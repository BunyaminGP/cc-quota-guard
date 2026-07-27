#!/usr/bin/env bash
# install.sh — MANUAL fallback installer for Claude Code versions that
# don't have the plugin system yet. If your `claude` supports `/plugin`,
# prefer that instead:
#
#   /plugin marketplace add BunyaminGP/cc-quota-guard
#   /plugin install cc-quota-guard
#
# This script copies the tool into ~/.claude/cc-quota-guard/ and merges the
# PostToolUse hooks into ~/.claude/settings.json (idempotent, via python3).
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/.claude/cc-quota-guard"
SETTINGS="$HOME/.claude/settings.json"

command -v python3 >/dev/null || { echo "python3 is required." >&2; exit 1; }

echo "→ Copying files to: $DEST"
mkdir -p "$DEST/scripts" "$DEST/bin" "$DEST/templates"
cp "$SRC/scripts/quota_gate.py" "$DEST/scripts/"
cp "$SRC/scripts/usage.py"      "$DEST/scripts/"
cp "$SRC/bin/cc-run"            "$DEST/bin/"
cp "$SRC/templates/progress.md" "$DEST/templates/" 2>/dev/null || true
chmod +x "$DEST/bin/cc-run" "$DEST/scripts/quota_gate.py" "$DEST/scripts/usage.py"

HOOK_SCRIPT="$DEST/scripts/quota_gate.py"

echo "→ Updating settings.json: $SETTINGS"
python3 - "$SETTINGS" "$HOOK_SCRIPT" <<'PY'
import json, os, sys
settings_path, hook_script = sys.argv[1], sys.argv[2]
os.makedirs(os.path.dirname(settings_path), exist_ok=True)
try:
    with open(settings_path) as f:
        cfg = json.load(f)
except Exception:
    cfg = {}

hooks = cfg.setdefault("hooks", {})
ptu = hooks.setdefault("PostToolUse", [])

# Two matchers are needed:
#   - "TodoWrite": records todo state + checks the SOFT threshold.
#   - "*"        : checks the HARD threshold on EVERY tool call (so a quota
#                  spike in the middle of an item is caught promptly).
WANTED_MATCHERS = ["TodoWrite", "*"]

def has_entry(matcher):
    for entry in ptu:
        if entry.get("matcher") == matcher:
            for h in entry.get("hooks", []):
                if h.get("command") == "python3" and h.get("args") == [hook_script]:
                    return True
    return False

added = []
for matcher in WANTED_MATCHERS:
    if not has_entry(matcher):
        ptu.append({
            "matcher": matcher,
            "hooks": [{"type": "command", "command": "python3", "args": [hook_script], "timeout": 20}],
        })
        added.append(matcher)

if added:
    with open(settings_path, "w") as f:
        json.dump(cfg, f, indent=2)
    print(f"   Added PostToolUse matchers: {', '.join(added)}")
else:
    print("   Hooks already registered, nothing changed.")
PY

# Optional PATH shortcut for cc-run (only if ~/.local/bin exists)
if [[ -d "$HOME/.local/bin" ]]; then
  ln -sf "$DEST/bin/cc-run" "$HOME/.local/bin/cc-run"
  echo "→ Linked 'cc-run' into ~/.local/bin."
else
  echo "→ Run it directly: $DEST/bin/cc-run"
fi

echo
echo "✅ Install complete."
echo
echo "By default, the HARD threshold only forces a clean stop — nothing is"
echo "reverted automatically. To opt into auto-revert (git stash) of the"
echo "in-progress item, pass --enable-hard-abort to cc-run, or set"
echo "CC_HARD_ABORT=1 / .cc-quota/config.json { \"hard_abort_enabled\": true }."
echo "Read the README before turning this on."
echo
echo "Verify:"
echo "  1) Is usage readable:     python3 $DEST/scripts/usage.py"
echo "  2) API schema (if needed): python3 $DEST/scripts/usage.py --probe"
echo "  3) Set thresholds (e.g.):  cc-run --threshold 80 --session-hard 95 --weekly-hard 98 \"task...\""
echo
echo "Note: to upgrade an older install (only had the TodoWrite matcher),"
echo "      just re-run this script — it adds the missing '*' matcher."
