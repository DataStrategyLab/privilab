#!/bin/sh
set -eu

GITLEAKS=".tools/bin/gitleaks"

if [ ! -x "$GITLEAKS" ]; then
    echo "missing pinned Gitleaks; setup is held: see docs/release-status.md" >&2
    exit 1
fi

temp_dir="$(mktemp -d)"
trap 'rm -rf "$temp_dir"' EXIT HUP INT TERM
worktree="$temp_dir/worktree"
mkdir -p "$worktree"

if git rev-parse --verify HEAD >/dev/null 2>&1; then
    "$GITLEAKS" git . --no-banner --redact
fi

git ls-files --cached --others --exclude-standard |
while IFS= read -r path; do
    if [ -f "$path" ] || [ -L "$path" ]; then
        mkdir -p "$worktree/$(dirname "$path")"
        cp -P "$path" "$worktree/$path"
    fi
done

"$GITLEAKS" dir "$worktree" --no-banner --redact
