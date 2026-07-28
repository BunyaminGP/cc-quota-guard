#!/usr/bin/env python3
"""
usage.py — Claude Code usage (rate-limit) reader.

Source: Anthropic's UNDOCUMENTED OAuth usage endpoint:
    GET https://api.anthropic.com/api/oauth/usage
    headers: Authorization: Bearer <token>, anthropic-beta: oauth-2025-04-20
Token: ~/.claude/.credentials.json -> .claudeAiOauth.accessToken

This endpoint is unofficial; Anthropic can change or remove it without
notice. That's why get_usage() raises on any problem, and the caller is
expected to FAIL-OPEN (i.e. never block Claude just because usage couldn't
be read).

Response field names (confirmed from the live API):
    .five_hour.utilization   (0-100 percent)
    .five_hour.resets_at     (ISO 8601)
    .seven_day.utilization
    .seven_day.resets_at
    .seven_day_sonnet.*      (optional)

Library usage:
    from usage import get_usage
    u = get_usage()          # {"session": {...}, "week_all": {...}, ...}

CLI:
    python3 usage.py           -> prints a summary
    python3 usage.py --probe   -> prints the RAW API response (schema check)
    python3 usage.py --json    -> normalized JSON
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error

HOME = os.path.expanduser("~")
CREDENTIALS_FILE = os.environ.get(
    "CC_CREDENTIALS_FILE", os.path.join(HOME, ".claude", ".credentials.json")
)
CACHE_FILE = os.environ.get(
    "CC_USAGE_CACHE", os.path.join(HOME, ".claude", ".cc-quota-cache.json")
)
# Cache TTL (seconds) so we don't hammer the API. The hook now fires on
# EVERY tool call (not just TodoWrite), so this value is also the real
# detection resolution for the hard threshold: a quota spike is noticed
# at most this many seconds late. 30s is a reasonable balance.
CACHE_TTL = int(os.environ.get("CC_USAGE_CACHE_TTL", "30"))
API_URL = "https://api.anthropic.com/api/oauth/usage"
API_TIMEOUT = float(os.environ.get("CC_USAGE_TIMEOUT", "8"))


def _read_token():
    try:
        with open(CREDENTIALS_FILE, "r") as f:
            creds = json.load(f)
    except FileNotFoundError:
        # Unverified on a real macOS install: Claude Code may store the
        # OAuth token in the system Keychain instead of writing this file
        # at all, in which case this tool has nothing to read and silently
        # fails open (zero quota protection, no error shown to the user
        # anywhere except this CLI). Only the CLI path (usage.py run
        # directly) ever surfaces this message; quota_gate.py's caller
        # still just catches the exception and fails open as always.
        raise RuntimeError(
            f"credentials file not found: {CREDENTIALS_FILE} "
            "(on macOS, Claude Code may store the OAuth token in the system "
            "Keychain instead of this file, which this tool doesn't read — "
            "see the README's Requirements section)"
        )
    tok = (creds.get("claudeAiOauth") or {}).get("accessToken")
    if not tok:
        raise RuntimeError("accessToken not found (you may be using the macOS keychain instead)")
    return tok


def fetch_raw():
    """Returns the raw API JSON response. Raises on any error."""
    token = _read_token()
    req = urllib.request.Request(
        API_URL,
        headers={
            "Authorization": "Bearer " + token,
            "anthropic-beta": "oauth-2025-04-20",
            "Content-Type": "application/json",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=API_TIMEOUT) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body)


def _normalize(raw):
    """Reduces the raw API response to a stable schema."""

    def block(node):
        if not isinstance(node, dict):
            return None
        util = node.get("utilization")
        if util is None:
            # some responses use used_percentage instead
            util = node.get("used_percentage")
        if util is None:
            return None
        try:
            util = float(util)
        except (TypeError, ValueError):
            return None
        return {"pct": util, "resets_at": node.get("resets_at")}

    return {
        "session": block(raw.get("five_hour")),
        "week_all": block(raw.get("seven_day")),
        "week_sonnet": block(raw.get("seven_day_sonnet")),
        "fetched_at": int(time.time()),
    }


def _read_cache():
    try:
        with open(CACHE_FILE, "r") as f:
            c = json.load(f)
        if int(time.time()) - int(c.get("fetched_at", 0)) <= CACHE_TTL:
            return c
    except Exception:
        pass
    return None


def _write_cache(data):
    try:
        tmp = CACHE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, CACHE_FILE)
    except Exception:
        pass  # failing to write the cache is not critical


def get_usage(use_cache=True):
    """
    Returns normalized usage data.
    Raises on failure (the caller must fail-open).
    """
    if use_cache:
        c = _read_cache()
        if c is not None:
            return c
    raw = fetch_raw()
    data = _normalize(raw)
    if data["session"] is None and data["week_all"] is None:
        raise RuntimeError("API response is missing the expected fields (schema may have changed; try --probe)")
    _write_cache(data)
    return data


# --------------------------------------------------------------------------- CLI
def _cli():
    args = set(sys.argv[1:])
    if "--probe" in args:
        try:
            print(json.dumps(fetch_raw(), indent=2, ensure_ascii=False))
        except Exception as e:
            print("PROBE ERROR:", e, file=sys.stderr)
            sys.exit(1)
        return
    try:
        u = get_usage(use_cache="--no-cache" not in args)
    except Exception as e:
        print("ERROR:", e, file=sys.stderr)
        sys.exit(1)
    if "--json" in args:
        print(json.dumps(u, indent=2, ensure_ascii=False))
        return
    for key, label in (("session", "5-hour session"), ("week_all", "Weekly (all)"), ("week_sonnet", "Weekly (Sonnet)")):
        b = u.get(key)
        if b:
            print(f"{label:>18}: {b['pct']:.1f}%   resets: {b.get('resets_at')}")
        else:
            print(f"{label:>18}: (no data)")


if __name__ == "__main__":
    _cli()
