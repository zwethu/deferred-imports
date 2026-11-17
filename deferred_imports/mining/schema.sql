-- SENSO-Lens event log: one SQLite file per repository, index/<repo>.sqlite.
-- Every table and column is explained in docs/schema.md.
--
-- Conventions
--   i            commit number in first-parent order, oldest first (0, 1, 2 ...): the time axis
--   from_i/to_i  an interval: valid for from_i <= i < to_i; to_i NULL = still valid at the pinned SHA
--   delta        +1 / -1 for one event; module_edges holds the net change per commit
--
-- Bump user_version (and SCHEMA_VERSION in schema.py) on any change; old databases are then re-mined.

PRAGMA journal_mode = WAL;

-- A. About this run ------------------------------------------------------------------------------

CREATE TABLE run_info (
  key   TEXT PRIMARY KEY,  -- repo, pinned_sha, miner_version, started, finished, last_i,
                           -- source_roots, exclude_regex, n_external_imports
  value TEXT NOT NULL
);

-- B. Commits and files ---------------------------------------------------------------------------

CREATE TABLE commits (
  i              INTEGER PRIMARY KEY,
  sha            TEXT    NOT NULL UNIQUE,
  date           TEXT    NOT NULL,            -- committer date, ISO 8601
  author_hash    TEXT    NOT NULL,            -- salted hash of the email, never the email (PDPA)
  n_parents      INTEGER NOT NULL,            -- 2 or more = merge commit
  n_files        INTEGER NOT NULL,
  is_fix         INTEGER NOT NULL CHECK (is_fix IN (0, 1)),
  is_revert      INTEGER NOT NULL CHECK (is_revert IN (0, 1)),
  reverts_sha    TEXT,                        -- from "This reverts commit ...", if named
  is_agent       INTEGER NOT NULL CHECK (is_agent IN (0, 1)),
  agent          TEXT,                        -- copilot, claude, cursor ...
  is_format_only INTEGER NOT NULL DEFAULT 0 CHECK (is_format_only IN (0, 1)),
  is_oversized   INTEGER NOT NULL DEFAULT 0 CHECK (is_oversized IN (0, 1))
);

CREATE TABLE files (
  file_id INTEGER PRIMARY KEY,
  first_i INTEGER NOT NULL REFERENCES commits (i)
);

CREATE TABLE file_paths (
  file_id INTEGER NOT NULL REFERENCES files (file_id),
  path    TEXT    NOT NULL,
  from_i  INTEGER NOT NULL,                   -- commit that added or renamed the file to this path
  to_i    INTEGER,                            -- commit that renamed or deleted it
  PRIMARY KEY (file_id, from_i)
);

CREATE TABLE file_changes (
  i           INTEGER NOT NULL REFERENCES commits (i),
  file_id     INTEGER NOT NULL REFERENCES files (file_id),
  change      TEXT    NOT NULL CHECK (change IN ('A', 'M', 'D', 'R', 'C')),
  path        TEXT    NOT NULL,               -- path after the commit (for D: before)
  old_path    TEXT,                           -- for R and C
  added       INTEGER,                        -- lines; NULL for binary files
  deleted     INTEGER,
  loc_after   INTEGER,                        -- .py only
  parse_error INTEGER CHECK (parse_error IN (0, 1)),  -- .py only
  PRIMARY KEY (i, file_id)
);

-- C. Imports and file edges ----------------------------------------------------------------------

CREATE TABLE raw_imports (
  i       INTEGER NOT NULL REFERENCES commits (i),
  file_id INTEGER NOT NULL REFERENCES files (file_id),
  delta   INTEGER NOT NULL CHECK (delta IN (-1, 1)),
  stmt    TEXT    NOT NULL,                   -- "from ..db import session", one imported name per row
  module  TEXT    NOT NULL,                   -- "db"; '' for "from . import x"
  name    TEXT,                               -- "session"; NULL for "import a.b"
  level   INTEGER NOT NULL CHECK (level >= 0),  -- leading dots: 0 = absolute
  kind    TEXT    NOT NULL                    -- top_level, or in_function / type_checking /
                                              -- try_except joined with '+'
);

CREATE TABLE file_edges (
  i        INTEGER NOT NULL REFERENCES commits (i),
  src_file INTEGER NOT NULL REFERENCES files (file_id),
  dst_file INTEGER NOT NULL REFERENCES files (file_id),
  delta    INTEGER NOT NULL CHECK (delta IN (-1, 1)),
  kind     TEXT    NOT NULL,
  cause    TEXT    NOT NULL CHECK (cause IN ('import', 'resolve', 'delete'))
);

-- D. Modules and module edges --------------------------------------------------------------------

CREATE TABLE modules (
  module_id INTEGER PRIMARY KEY,
  name      TEXT    NOT NULL,                 -- dotted: "dcim.models"
  from_i    INTEGER NOT NULL,                 -- commit that added __init__.py
  to_i      INTEGER,                          -- commit that deleted it
  excluded  TEXT CHECK (excluded IN ('tests', 'docs', 'examples', 'migrations', 'vendor', 'build'))
);

CREATE TABLE file_modules (
  file_id   INTEGER NOT NULL REFERENCES files (file_id),
  module_id INTEGER NOT NULL REFERENCES modules (module_id),
  from_i    INTEGER NOT NULL,
  to_i      INTEGER,
  PRIMARY KEY (file_id, from_i)
);

CREATE TABLE module_edges (
  i       INTEGER NOT NULL REFERENCES commits (i),
  src_mod INTEGER NOT NULL REFERENCES modules (module_id),
  dst_mod INTEGER NOT NULL REFERENCES modules (module_id),
  delta   INTEGER NOT NULL CHECK (delta <> 0),  -- net change in the edge weight at commit i
  kind    TEXT    NOT NULL,
  cause   TEXT    NOT NULL CHECK (cause IN ('import', 'resolve', 'move', 'module')),
  CHECK (src_mod <> dst_mod),
  PRIMARY KEY (i, src_mod, dst_mod, kind, cause)
);

CREATE TABLE module_touches (
  i         INTEGER NOT NULL REFERENCES commits (i),
  module_id INTEGER NOT NULL REFERENCES modules (module_id),
  n_files   INTEGER NOT NULL CHECK (n_files > 0),
  PRIMARY KEY (module_id, i)
);

-- E. Bookkeeping ---------------------------------------------------------------------------------

CREATE TABLE problems (
  i       INTEGER,
  file_id INTEGER,
  kind    TEXT NOT NULL CHECK (kind IN ('parse_error', 'unresolved', 'oversized', 'encoding')),
  detail  TEXT
);

CREATE TABLE splits (                          -- written later by task G-07, not by the miner
  name   TEXT    PRIMARY KEY CHECK (name IN ('induce', 'calibrate', 'test')),
  from_i INTEGER NOT NULL,
  to_i   INTEGER NOT NULL
);

CREATE INDEX idx_file_paths_path   ON file_paths (path);
CREATE INDEX idx_raw_imports_file  ON raw_imports (file_id, i);
CREATE INDEX idx_file_edges_src    ON file_edges (src_file, i);
CREATE INDEX idx_file_edges_dst    ON file_edges (dst_file, i);
CREATE INDEX idx_modules_name      ON modules (name);
CREATE INDEX idx_module_edges_pair ON module_edges (src_mod, dst_mod, i);
CREATE INDEX idx_module_touches_i  ON module_touches (i);

PRAGMA user_version = 2;
