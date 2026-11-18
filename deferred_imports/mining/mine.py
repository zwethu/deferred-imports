"""Mine one git repository into its SQLite event log, using plain git commands.

    index/<repo>.sqlite   tables in docs/schema.md; this module fills
                          run_info, commits, files, file_paths, file_changes, raw_imports, problems,
                          and edges.py the rest

How it works:
  1. One `git log --first-parent --diff-merges=first-parent --raw --numstat -M`
     gives every commit with its changed files. A merge is diffed against its
     first parent (^1), so one merged PR = one commit.
  2. One `git cat-file --batch` process reads the old and new blob of each
     changed .py file. tree-sitter parses both; only the difference in the set
     of imports becomes raw_imports rows.
  3. One `git log` over the whole history (all parents) gives the commits each
     merge brought in, so agent trailers on PR commits are not missed.
  4. Each file gets a file_id that a rename keeps (files, file_paths).
  5. edges.py then resolves the imports and lifts them to module edges.

The miner logs facts only. Rules, windows and thresholds are computed later
from these tables. Commit messages are not stored (PDPA, docs/schema.md).

A stopped run continues from run_info.last_i when started again. A finished
database is left alone; delete it to mine again.

Run (from the deferred-imports folder):
    uv run python -m deferred_imports.mining.mine ../corpus-clones/netbox --rev <pinned_sha>
Output goes to index/<repo>.sqlite and the salt to .salt (both ignored by git).
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import re
import secrets
import subprocess
import sys
import time
import warnings
from collections import Counter, OrderedDict
from datetime import UTC, datetime
from pathlib import Path

import tree_sitter_python
from tree_sitter import Language, Parser

from deferred_imports.mining import edges, schema

MINER_VERSION = "0.4.0"  # 0.4.0: if False: / if not TYPE_CHECKING: fix (15 Nov)
BATCH = 500  # commits per transaction
# A commit changing more files than this is flagged is_oversized (provisional; agree with the
# team). One such commit would otherwise give every module pair an opportunity.
OVERSIZED_FILES = 1000

# ---------------------------------------------------------------- labels

# Keep in sync with BUG_FIX_KEYWORDS in senso-framework/shared/mining/git_miner.py.
FIX_RE = re.compile(r"\b(fix(e[sd])?|bug(s|fix)?|hotfix|defect|fault|crash(es)?|regression|"
                    r"patch(ed)?|repair(ed)?|resolve[sd]?)\b", re.IGNORECASE)
# Same rule as scripts/screen_repo.sh: subject starts with "Revert " / "Revert:" / 'Revert"'.
REVERT_RE = re.compile(r'^revert( |:|")', re.IGNORECASE)
REVERTS_SHA_RE = re.compile(r"This reverts commit ([0-9a-f]{7,40})", re.IGNORECASE)

# Same patterns as AGENT in scripts/screen_repo.sh and docs/corpus-criteria.md,
# checked against "name <email>" and the message. Keep the three in sync.
AGENT_PATTERNS = [
    ("copilot", r"copilot-swe-agent|Copilot <"),
    ("devin", r"devin-ai-integration"),
    ("cursor", r"cursoragent@cursor\.com"),
    ("claude", r"noreply@anthropic\.com|Generated with \[?Claude Code"),
    ("aider", r"\(aider\)"),
    ("openhands", r"openhands@all-hands\.dev"),
    ("codex", r"codex@openai\.com"),
    ("jules", r"google-labs-jules"),
]
AGENT_RES = [(name, re.compile(rx, re.IGNORECASE)) for name, rx in AGENT_PATTERNS]


def find_agent(who: str, message: str) -> str:
    text = who + "\n" + message
    for name, rx in AGENT_RES:
        if rx.search(text):
            return name
    return ""


def load_salt(path: Path) -> str:
    """One salt for the whole corpus, so the same person hashes the same in every repo.
    The salt file must never be committed (PDPA)."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(16) + "\n")
        print(f"new salt written to {path} (keep it, do not commit it)", file=sys.stderr)
    return path.read_text().strip()


def hash_author(salt: str, email: str) -> str:
    return hashlib.sha256((salt + email.strip().lower()).encode()).hexdigest()[:16]


# ---------------------------------------------------------------- imports (tree-sitter)

PARSER = Parser(Language(tree_sitter_python.language()))

# Nodes that can hold statements. Imports never sit inside expressions, so we
# only walk into these (much faster than visiting every node).
WALK_INTO = {
    "module", "block", "if_statement", "elif_clause", "else_clause", "try_statement",
    "except_clause", "except_group_clause", "finally_clause", "with_statement",
    "for_statement", "while_statement", "function_definition", "class_definition",
    "decorated_definition", "match_statement", "case_clause", "ERROR",
}


def _clean(node) -> str:
    # Drop spaces and backslash line breaks inside a dotted name, as Python does.
    return re.sub(r"[\s\\]+", "", node.text.decode("utf-8", "replace"))


def _name(node) -> str:
    # `import a.b as x` -> "a.b"; the alias does not change the dependency.
    if node.type == "aliased_import":
        node = node.child_by_field_name("name")
    return _clean(node)


def _kind(stack: tuple) -> str:
    tags = []
    if "function_definition" in stack:
        tags.append("in_function")
    if "type_checking" in stack:
        tags.append("type_checking")
    if "try_statement" in stack:
        tags.append("try_except")
    return "+".join(tags) or "top_level"


def never_runs(cond: str) -> str | None:
    """Which part of `if <cond>:` never runs at runtime, so its imports are tagged type_checking.

    "body" for TYPE_CHECKING / x.TYPE_CHECKING / False, "else" (every elif and else part) for
    `not` of those, None otherwise. Other conditions that mention TYPE_CHECKING without `not`
    (`TYPE_CHECKING and x`) count as "body", as before. Only the `if` condition is read, not an
    `elif` one. verify.py has its own copy of this rule on purpose: keep the two the same."""
    c = " ".join(cond.split())
    while c.startswith("(") and c.endswith(")") and c.count("(") == 1:
        c = c[1:-1].strip()
    neg = c.startswith("not ")
    if neg:
        c = c[4:].strip()
        while c.startswith("(") and c.endswith(")") and c.count("(") == 1:
            c = c[1:-1].strip()
    simple = c == "False" or (c.split(".")[-1] == "TYPE_CHECKING"
                              and all(p.isidentifier() for p in c.split(".")))
    if simple:
        return "else" if neg else "body"
    if not neg and "TYPE_CHECKING" in c and "not" not in c.split():
        return "body"
    return None


def extract_imports(src: bytes) -> tuple[Counter, bool]:
    """Return (Counter of (import, kind), has_parse_error). One entry per imported name:
    `from a import b, c` -> "from a import b", "from a import c"."""
    tree = PARSER.parse(src)
    out: Counter = Counter()
    todo = [(tree.root_node, ())]
    while todo:
        node, ctx = todo.pop()
        t = node.type
        if t == "import_statement":
            for n in node.children_by_field_name("name"):
                out[(f"import {_name(n)}", _kind(ctx))] += 1
        elif t == "import_from_statement":
            mod = _clean(node.child_by_field_name("module_name"))
            names = node.children_by_field_name("name")
            if not names:  # wildcard
                out[(f"from {mod} import *", _kind(ctx))] += 1
            for n in names:
                out[(f"from {mod} import {_name(n)}", _kind(ctx))] += 1
        elif t in WALK_INTO:
            if t == "if_statement":
                cond = node.child_by_field_name("condition")
                side = never_runs(cond.text.decode("utf-8", "replace")) if cond else None
                if side:
                    # "body": the `if` body never runs; "else": every elif/else part never runs
                    body = node.child_by_field_name("consequence")
                    for c in node.children:
                        dead = (c == body) if side == "body" else \
                            c.type in ("elif_clause", "else_clause")
                        todo.append((c, ctx + ("type_checking",) if dead else ctx))
                    continue
            sub = ctx + (t,) if t in ("function_definition", "try_statement") else ctx
            for c in node.children:
                todo.append((c, sub))
    return out, tree.root_node.has_error


def split_stmt(stmt: str) -> tuple[str, str | None, int]:
    """Split an import from extract_imports into (module, name, level) for raw_imports.

    "from ..db import session" -> ("db", "session", 2); "import a.b" -> ("a.b", None, 0)."""
    if stmt.startswith("import "):
        return stmt[len("import "):], None, 0
    mod, name = stmt[len("from "):].split(" import ", 1)
    level = len(mod) - len(mod.lstrip("."))
    return mod[level:], name, level


# ---------------------------------------------------------------- git plumbing

NULL_SHA = "0" * 40
CHANGE = {"A": "A", "M": "M", "D": "D", "R": "R", "C": "C", "T": "M"}  # T = type change
MARK = "\x02\x03"


def git(repo: Path, *args: str) -> str:
    # errors="replace": old commits can hold Latin-1 names or broken UTF-8 in messages.
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True, errors="replace").stdout


class Blobs:
    """One long-running `git cat-file --batch`, with a small cache of parsed blobs
    (the new blob of one commit is usually the old blob of a later one)."""

    def __init__(self, repo: Path, cache_size: int = 20000):
        self.p = subprocess.Popen(["git", "-C", str(repo), "cat-file", "--batch"],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        self.cache: OrderedDict = OrderedDict()
        self.cache_size = cache_size

    def read(self, sha: str) -> bytes:
        self.p.stdin.write(sha.encode() + b"\n")
        self.p.stdin.flush()
        header = self.p.stdout.readline().split()
        if len(header) < 3 or header[1] != b"blob":
            return b""
        data = self.p.stdout.read(int(header[2]))
        self.p.stdout.read(1)  # trailing newline
        return data

    def parse(self, sha: str) -> tuple[Counter, int, bool]:
        """(imports, line count, has_parse_error) of one .py blob."""
        if sha == NULL_SHA:
            return Counter(), 0, False
        if sha in self.cache:
            self.cache.move_to_end(sha)
            return self.cache[sha]
        data = self.read(sha)
        imps, err = extract_imports(data)
        loc = data.count(b"\n") + (bool(data) and not data.endswith(b"\n"))
        self.cache[sha] = (imps, loc, err)
        if len(self.cache) > self.cache_size:
            self.cache.popitem(last=False)
        return self.cache[sha]

    def same_ast(self, old_sha: str, new_sha: str) -> bool:
        """True if two .py blobs have the same Python AST: only formatting or comments differ.
        False if either does not parse as Python 3."""
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")  # invalid escapes etc. in old code
                return (ast.dump(ast.parse(self.read(old_sha)))
                        == ast.dump(ast.parse(self.read(new_sha))))
        except (SyntaxError, ValueError, RecursionError, MemoryError):  # ValueError: NUL bytes
            return False

    def close(self):
        self.p.stdin.close()
        self.p.wait()


def iter_log(repo: Path, rev: str):
    """Yield one dict per first-parent commit, oldest first."""
    fmt = MARK + "%H%x00%P%x00%cI%x00%an%x00%ae%x00%B%x00"
    cmd = ["git", "-C", str(repo), "-c", "core.quotepath=off", "log", "--first-parent",
           "--diff-merges=first-parent", "--reverse", "-z", "--raw", "--numstat", "-M",
           "--no-abbrev", f"--format={fmt}", rev]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    buf = b"\x00"
    while True:
        chunk = p.stdout.read(1 << 20)
        if chunk:
            buf += chunk
        # A commit starts with NUL + MARK. The NUL keeps a MARK inside a message from
        # matching (the message is never preceded by NUL + MARK).
        parts = buf.split(b"\x00" + MARK.encode())
        # keep the last (maybe incomplete) part unless the stream ended
        done, buf = (parts, b"") if not chunk else (parts[:-1], parts[-1])
        for part in done:
            if part:
                yield parse_commit(part.decode("utf-8", "replace"))
        if not chunk:
            break
    if p.wait() != 0:
        raise RuntimeError("git log failed")


RAW_RE = re.compile(r"^:\d{6} \d{6} [0-9a-f]{40} [0-9a-f]{40} [A-Z]\d*$")


def parse_commit(text: str) -> dict:
    sha, parents, date, name, email, message, rest = text.split("\x00", 6)
    toks = rest.lstrip("\x00\n").split("\x00")
    files, stats = [], {}
    k = 0
    while k < len(toks):
        tok = toks[k].lstrip("\n")
        if not tok:
            k += 1
            continue
        if RAW_RE.match(tok):
            _, new_mode, old_sha, new_sha, status = tok[1:].split(" ")
            letter = status[0]
            if letter in "RC":
                old_path, path = toks[k + 1], toks[k + 2]
                k += 3
            else:
                old_path = path = toks[k + 1]
                k += 2
            files.append({"change": CHANGE.get(letter, "M"), "path": path,
                          "old_path": old_path if letter in "RC" else "",
                          "old_sha": old_sha, "new_sha": new_sha, "new_mode": new_mode,
                          "old_mode": tok[1:7]})
        else:  # numstat: "added\tdeleted\tpath" or "added\tdeleted\t" + old + new
            added, deleted, path = tok.split("\t", 2)
            if path:
                k += 1
            else:
                path = toks[k + 2]
                k += 3
            # "-" means a binary file: no line counts
            stats[path] = (None if added == "-" else int(added),
                           None if deleted == "-" else int(deleted))
    for f in files:
        f["added"], f["deleted"] = stats.get(f["path"], (None, None))
    return {"hash": sha, "parents": parents.split(), "date": date, "name": name,
            "email": email, "message": message.strip(), "files": files}


def merge_contents(repo: Path, rev: str, first_parent: list[str]) -> dict[str, list[tuple]]:
    """For each first-parent merge, the (who, message) of the side commits it brought in."""
    # -z ends each commit with NUL. NUL cannot appear in a commit message, but any other
    # byte can (netbox has messages with \x01), so NUL is the only safe separator.
    out = git(repo, "log", "-z", "--format=%H%x00%P%x00%an <%ae>%x00%B", rev)
    fields = out.split("\x00")
    info, parents = {}, {}
    for k in range(0, len(fields) - 3, 4):
        sha, ps, who, msg = fields[k:k + 4]
        info[sha] = (who, msg)
        parents[sha] = ps.split()
    seen, brought = set(), {}
    for sha in first_parent:  # oldest first
        side = []
        todo = list(parents.get(sha, [])[1:])
        while todo:
            c = todo.pop()
            if c in seen or c not in info:
                continue
            seen.add(c)
            side.append(info[c])
            todo.extend(parents[c])
        if side:
            brought[sha] = side
        seen.add(sha)
    return brought


def is_py(path: str, mode: str) -> bool:
    return path.endswith(".py") and mode in ("100644", "100755")


def blame_ignore_revs(repo: Path, rev: str) -> set[str]:
    """Commits the project lists in .git-blame-ignore-revs as reformatting (at the pinned SHA)."""
    try:
        text = git(repo, "show", f"{rev}:.git-blame-ignore-revs")
    except subprocess.CalledProcessError:
        return set()
    shas = (line.split("#", 1)[0].strip() for line in text.splitlines())
    return {s for s in shas if re.fullmatch(r"[0-9a-f]{40}", s)}


# ---------------------------------------------------------------- file identity

class FileIds:
    """Stable file ids across renames: writes `files` and `file_paths` (docs/schema.md, B).

    A rename keeps the id. Add and copy give a new id, and so does a file that comes back
    at a path deleted earlier."""

    def __init__(self, con):
        self.con = con
        rows = con.execute("SELECT file_id, path, from_i FROM file_paths WHERE to_i IS NULL")
        self.live = {path: (fid, from_i) for fid, path, from_i in rows}  # path -> open interval
        self.next = (con.execute("SELECT MAX(file_id) FROM files").fetchone()[0] or 0) + 1
        self.unknown = 0  # changes to a path the walk never saw added: a miner bug if > 0

    def _new(self, path: str, i: int) -> int:
        fid, self.next = self.next, self.next + 1
        self.con.execute("INSERT INTO files VALUES (?, ?)", (fid, i))
        self._open(fid, path, i)
        return fid

    def _open(self, fid: int, path: str, i: int) -> None:
        self.con.execute("INSERT INTO file_paths VALUES (?, ?, ?, NULL)", (fid, path, i))
        self.live[path] = (fid, i)

    def _close(self, path: str, i: int) -> int | None:
        if path not in self.live:
            self.unknown += 1
            return None
        fid, from_i = self.live.pop(path)
        self.con.execute("UPDATE file_paths SET to_i = ? WHERE file_id = ? AND from_i = ?",
                         (i, fid, from_i))
        return fid

    def apply(self, i: int, files: list[dict]) -> list[int]:
        """The file id of each changed file of commit i, in order."""
        ids: list[int | None] = [None] * len(files)
        # Deletes and renames first free their old path, so a path reused in the same
        # commit (a renamed away, a new a added) is not confused with the old file.
        for k, f in enumerate(files):
            if f["change"] in ("D", "R"):
                ids[k] = self._close(f["old_path"] or f["path"], i)
        for k, f in enumerate(files):
            change, path = f["change"], f["path"]
            if change == "R" and ids[k] is not None:
                self._open(ids[k], path, i)
            elif change == "D":
                if ids[k] is None:  # unknown path: give it an id that is closed at once
                    ids[k] = self._new(path, i)
                    self._close(path, i)
            elif change == "M" and path in self.live:
                ids[k] = self.live[path][0]
            else:  # A, C, or M / R of a path never seen (R was counted in _close)
                self.unknown += change == "M"
                if path in self.live:
                    self._close(path, i)
                ids[k] = self._new(path, i)
        return ids


# ---------------------------------------------------------------- main

def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _set_info(con, **values) -> None:
    con.executemany("INSERT OR REPLACE INTO run_info VALUES (?, ?)",
                    [(k, str(v)) for k, v in values.items()])


def mine(repo: Path, rev: str, db_path: Path, salt: str, limit: int | None = None,
         extra_roots: list[str] = ()) -> None:
    rev_sha = git(repo, "rev-parse", rev).strip()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = schema.connect(db_path)
    con.execute("PRAGMA synchronous = NORMAL")  # safe with WAL; much faster commits
    info = dict(con.execute("SELECT key, value FROM run_info"))
    if "finished" in info:
        print(f"{db_path} is already complete; delete it to mine again", file=sys.stderr)
        con.close()
        return
    if info and (info["pinned_sha"], info["miner_version"]) != (rev_sha, MINER_VERSION):
        con.close()
        raise RuntimeError(f"{db_path} was started at another commit or miner version: "
                           "delete it and mine again")
    last_i = int(info.get("last_i", -1))
    if not info:
        tree = git(repo, "-c", "core.quotepath=off", "ls-tree", "-r", "-z", "--name-only",
                   rev_sha).split("\x00")
        listed_roots, py2_until = edges.listed(repo.name)
        roots = edges.source_roots([p for p in tree if p], [*listed_roots, *extra_roots])
        _set_info(con, repo=repo.name, pinned_sha=rev_sha, miner_version=MINER_VERSION,
                  started=_now(), last_i=-1, source_roots=";".join(roots), py2_until=py2_until)
        con.commit()

    first_parent = git(repo, "rev-list", "--first-parent", "--reverse", rev_sha).split()
    total = len(first_parent) if limit is None else min(limit, len(first_parent))
    start = f", resuming after commit {last_i}" if last_i >= 0 else ""
    print(f"{repo.name}: {total} first-parent commits up to {rev_sha[:12]}{start}",
          file=sys.stderr)
    brought = merge_contents(repo, rev_sha, first_parent)
    ignore_revs = blame_ignore_revs(repo, rev_sha)
    _set_info(con, oversized_files=OVERSIZED_FILES)

    blobs = Blobs(repo)
    ids = FileIds(con)
    t0 = time.time()
    for i, c in enumerate(iter_log(repo, rev_sha)):
        if i >= total:
            break
        if i <= last_i:
            continue
        msg = c["message"]
        agent = find_agent(f"{c['name']} <{c['email']}>", msg)
        for who, side_msg in brought.get(c["hash"], []):
            agent = agent or find_agent(who, side_msg)
        reverts = REVERTS_SHA_RE.search(msg)
        is_revert = bool(REVERT_RE.match(msg))
        con.execute(
            "INSERT INTO commits (i, sha, date, author_hash, n_parents, n_files, is_fix, "
            "is_revert, reverts_sha, is_agent, agent, is_oversized) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (i, c["hash"], c["date"], hash_author(salt, c["email"]), len(c["parents"]),
             len(c["files"]), int(bool(FIX_RE.search(msg)) and not is_revert), int(is_revert),
             reverts.group(1) if reverts else None, int(bool(agent)), agent or None,
             int(len(c["files"]) > OVERSIZED_FILES)))
        imports_changed = False

        for f, fid in zip(c["files"], ids.apply(i, c["files"])):
            old_py = is_py(f["old_path"] or f["path"], f["old_mode"])
            new_py = is_py(f["path"], f["new_mode"])
            before = blobs.parse(f["old_sha"])[0] if old_py else Counter()
            after, loc, err = blobs.parse(f["new_sha"]) if new_py else (Counter(), None, None)
            con.execute("INSERT INTO file_changes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (i, fid, f["change"], f["path"], f["old_path"] or None, f["added"],
                         f["deleted"], loc, None if err is None else int(err)))
            if err:
                con.execute("INSERT INTO problems VALUES (?, ?, 'parse_error', ?)",
                            (i, fid, f["path"]))
            # A deleted file's imports are all logged as removed, against its own file id.
            rows = [(i, fid, delta, stmt, *split_stmt(stmt), kind)
                    for delta, diff in ((-1, before - after), (1, after - before))
                    for (stmt, kind), n in sorted(diff.items()) for _ in range(n)]
            con.executemany("INSERT INTO raw_imports VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
            imports_changed = imports_changed or bool(rows)

        # Reformatting: listed by the project, or every change is a .py edit with the same AST
        # (the import check first, because it is free).
        if c["hash"] in ignore_revs or (
                c["files"] and not imports_changed
                and all(f["change"] == "M" and is_py(f["path"], f["old_mode"])
                        and is_py(f["path"], f["new_mode"]) for f in c["files"])
                and all(blobs.same_ast(f["old_sha"], f["new_sha"]) for f in c["files"])):
            con.execute("UPDATE commits SET is_format_only = 1 WHERE i = ?", (i,))

        if (i + 1) % BATCH == 0 or i == total - 1:
            _set_info(con, last_i=i)
            con.commit()
            rate = (i - last_i) / (time.time() - t0)
            print(f"  {i + 1}/{total} commits, {rate:.0f}/s", file=sys.stderr)
    blobs.close()

    print(f"{repo.name}: resolving imports and lifting to modules", file=sys.stderr)
    edge_stats = edges.build(con)

    def count(sql: str) -> int:
        return con.execute(sql).fetchone()[0] or 0

    stats = {
        "n_commits": count("SELECT COUNT(*) FROM commits"),
        "n_file_changes": count("SELECT COUNT(*) FROM file_changes"),
        "n_raw_imports": count("SELECT COUNT(*) FROM raw_imports"),
        "n_agent_commits": count("SELECT SUM(is_agent) FROM commits"),
        "n_parse_errors": count("SELECT COUNT(*) FROM file_changes WHERE parse_error = 1"),
        "n_format_only": count("SELECT SUM(is_format_only) FROM commits"),
        "n_oversized": count("SELECT SUM(is_oversized) FROM commits"),
        "n_unknown_paths": int(info.get("n_unknown_paths", 0)) + ids.unknown,
    }
    secs = time.time() - t0
    complete = total == len(first_parent)
    if complete:  # a --limit run stays open, so a later run without --limit continues it
        stats["finished"] = _now()
    _set_info(con, seconds=f"{secs:.0f}", **stats)
    con.commit()
    con.close()
    status = "done" if complete else "stopped at --limit (run again without it to continue)"
    print(f"{status} in {secs:.0f}s: " + ", ".join(
        f"{v} {k[2:].replace('_', ' ')}" for k, v in stats.items() if k.startswith("n_"))
        + f" -> {db_path}", file=sys.stderr)
    print("edges: " + ", ".join(f"{v} {k[2:].replace('_', ' ')}" for k, v in edge_stats.items()
                                if k.startswith("n_")), file=sys.stderr)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repo", type=Path, help="path to a local clone")
    ap.add_argument("--rev", default="HEAD", help="pinned commit sha to mine up to (default HEAD)")
    ap.add_argument("--out", type=Path, help="database file (default index/<repo name>.sqlite)")
    ap.add_argument("--salt-file", type=Path, default=Path(".salt"),
                    help="salt for hashing author emails; created if missing (default ./.salt). "
                         "Use the same file for every repo; never commit it.")
    ap.add_argument("--limit", type=int, help="only the first N commits (for testing)")
    ap.add_argument("--source-roots", default="",
                    help="extra source roots, comma-separated (also read from "
                         "corpus/resolver.csv)")
    a = ap.parse_args(argv)
    repo = a.repo.resolve()
    mine(repo, a.rev, a.out or Path("index") / f"{repo.name}.sqlite", load_salt(a.salt_file),
         a.limit, [r for r in a.source_roots.split(",") if r])


if __name__ == "__main__":
    main()
