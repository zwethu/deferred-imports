#!/usr/bin/env bash
# Clone every repo in corpus/paper-corpus.csv into ../clones/<name> (full history).
# A clone that already exists is only fetched. One failure does not stop the others.
# Run from the repo root:
#     bash scripts/clone_corpus.sh
CLONES="${CLONES:-../clones}"
mkdir -p "$CLONES"
failed=()
# read columns by header name, so column order does not matter
while IFS=' ' read -r name url sha; do
  dir="$CLONES/$name"
  if [ -d "$dir/.git" ]; then
    echo "== $name: fetch"; git -C "$dir" fetch --quiet origin || { failed+=("$name"); continue; }
  else
    echo "== $name: clone"; git clone --quiet "$url" "$dir" || { failed+=("$name"); continue; }
  fi
  # the pinned commit can be on a non-default branch (osf.io, archivematica)
  git -C "$dir" cat-file -e "$sha^{commit}" 2>/dev/null \
    || git -C "$dir" fetch --quiet origin "$sha" \
    || { echo "!! $name: pinned commit $sha not found"; failed+=("$name"); }
done < <(python3 -c '
import csv, sys
for r in csv.DictReader(open("corpus/paper-corpus.csv")):
    print(r["name"], r["url"], r["pinned_sha"])')
if [ ${#failed[@]} -gt 0 ]; then echo "failed: ${failed[*]}"; exit 1; fi
echo "done: all cloned"
