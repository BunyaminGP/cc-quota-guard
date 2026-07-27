#!/usr/bin/env python3
"""
quota_gate.py — Claude Code PostToolUse hook. Registered on two matchers:

  - "TodoWrite": records the todo list to `.cc-quota/todos_state.json`
    (which item is in_progress, and which git commit it started from) and
    checks the SOFT threshold (finish the current item, then stop cleanly).
  - "*" (every tool): checks the HARD thresholds on EVERY call. A todo
    item's own work (many Edit/Bash/Write calls) can span a long stretch of
    time after a single TodoWrite call — if we only checked at TodoWrite
    time, a quota spike in between would be caught far too late.

What happens at the hard threshold depends on `hard_abort_enabled`
(default: **false**):
  - disabled (default): Claude is told to stop as safely as possible
    (commit if you can, don't start anything new) — same spirit as the
    soft stop, just triggered mid-item instead of at a boundary. No files
    are touched automatically.
  - enabled (opt-in via CC_HARD_ABORT=1, or the plugin's own userConfig
    screen): if a todo item is in_progress, ALL changes made on that item
    are reverted with `git stash`, the item is marked 'pending' again, and
    it gets redone from scratch after the quota resets.

Why is auto-revert opt-in? This hook is meant to be installed by people
who didn't write it. Automatically running `git stash` on someone's
working tree is a reasonable thing to opt into, not a reasonable default
for a stranger who just ran `/plugin install`. Read the README before
turning it on.

hard_abort_enabled can ONLY be turned on by something the user themselves
controls (an env var they set, or the plugin's configure screen) — never by
`.cc-quota/config.json`, because that file lives inside the project and can
arrive already committed in a repo someone else wrote or you just cloned.
The percentage thresholds ARE safe to read from config.json: they only
change *when* you stop, never *whether* a destructive-ish action happens.

FAIL-OPEN: if usage can't be read (API down, no token, schema changed),
Claude is NEVER blocked. Likewise, if git is unavailable or fails, revert
is skipped but Claude is still told to stop cleanly.

The hard-abort revert assumes the working tree is clean whenever a todo
item starts — i.e. every item ends with a commit. If the previous item
wasn't committed before the next one started, `git stash` will also sweep
up that earlier uncommitted work. This is a known limitation (see
README).

Config precedence for the percentage thresholds (highest wins): CC_* env
vars > .cc-quota/config.json > plugin userConfig > built-in defaults.
hard_abort_enabled uses the same order MINUS .cc-quota/config.json, which
is deliberately never consulted for it (see above). See _load_config().
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import usage  # noqa: E402
except Exception:
    usage = None


# --------------------------------------------------------------------------- helpers

def _project_dir(hook_input):
    return (
        os.environ.get("CLAUDE_PROJECT_DIR")
        or hook_input.get("cwd")
        or os.getcwd()
    )


def _quota_dir(proj):
    return os.path.join(proj, ".cc-quota")


def _marker_path(proj):
    return os.path.join(_quota_dir(proj), "STOP.json")


def _todos_state_path(proj):
    return os.path.join(_quota_dir(proj), "todos_state.json")


def _truthy(v):
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _load_config(proj):
    """
    Precedence, lowest to highest (each step overrides the previous one):
      1. built-in fallback defaults
      2. plugin userConfig — the values the user picked in the install/
         configure screen (CLAUDE_PLUGIN_OPTION_* env vars, set by Claude
         Code itself when this hook runs as part of the plugin)
      3. .cc-quota/config.json — per-project override
      4. CC_* environment variables — an explicit, one-off override (e.g.
         cc-run flags the user actually passed, or a manual `export`)
    """
    cfg = {
        "session_soft": 80.0,
        "session_hard": 95.0,
        "weekly_hard": 98.0,
        "hard_abort_enabled": False,
    }

    plugin_option_map = {
        "CLAUDE_PLUGIN_OPTION_SESSION_SOFT": "session_soft",
        "CLAUDE_PLUGIN_OPTION_SESSION_HARD": "session_hard",
        "CLAUDE_PLUGIN_OPTION_WEEKLY_HARD": "weekly_hard",
    }
    for env, key in plugin_option_map.items():
        v = os.environ.get(env)
        if v not in (None, ""):
            try:
                cfg[key] = float(v)
            except ValueError:
                pass
    if os.environ.get("CLAUDE_PLUGIN_OPTION_HARD_ABORT_ENABLED") not in (None, ""):
        cfg["hard_abort_enabled"] = _truthy(os.environ["CLAUDE_PLUGIN_OPTION_HARD_ABORT_ENABLED"])

    # NOTE: hard_abort_enabled is deliberately NOT read from config.json.
    # That file lives inside the project and can arrive already committed
    # in a repo you clone — it must never be able to silently turn on
    # automatic `git stash` on your behalf. Only a value YOU set yourself
    # (CC_HARD_ABORT env var, or the plugin's own userConfig screen) can do
    # that. Only the percentage thresholds are safe to let a project tune,
    # since they change *when* you stop, never *whether* something
    # destructive-ish happens.
    cfg_path = os.path.join(_quota_dir(proj), "config.json")
    try:
        with open(cfg_path) as f:
            fc = json.load(f)
        for k in ("session_soft", "session_hard", "weekly_hard"):
            if k in fc:
                cfg[k] = float(fc[k])
    except Exception:
        pass

    env_map = {
        "CC_SESSION_SOFT": "session_soft",
        "CC_SESSION_HARD": "session_hard",
        "CC_WEEKLY_HARD": "weekly_hard",
    }
    for env, key in env_map.items():
        if os.environ.get(env):
            cfg[key] = float(os.environ[env])
    if os.environ.get("CC_HARD_ABORT"):
        cfg["hard_abort_enabled"] = _truthy(os.environ["CC_HARD_ABORT"])
    return cfg


def _allow():
    sys.exit(0)


def _block(reason, user_msg):
    out = {
        "decision": "block",
        "reason": reason,
        "systemMessage": user_msg,
        "continue": True,
    }
    print(json.dumps(out))
    sys.exit(0)


def _git(proj, *args):
    try:
        r = subprocess.run(
            ["git", "-C", proj, *args], capture_output=True, text=True, timeout=15
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return 1, "", str(e)


def _is_git_repo(proj):
    code, out, _ = _git(proj, "rev-parse", "--is-inside-work-tree")
    return code == 0 and out == "true"


def _read_todos_state(proj):
    try:
        with open(_todos_state_path(proj)) as f:
            return json.load(f)
    except Exception:
        return None


def _write_todos_state(proj, state):
    os.makedirs(_quota_dir(proj), exist_ok=True)
    tmp = _todos_state_path(proj) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, _todos_state_path(proj))


def _save_todos_state(proj, todos, is_git):
    """On a TodoWrite call, records the todo list; if a new item just became
    in_progress, notes the checkpoint commit (if any)."""
    prev = _read_todos_state(proj)
    prev_in_progress = (prev or {}).get("in_progress")
    in_progress_todo = next((t for t in todos if t.get("status") == "in_progress"), None)

    state = {"todos": todos, "updated_at": int(time.time())}
    if in_progress_todo is None:
        state["in_progress"] = None
    elif prev_in_progress and prev_in_progress.get("content") == in_progress_todo.get("content"):
        state["in_progress"] = prev_in_progress  # same item still running, keep checkpoint
    else:
        checkpoint = None
        if is_git:
            code, out, _ = _git(proj, "rev-parse", "HEAD")
            checkpoint = out if code == 0 else None
        state["in_progress"] = {
            "content": in_progress_todo.get("content"),
            "checkpoint_commit": checkpoint,
            "started_at": int(time.time()),
        }
    _write_todos_state(proj, state)
    return state


def _append_progress_note(proj, text):
    path = os.path.join(_quota_dir(proj), "progress.md")
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n" + text + "\n")
    except Exception:
        pass


def _write_marker(proj, data):
    os.makedirs(_quota_dir(proj), exist_ok=True)
    with open(_marker_path(proj), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _marker_still_valid(proj):
    """A STOP.json marker only short-circuits the checks below while we're
    still inside the quota window it declared (cc-run is asleep, waiting
    for `resets_at`). A marker whose `resets_at` has already passed — or
    that's missing/malformed — is stale: either cc-run resumed without
    cleaning it up, or the file shipped with the project (e.g. committed by
    someone else, or by an untrusted repo) rather than being written by
    this hook just now. A stale/foreign marker must NOT be trusted to
    silently and permanently disable the guard, so we treat it as absent.
    """
    try:
        with open(_marker_path(proj)) as f:
            data = json.load(f)
        resets_at = data.get("resets_at")
        if not resets_at:
            return False
        s = str(resets_at).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt > datetime.now(timezone.utc)
    except Exception:
        return False


# --------------------------------------------------------------------------- hard threshold

def _do_hard_stop(proj, which, pct, resets_at, thr, state, is_git, hard_abort_enabled):
    in_progress = (state or {}).get("in_progress")
    aborted_item = in_progress.get("content") if in_progress else None
    stash_created = False
    did_revert = False

    if hard_abort_enabled and in_progress and is_git:
        did_revert = True
        stamp = int(time.time())
        code, out, _err = _git(
            proj, "stash", "push", "-u", "-m",
            f"cc-quota-guard: abort '{aborted_item[:60]}' @ {stamp}",
        )
        stash_created = code == 0 and "No local changes to save" not in out

        todos = state.get("todos", [])
        for t in todos:
            if t.get("content") == aborted_item:
                t["status"] = "pending"
        _write_todos_state(proj, {"todos": todos, "in_progress": None, "updated_at": stamp})

        _append_progress_note(
            proj,
            "## ⛔ HARD quota threshold — item reverted\n"
            f"- Time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"- Reverted item: {aborted_item}\n"
            "- Method: git stash"
            + (" (stash created, recoverable with `git stash list`)"
               if stash_created else " (working tree was already clean, no stash created)")
            + "\n"
            f"- Checkpoint commit: {in_progress.get('checkpoint_commit') or 'unknown'}\n"
            "- After the reset, this item must be redone FROM SCRATCH.\n",
        )
    elif in_progress and not hard_abort_enabled:
        _append_progress_note(
            proj,
            "## ⚠️ HARD quota threshold — auto-revert is disabled\n"
            f"- Item in progress: {aborted_item}\n"
            "- `hard_abort_enabled` is off (this is the default), so nothing was reverted "
            "automatically. Leave this item in the safest state you can, commit if possible, "
            "and stop.\n",
        )
    elif in_progress and not is_git:
        _append_progress_note(
            proj,
            "## ⚠️ HARD quota threshold — no git, could not revert\n"
            f"- Item: {aborted_item}\n"
            "- This project is not a git repository; automatic revert was skipped. "
            "Leave the item in a safe state and note it manually.\n",
        )

    _write_marker(proj, {
        "mode": "hard",
        "window": which,
        "pct": pct,
        "resets_at": resets_at,
        "threshold": thr,
        "stopped_at": int(time.time()),
        "aborted_item": aborted_item if did_revert else None,
        "stash_created": stash_created,
        "git_available": is_git,
        "hard_abort_enabled": hard_abort_enabled,
    })

    label = "5-hour session" if which == "session" else "weekly"
    if did_revert:
        reason = (
            f"[HARD QUOTA THRESHOLD] {label} usage reached {pct:.0f}% (threshold {thr:.0f}%). "
            f"ALL changes made on '{aborted_item}' were REVERTED with `git stash` "
            "(the working tree is back to the commit from before this item started). NOW:\n"
            "1) Do NOT run any more edit/write/bash commands.\n"
            "2) Do NOT commit — the revert already happened, there is nothing to commit.\n"
            "3) Mark this item as 'pending' with TodoWrite "
            "(already recorded as pending in `.cc-quota/todos_state.json`).\n"
            f"4) Give a short note: '{aborted_item}' was reverted due to quota, will be redone from scratch after reset.\n"
            "5) END THE TURN — don't call any more tools.\n"
            f"Quota reset time: {resets_at}."
        )
    else:
        reason = (
            f"[HARD QUOTA THRESHOLD] {label} usage reached {pct:.0f}% (threshold {thr:.0f}%) — "
            "automatic revert was not performed (auto-revert is disabled, git is unavailable, or no item "
            "is in progress). Leave the current work in the safest possible state, commit if you can, "
            "give a short note, and END THE TURN. Don't start anything new.\n"
            f"Quota reset time: {resets_at}."
        )
    user_msg = (
        f"⛔ HARD quota threshold ({label} {pct:.0f}%) — "
        f"{'item reverted' if did_revert else 'clean stop'}. Reset: {resets_at}"
    )
    _block(reason, user_msg)


# --------------------------------------------------------------------------- soft threshold

def _do_soft_stop(proj, which, pct, resets_at, thr):
    _write_marker(proj, {
        "mode": "soft",
        "window": which,
        "pct": pct,
        "resets_at": resets_at,
        "threshold": thr,
        "stopped_at": int(time.time()),
        "aborted_item": None,
        "stash_created": False,
    })

    label = "5-hour session" if which == "session" else "weekly"
    reason = (
        f"[QUOTA THRESHOLD] {label} usage reached {pct:.0f}% (threshold {thr:.0f}%). "
        "Do NOT start a new todo item. Instead, wrap up cleanly IN THIS ORDER:\n"
        "1) Update `.cc-quota/progress.md`: which items are done, what's next, what context/notes "
        "are needed to resume (read the file first, create it if missing).\n"
        "2) Don't leave any edit half-finished; leave the current item at a safe point.\n"
        "3) Commit your changes with a meaningful message (if this is a git repo).\n"
        "4) Give a short summary and END THE TURN — don't call any more tools.\n"
        f"Quota reset time: {resets_at}. After the reset, work resumes by reading `.cc-quota/progress.md`."
    )
    user_msg = f"⛔ Quota threshold reached ({label} {pct:.0f}%) — Claude is wrapping up cleanly. Reset: {resets_at}"
    _block(reason, user_msg)


# --------------------------------------------------------------------------- main

def main():
    raw_in = sys.stdin.read()
    try:
        hook_input = json.loads(raw_in) if raw_in.strip() else {}
    except Exception:
        hook_input = {}

    proj = _project_dir(hook_input)
    cfg = _load_config(proj)

    # Already stopped and still within that stop's quota window — don't
    # block repeatedly and create a loop while cc-run is asleep waiting for
    # the reset. A marker that's stale (past its resets_at) or foreign
    # (shipped with the project instead of written by this run) is ignored
    # and removed instead of trusted — see _marker_still_valid().
    if os.path.exists(_marker_path(proj)):
        if _marker_still_valid(proj):
            _allow()
        try:
            os.remove(_marker_path(proj))
        except Exception:
            pass

    tool_name = hook_input.get("tool_name") or hook_input.get("tool") or ""
    tool_input = hook_input.get("tool_input") or {}
    is_git = _is_git_repo(proj)

    state = _read_todos_state(proj)
    if tool_name == "TodoWrite":
        todos = tool_input.get("todos") or []
        if todos:
            state = _save_todos_state(proj, todos, is_git)

    if usage is None:
        _allow()  # fail-open: module couldn't be imported
    try:
        u = usage.get_usage()
    except Exception:
        _allow()  # fail-open: couldn't read usage

    session = u.get("session") or {}
    week = u.get("week_all") or {}
    s_pct = session.get("pct")
    w_pct = week.get("pct")

    # HARD threshold — checked on every call, takes priority over soft.
    if s_pct is not None and s_pct >= cfg["session_hard"]:
        _do_hard_stop(proj, "session", s_pct, session.get("resets_at"), cfg["session_hard"],
                      state, is_git, cfg["hard_abort_enabled"])
    if w_pct is not None and w_pct >= cfg["weekly_hard"]:
        _do_hard_stop(proj, "week_all", w_pct, week.get("resets_at"), cfg["weekly_hard"],
                      state, is_git, cfg["hard_abort_enabled"])

    # SOFT threshold — only checked at item boundaries (TodoWrite calls).
    if tool_name == "TodoWrite" and s_pct is not None and s_pct >= cfg["session_soft"]:
        _do_soft_stop(proj, "session", s_pct, session.get("resets_at"), cfg["session_soft"])

    _allow()


if __name__ == "__main__":
    main()
