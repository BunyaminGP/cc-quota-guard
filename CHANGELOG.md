# Changelog

All notable changes to cc-quota-guard are documented here. Versions match
`.claude-plugin/plugin.json` and the `cc-quota-guard--vX.Y.Z` git tags.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- **Push notifications** (`scripts/notify.py`): optional webhook POST at
  the moments that matter — a SOFT/HARD threshold stopping Claude,
  `cc-run` resuming, the task finishing, or `cc-run` giving up after
  retries. Set `CC_NOTIFY_URL` (env var or the plugin's `notify_url`
  configure-screen field) to a webhook URL; tested end-to-end against a
  real ntfy.sh topic and phone (both the raw `notify.py` CLI and the full
  `cc-run` wrapper flow). Reuses the already-localized, already-privacy-
  safe status text shown to the human (systemMessage / cc-run's own
  terminal lines) as the notification body — no new message drafting, no
  task content or file paths ever sent. Fails open on everything (no URL,
  bad URL, no network, timeout — `CC_NOTIFY_TIMEOUT`, default 5s) and can
  never break a hook call or a `cc-run` round.
  Deliberately scoped to a plain-text POST body (what ntfy.sh expects) —
  does NOT attempt Slack's or Discord's JSON webhook shape
  (`{"text": ...}` / `{"content": ...}`), since that was never tested;
  documented as a known limitation rather than an implied feature.
  `notify_url` follows the same restricted precedence as
  `hard_abort_enabled`: readable only from `CC_NOTIFY_URL` or the plugin's
  own configure screen, **never** from `.cc-quota/config.json` — a notify
  URL is an exfiltration channel (session status sent to whoever controls
  it), not a cosmetic setting, so a cloned/untrusted project must not be
  able to silently set it. New `tests/test_notify.py` (real local HTTP
  server capturing an actual POST, fail-open cases, URL-resolution
  precedence, and a behavioral regression guard that no code path in the
  module ever opens a `config.json`); new tests in `test_quota_gate.py`
  and a new `test_cc_run.sh` scenario.

## [0.9.0] — 2026-07-28

### Added
- **Weekly SOFT threshold** (`weekly_soft`, default 97%), symmetric with
  the existing session SOFT threshold: at this usage %, Claude finishes
  the current todo item then stops cleanly, checked at the same
  TodoWrite/Task* item boundaries as session SOFT — session and weekly are
  independent tiers, either can fire on its own. Wired through the full
  precedence chain like every other threshold: `CC_WEEKLY_SOFT` env var,
  `.cc-quota/config.json`'s `weekly_soft` key, the plugin's configure
  screen, `cc-run --weekly-soft N`. Replaces an earlier idea of checking
  the API's separate `seven_day_sonnet` usage field (fetched by
  `usage.py` but never actually consulted) — decided a weekly SOFT
  warning was the more useful fix, and simpler to reason about than a
  third, per-model threshold.

### Changed
- `quota_gate.py`'s `main()` no longer computes `is_git` (a `git
  rev-parse` subprocess spawn) unconditionally on every single tool call.
  Most tool calls (a plain Edit/Bash/Read, not a planning call, nowhere
  near a HARD threshold) never actually needed the answer — only the
  TodoWrite/Task* state-tracking branch and the HARD-threshold checks do.
  Now a memoized `is_git()` closure, computed lazily on first actual use
  per hook invocation (still only ever spawns git once per call, same as
  before, just skips the spawn entirely on the calls that never needed
  it). No behavior change.

### Fixed
- `quota_gate.py`'s `_do_hard_stop` crashed with `TypeError` on
  `aborted_item[:60]` when an in-progress item's `content` was `None`
  (reachable via a `TaskCreate` call whose `tool_response`/`tool_input`
  both omitted `subject`) — the one code path this project's fail-open
  design can least afford to break, since it's the one that runs `git
  stash` on the user's working tree. `_save_task_tool_state`'s `TaskCreate`
  branch now falls back to a placeholder subject (matching the
  pre-existing fallback in its `TaskUpdate` branch), and `_do_hard_stop`
  itself now defends against a `None`/missing content defensively too.
- `scripts/usage.py`'s `_read_token()` raised a bare `FileNotFoundError`
  with no explanation when `~/.claude/.credentials.json` doesn't exist at
  all — the likely case on a real macOS install if Claude Code stores the
  OAuth token in the system Keychain instead (unverified; this project has
  no Mac to test against). Now raises a `RuntimeError` that says so, so
  `python3 scripts/usage.py` gives an actionable hint instead of a bare
  traceback. Documented as an open, unverified gap in both READMEs.
- `scripts/stream_render.py` rendered a failed round's `result` event
  identically to a successful one — `claude` can exit 0 even when a round
  didn't actually finish the task (e.g. `subtype: "error_max_turns"`), and
  since `cc-run`'s retry logic only looks at the process exit code, it
  can't tell the difference either; it just logs "ended on its own" and
  quietly stops the whole unattended run. Now prints a visible warning
  when the result event's `is_error` is true or `subtype` isn't
  `"success"`. Covered by a new fake-`claude` scenario in
  `tests/test_cc_run.sh`.

## [0.8.3] — 2026-07-28

### Fixed
- The 0.8.2 macOS fix was incomplete: the RULES prompt block was still
  built as a cat-heredoc wrapped in command substitution, and bash 3.2's
  naive scanner — which doesn't understand heredocs — treated the lone
  apostrophe in the heredoc's prose ("you'll") as an opened quote and
  never found the closing paren, so `bash -n` still exited 2 on macOS.
  Now read via a top-level heredoc (`IFS= read -r -d '' RULES <<EOF`),
  where any prose is safe no matter what future edits add to it.

### Added
- `tests/check_bash32_compat.py`: static guard that scans every shell
  script for the two bash-3.2 poison patterns (odd apostrophe count
  inside a `$()` span, heredoc inside `$()`), wired into the CI syntax
  step — so the next regression is caught on all lanes with a message
  naming the exact line, instead of a bare `bash -n` exit 2 from the
  macOS lane only.

## [0.8.2] — 2026-07-28

**Note:** still broken on macOS — the fix below removed two of the three
bash-3.2-incompatible constructs but missed one; completed in 0.8.3.

### Fixed
- `bin/cc-run` didn't parse on macOS's stock `/bin/bash` (3.2, what
  `#!/usr/bin/env bash` resolves to on a default Mac): two constructs —
  an inline `$( if ... )` with apostrophes inside double-quoted text,
  embedded in the RULES heredoc, and a nested `$(to_py_path ...)` inside a
  double-quoted string inside `$()` — tripped bash 3.2's naive
  command-substitution matcher (it counts characters instead of using the
  real parser; fixed upstream only in bash 4.0), rejecting the whole
  script as a syntax error before running a single line. Both restructured
  into plain variable assignments. Caught by the first-ever macOS CI run
  (`bash -n` exiting 2), which the Ubuntu/Windows lanes passed.

### Added
- README badges (CI, license, changelog).

## [0.8.1] — 2026-07-28

### Added
- N-language message catalog: `locales/<code>.json` (one file per
  language, `en`/`tr` shipped) + `scripts/i18n.py` (shared lookup used by
  both `cc-run` and the hook). Adding a language is copying `locales/en.json`
  and translating it — no code changes anywhere. Falls back to English at
  every level: unknown language, a locale file missing a key, even a
  broken/missing locale file entirely.
- Language setting (`CC_LANG` env var, `.cc-quota/config.json`'s
  `"language"` key, or the plugin's configure screen) for `cc-run`'s
  terminal output and the hook's `systemMessage`. Claude itself is always
  instructed in English regardless of this setting — it only changes what
  the human running the tool sees.
- `tests/` (pytest for the Python side, `tests/test_cc_run.sh` for
  `cc-run`'s retry/backoff/timeout/language behavior against a fake
  `claude`) and a GitHub Actions CI workflow
  (`.github/workflows/ci.yml`, matrix: Ubuntu/macOS/Windows) running both
  plus a syntax/compile check on every push and PR.

### Fixed
- `install.sh` (manual, non-plugin install) wasn't copying
  `locales/*.json` or `scripts/i18n.py` — language support would have
  silently done nothing on that install path. Also fixed a pre-existing
  gap where it never copied `scripts/stream_render.py` either.
- `quota_gate.py`'s internal `_git()` helper now retries a couple of times
  on a transient `OSError` before giving up (found while building the test
  suite: on some Windows/Python combinations, spawning many subprocesses
  in a short window can intermittently fail this way). Worth hardening
  specifically because `_is_git_tracked` — the check that stops a planted,
  git-tracked `todos_state.json` from triggering an unwanted hard-abort
  revert — would otherwise read a transient failure as "not tracked" and
  wrongly trust it, purely from bad luck rather than the file genuinely
  being untracked.

## [0.6.0] — 2026-07-27

### Added
- `cc-run` retry/backoff resilience: a round (initial or resume) that
  fails outright, or makes zero progress for longer than
  `CC_ROUND_TIMEOUT` (default 1h), is now retried with linear backoff up
  to `CC_MAX_RETRIES` times (default 5) instead of the wrapper silently
  giving up or hanging indefinitely. Closes a real gap where a transient
  network outage at the exact moment a session woke up to resume could
  leave it stuck for hours with no recovery.

### Fixed
- `scripts/stream_render.py` only ever reconfigured `stdout` to UTF-8,
  never `stdin` — on Windows this was the actual root cause of persistent
  mojibake (surviving even the 0.4.1 console-encoding fix, since that only
  addressed the *outgoing* side) and of a `UnicodeEncodeError` crash on a
  stray character. Both ends are now reconfigured, and `stdout` degrades
  with `errors="replace"` instead of crashing on anything still invalid.

## [0.5.0] — 2026-07-27

### Fixed
- The SOFT threshold (and hard-abort's in-progress tracking) only ever
  recognized `TodoWrite` calls. Some Claude Code versions plan with
  `TaskCreate`/`TaskUpdate`/`TaskList` instead — on those, the SOFT
  threshold was silently dead no matter how high usage got, since the one
  call it watched for never happened. Both tool families are now
  supported and tracked into the same on-disk state.

## [0.4.1] — 2026-07-27

### Fixed
- Mojibake in the `cc-run` PowerShell wrapper (`shell/cc-run.ps1`):
  forces the console to UTF-8 for the duration of the call, then restores
  it, since PowerShell defaults to the system codepage when decoding a
  child process's stdout.

## [0.4.0] — 2026-07-27

### Security
- `.cc-quota` is no longer trusted if it's a symlink or an existing
  non-directory — a cloned/untrusted repo could otherwise redirect the
  hook's writes outside the project.
- A `todos_state.json` that is itself tracked by git (a sign it shipped
  with the repo rather than being written locally, since the README tells
  users to `.gitignore` it) is no longer trusted to claim an `in_progress`
  item for hard-abort revert purposes — closes a path where a planted
  file could trigger an unwanted `git stash` on unrelated uncommitted work.
- Percentage thresholds from any source are now clamped to `(0, 100]` —
  closes both a crash-on-malformed-env-var bug and a way for a cloned
  repo's `config.json` to neuter the guard (an absurdly high threshold) or
  grief it into blocking every tool call (zero or negative).

### Changed
- Consolidated the `TodoWrite` + `*` `PostToolUse` hook matchers into a
  single `*` (the script already dispatched internally by tool name) —
  removes a redundant double-invocation of the hook on every `TodoWrite`
  call.

## [0.3.1] — 2026-07-27

### Fixed
- A previous, unrelated run's finished `progress.md` (containing
  `CC_QUOTA_DONE`) left in the same project folder would make a brand-new
  `cc-run` task falsely report success after its very first round, before
  Claude had done anything for the new task. Now archived before a fresh
  run starts.

## [0.3.0] — 2026-07-27

### Added
- `cc-run` output now goes through `scripts/stream_render.py`
  (`--output-format stream-json`), showing the *resolved* model actually
  running (aliases like `sonnet` resolve to a specific dated model), which
  tools are being called, and a per-round cost/model-usage summary — same
  underlying request, just parsed instead of printed raw.

### Fixed
- A `UnicodeEncodeError` crash on Windows when printing emoji, since
  `stdout`'s encoding follows the system codepage by default.

## [0.2.2] — 2026-07-27

### Added
- `shell/cc-run.ps1` and `shell/cc-run.sh`: terminal integration so
  `cc-run` is callable as a bare command from the user's own shell (a
  plugin's `bin/` is normally only on `PATH` for Claude Code's own internal
  Bash tool calls, not the user's terminal).

## [0.2.1] — 2026-07-27

### Security
- A stale or planted `STOP.json` (expired, malformed, or shipped inside a
  cloned project) could otherwise be trusted as "already stopped, don't
  re-check" indefinitely — now only honored while its `resets_at` is still
  in the future, and cleaned up otherwise.
- `hard_abort_enabled` made explicitly opt-in, readable only from
  something the user themselves controls (`CC_HARD_ABORT` env var or the
  plugin's configure screen) — never from `.cc-quota/config.json`, which
  can arrive already committed in a cloned repo.

## [0.2.0] — 2026-07-27

### Added
- Plugin configuration screen (`userConfig` in `plugin.json`) for the
  session/weekly thresholds and hard-abort toggle.

## [0.1.0] — 2026-07-27

Initial release: `quota_gate.py` PostToolUse hook (SOFT/HARD threshold
detection via the undocumented OAuth usage endpoint) and the `cc-run`
wrapper (headless run, sleep-until-reset, auto-resume).
