#!/usr/bin/env python3
"""
stream_render.py — reads Claude Code's `--output-format stream-json` event
stream from stdin and renders a readable, live view to stdout: which model
is actually running (aliases like "opus" resolve to a specific dated model
— this is the only place that resolution is visible), assistant text as it
arrives, which tools are being called, and a final cost/model-usage
summary.

Used by cc-run so a headless run isn't silent and so you can see exactly
which model version ran, not just which alias you asked for. This does not
cost anything extra — it's the same underlying run, just parsed instead of
printed as plain text.

Usage: claude ... --output-format stream-json --verbose | python3 stream_render.py
"""

import json
import sys

# On Windows, stdout's encoding follows the system codepage (e.g. cp1254),
# which can't represent emoji and raises UnicodeEncodeError on print().
# Force UTF-8 regardless of locale; no-op on platforms where it's already
# UTF-8. Requires Python 3.7+ (already required elsewhere in this project).
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def main():
    model_reported = False
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except Exception:
            continue

        etype = event.get("type")

        if etype == "system" and event.get("subtype") == "init":
            if not model_reported:
                print(f"🧠 [cc-run] model: {event.get('model', 'unknown')}", flush=True)
                model_reported = True

        elif etype == "assistant":
            content = ((event.get("message") or {}).get("content")) or []
            for block in content:
                btype = block.get("type")
                if btype == "text" and block.get("text"):
                    print(block["text"], flush=True)
                elif btype == "tool_use":
                    print(f"   [tool] {block.get('name', '?')}", flush=True)

        elif etype == "result":
            usage = event.get("modelUsage") or {}
            models = ", ".join(usage.keys()) if usage else event.get("model", "unknown")
            cost = event.get("total_cost_usd")
            if cost is not None:
                print(f"💲 [cc-run] model(s) used: {models} — cost: ${cost:.4f}", flush=True)
            else:
                print(f"💲 [cc-run] model(s) used: {models}", flush=True)


if __name__ == "__main__":
    main()
