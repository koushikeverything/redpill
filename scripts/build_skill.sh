#!/usr/bin/env bash
# Package the skill source into a distributable .skill bundle.
#   skill/redpill-inventory/  ->  dist/redpill-inventory.skill
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL_DIR="$ROOT/skill"
NAME="redpill-inventory"
OUT="$ROOT/dist/$NAME.skill"

if [[ ! -f "$SKILL_DIR/$NAME/SKILL.md" ]]; then
  echo "error: $SKILL_DIR/$NAME/SKILL.md not found — nothing to package." >&2
  exit 1
fi

mkdir -p "$ROOT/dist"
rm -f "$OUT"

# A .skill is a zip of the skill folder (so it extracts to redpill-inventory/...).
# -X strips extra file attributes; exclude junk for a clean, reproducible bundle.
( cd "$SKILL_DIR" && zip -r -X "$OUT" "$NAME" \
    -x '*.DS_Store' -x '*__pycache__*' -x '*.pyc' >/dev/null )

echo "Built $OUT"
unzip -l "$OUT"
