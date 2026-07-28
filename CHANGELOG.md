# Changelog

All notable changes to cc-quota-guard are documented here. Versions match
`.claude-plugin/plugin.json` and the `cc-quota-guard--vX.Y.Z` git tags.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased] — targeting 0.8.1

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
