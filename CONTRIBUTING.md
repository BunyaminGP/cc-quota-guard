# Contributing to cc-quota-guard

Issues and PRs are welcome. This file covers how to get set up, how to run
the test suite, and the design principles a PR touching the
quota-detection or revert logic is expected to follow.

## Setup

No install step beyond the standard library — `scripts/*.py` only use
Python's stdlib (no `pip install` needed). You'll need:

- Python 3.8+
- `bash` (Git Bash on Windows)
- `git` (for the hard-abort revert tests)
- `pytest` (`python -m pip install pytest`)

## Running the tests before opening a PR

```bash
pytest                              # Python unit tests (scripts/*.py)
bash tests/test_cc_run.sh           # bin/cc-run black-box tests (fake `claude`)
python tests/check_bash32_compat.py bin/cc-run install.sh tests/test_cc_run.sh shell/cc-run.sh
```

The third command is a static check specific to this project: **cc-run
must stay parseable by macOS's stock `/bin/bash` (3.2)**, which parses
`$(...)` command substitution by naive character-counting rather than a
real shell parser. A stray apostrophe in prose inside a `$()` span, or a
heredoc nested inside one, silently breaks the *entire* script on macOS —
this bit the project for real (see CHANGELOG's 0.8.2/0.8.3 entries) before
the checker existed. If you edit `bin/cc-run`, `install.sh`, or the shell
tests, run this before pushing.

All three run in CI (`.github/workflows/ci.yml`) on Ubuntu, macOS, and
Windows for every push and PR — you don't strictly have to run them
locally first, but a red CI run is slower feedback than a local one.

## Design principles

If your change touches the quota-detection, hard-abort revert, or
credential-reading logic, keep to the style the rest of the project
already follows:

- **Fail open.** If usage can't be read, git is unavailable, or a
  notification fails to send — never block Claude, never crash the hook.
  An exception in the wrong place here is worse than the feature not
  working at all.
- **Opt in to anything destructive or security-relevant.** Auto-revert
  (`git stash`) and notification URLs are only ever readable from
  something the user themselves controls (an env var they set, or the
  plugin's own configure screen) — **never** from `.cc-quota/config.json`,
  since that file can arrive already committed in a cloned/untrusted
  repo. See `quota_gate.py`'s module docstring and `_load_config()` for
  the reasoning; keep any new security-relevant setting to the same rule.
- **Document the limitation instead of overclaiming.** If something is
  unverified (no real macOS/Linux hardware to test against, an untested
  third-party webhook shape, an assumption about Claude Code's internals),
  say so in the code comment and the README rather than presenting it as
  confirmed. Several real bugs in this project's history came from
  optimistic claims that turned out not to hold — see CHANGELOG.
- **Verify live when you can.** Where reasonably possible, changes in
  this project have been checked against a real subprocess run, a real
  git repo, or a real external service (not just reasoned about) before
  being considered done — the CHANGELOG entries describe what was
  actually verified and how. New tests should do the same wherever
  practical (e.g. `tests/test_notify.py` spins up a real local HTTP
  server rather than only mocking).

## Where things live

See `project-overview`-style comments at the top of `scripts/quota_gate.py`
and `bin/cc-run` for how the pieces fit together — both files have a
thorough module docstring explaining the architecture, not just the code.
`CHANGELOG.md` has the history of what changed and why, including several
security-hardening passes worth reading before touching the trust
boundaries (`.cc-quota` symlink guard, tracked-state distrust, threshold
clamping).

## Adding a language

See the README's [Language / Dil](README.md#language--dil) section —
adding a locale is dropping a `locales/<code>.json` file in, no code
changes required.

## License

By contributing, you agree your contribution is licensed under this
project's [MIT license](LICENSE).
