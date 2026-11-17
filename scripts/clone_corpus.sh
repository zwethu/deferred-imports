#!/usr/bin/env bash
# Clone every repo in corpus/paper-corpus.csv into ../clones/<name> (full history).
# A clone that already exists is only fetched. Run from the repo root:
#     bash scripts/clone_corpus.sh
set -euo pipefail
CLONES="${CLONES:-../clones}"
mkdir -p "$CLONES"
tail -n +2 corpus/paper-corpus.csv | while IFS=, read -r name group url kind sha rest; do
  dir="$CLONES/$name"
  if [ -d "$dir/.git" ]; then
    echo "== $name: fetch"; git -C "$dir" fetch --quiet origin
  else
    echo "== $name: clone"; git clone --quiet "$url" "$dir"
  fi
  # the pinned commit can be on a non-default branch (osf.io, archivematica)
  git -C "$dir" cat-file -e "$sha^{commit}" 2>/dev/null \
    || git -C "$dir" fetch --quiet origin "$sha" \
    || echo "!! $name: pinned commit $sha not found"
done
echo "done"
