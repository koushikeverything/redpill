#!/usr/bin/env bash
# Fold an edited .skill bundle back into the repo source of truth.
# Use this when you edited the skill inside Claude and got a new .skill file.
#   ./scripts/sync_from_skill.sh ~/Downloads/redpill-inventory.skill
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME="redpill-inventory"
SRC="${1:-}"

if [[ -z "$SRC" ]]; then
  echo "usage: $0 <path-to.skill>" >&2
  exit 1
fi
if [[ ! -f "$SRC" ]]; then
  echo "error: '$SRC' not found." >&2
  exit 1
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

unzip -q -o "$SRC" -d "$TMP"

# The bundle should contain a top-level redpill-inventory/ folder.
if [[ ! -d "$TMP/$NAME" ]]; then
  echo "error: bundle has no top-level '$NAME/' folder. Contents:" >&2
  ( cd "$TMP" && find . -maxdepth 2 ) >&2
  exit 1
fi

# Replace the source tree wholesale so deletions in the bundle propagate too.
rm -rf "$ROOT/skills/$NAME"
cp -R "$TMP/$NAME" "$ROOT/skills/$NAME"

echo "Synced '$SRC' -> skills/$NAME"
echo "Review changes, then commit:"
echo "  git -C \"$ROOT\" add -A && git -C \"$ROOT\" status"
