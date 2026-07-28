#!/usr/bin/env python3
"""
usage.py — Claude Code usage (rate-limit) reader.

Source: Anthropic's UNDOCUMENTED OAuth usage endpoint:
    GET https://api.anthropic.com/api/oauth/usage
    headers: Authorization: Bearer <token>, anthropic-beta: oauth-2025-04-20

Token, checked in this order (see _read_token()):
  1. CLAUDE_CODE_OAUTH_TOKEN env var (matches Claude Code's own precedence
     — used for `claude setup-token` long-lived tokens and SSH/headless
     setups; works identically on every platform).
  2. ~/.claude/.credentials.json -> .claudeAiOauth.accessToken (primary
     storage on Linux/Windows; confirmed via Claude Code's own docs).
  3. macOS only, when #2's file doesn't exist: the system Keychain,
     service name "Claude Code-credentials" (confirmed via Claude Code's
     docs and community bug reports — macOS's primary storage is the
     Keychain, not the file, and at least one reported Claude Code
     version actively deletes the file once Keychain is in use). Read via
     the `security` CLI (built into every Mac, no new dependency) —
     **implemented from documented behavior, not yet verified against a
     real macOS install**, since this project has no Mac to test with;
     see README's Honest warnings section.

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
import subprocess
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


KEYCHAIN_SERVICE = "Claude Code-credentials"


def _read_token_from_keychain():
    """
    macOS only: reads the OAuth credentials JSON out of the system
    Keychain via the `security` CLI (built into every Mac — no new
    dependency, same approach as quota_gate.py already shelling out to
    `git`). Raises on any failure, same contract as _read_token() itself,
    so the caller's existing fail-open handling covers this path too.

    Implemented from Claude Code's own documented behavior and community
    bug reports (the service name "Claude Code-credentials" is confirmed
    from both), NOT yet verified against a real macOS install — this
    project has no Mac to test with. If this is wrong for your installed
    Claude Code version, `python3 usage.py --probe` will show exactly
    where it fails; please open an issue with that output.
    """
    result = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "macOS Keychain lookup failed for service "
            f"'{KEYCHAIN_SERVICE}': {(result.stderr or '').strip() or 'unknown error'}"
        )
    creds = json.loads(result.stdout)
    tok = (creds.get("claudeAiOauth") or {}).get("accessToken")
    if not tok:
        raise RuntimeError("accessToken not found in macOS Keychain entry")
    return tok


def _read_token():
    # 1) CLAUDE_CODE_OAUTH_TOKEN env var — matches Claude Code's own
    # precedence (used for `claude setup-token` long-lived tokens and
    # SSH/headless setups), works identically on every platform, no
    # file/Keychain access needed at all.
    env_tok = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    if env_tok:
        return env_tok

    # 2) The credentials file — primary storage on Linux/Windows, and
    # still checked first on macOS too (some setups sync Keychain to this
    # file, e.g. for SSH access — see README).
    try:
        with open(CREDENTIALS_FILE, "r") as f:
            creds = json.load(f)
    except FileNotFoundError:
        # 3) macOS Keychain fallback — see _read_token_from_keychain()'s
        # docstring for what's confirmed vs. unverified here.
        if sys.platform == "darwin":
            return _read_token_from_keychain()
        raise RuntimeError(f"credentials file not found: {CREDENTIALS_FILE}")

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
