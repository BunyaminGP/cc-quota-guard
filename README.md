# cc-quota-guard

Run Claude Code **quota-aware**: stop it at a clean checkpoint before you hit
your usage limit, save progress to disk, and **automatically resume once the
quota resets** — instead of getting cut off mid-task.

*[Türkçe için README.tr.md](README.tr.md)*

## The problem

Normally, the moment your Claude Code quota runs out, the session just stops
— wherever it happened to be, edits half-made, nothing recorded. This tool
stops *before* that, at a point you choose, and in a way you choose:

- **SOFT threshold** (default 80% of the 5-hour session): there's still
  headroom, so Claude finishes the current todo item, then wraps up cleanly
  (commit + write progress notes) before stopping.
- **HARD threshold** (default 95% session / 98% weekly): can fire mid-item,
  when there may not be enough headroom left to finish safely. **Off by
  default.** If you opt in, Claude's in-progress changes on that item are
  reverted with `git stash`, the item goes back to `pending`, and it gets
  redone from scratch after the reset. In an 8-item todo list, if item 6 hits
  the hard threshold halfway through: item 6's partial work is stashed away,
  the reset happens, item 6 is redone from scratch, then 7 and 8 proceed
  normally.

## Install

**Recommended — as a Claude Code plugin:**

```
/plugin marketplace add BunyaminGP/cc-quota-guard
/plugin install cc-quota-guard
```

That's it — no copying files by hand, no editing `settings.json`. The hooks
register automatically, and `cc-run` (see below) becomes available as a bare
command in any Bash tool call while the plugin is enabled.

Install at project scope instead of user scope if you want it shared with
your team via version control:

```
claude plugin install cc-quota-guard --scope project
```

**Fallback — manual install** (for Claude Code versions without the plugin
system):

```bash
git clone https://github.com/BunyaminGP/cc-quota-guard
cd cc-quota-guard
bash install.sh
```

This copies the tool into `~/.claude/cc-quota-guard/` and merges the
`PostToolUse` hooks into `~/.claude/settings.json` (idempotent — safe to
re-run, e.g. to pick up an update).

## Usage

Fully automatic (stop + auto-resume at reset):

```bash
cc-run "refactor the auth service in 3 steps: ..."
cc-run --threshold 80 --session-hard 95 --weekly-hard 98 @task.md
```

- `--threshold N` — session **SOFT** threshold (default 80). Finishes the
  current item, then stops.
- `--session-hard N` — session **HARD** threshold (default 95). Can fire
  mid-item.
- `--weekly-hard N` — weekly **HARD** threshold (default 98). Can fire
  mid-item.
- `--enable-hard-abort` — opt in to auto-reverting the in-progress item
  (`git stash`) when a HARD threshold fires. **Off unless you pass this.**
  Without it, HARD thresholds just force a clean stop, same as SOFT — nothing
  is touched automatically. Read [Safety](#safety-read-this-before-enabling-hard-abort)
  below before turning this on.
- Task: plain text or `@file.md` (the file's contents become the task).

Just "stop cleanly" (no wrapper, interactive session): since the hooks are
installed, a normal `claude` session also stops cleanly at the thresholds —
but it won't auto-resume; you run `claude -c` yourself after the reset. Set
thresholds for this mode with environment variables: `CC_SESSION_SOFT=80
CC_SESSION_HARD=95 CC_WEEKLY_HARD=98`, and `CC_HARD_ABORT=1` to opt into
auto-revert.

## How it works

1. **Hook** (`scripts/quota_gate.py`) — registered on two `PostToolUse`
   matchers:
   - `TodoWrite`: records which item is `in_progress` and which git commit
     it started from, into `.cc-quota/todos_state.json`; checks the SOFT
     threshold.
   - `*` (every tool): checks the HARD thresholds on **every** call. A
     single todo item's work (many Edit/Bash/Write calls) can run long after
     one `TodoWrite` call — checking only at `TodoWrite` time would notice a
     quota spike far too late.
2. **State files**
   - `.cc-quota/progress.md` — what's done, what's next, and (if hard-abort
     fired) which item was reverted. Read on resume.
   - `.cc-quota/todos_state.json` — the hook's own snapshot of the todo list.
3. **Wrapper** (`bin/cc-run`) — starts Claude, reads the reset time from
   `.cc-quota/STOP.json` when a threshold stops it, sleeps until then, and
   resumes with `claude -c`. Stops when `progress.md` contains `CC_QUOTA_DONE`.

Quota source: Anthropic's **undocumented** OAuth usage endpoint
(`/api/oauth/usage`) — gives session (5h) and weekly utilization percentages
plus reset times.

## Safety — read this before enabling hard-abort

`--enable-hard-abort` makes an automated hook run `git stash` on your
working tree without asking. That's a reasonable thing to opt into once you
understand it; it is **not** a reasonable default for a plugin a stranger
just installed. A few things to know before you turn it on:

- **It relies on "clean at item start."** `git stash` returns the working
  tree to the last commit. For that to be the *right* commit, every item
  must actually be committed before the next one starts (the tool already
  pushes you toward this). If the previous item wasn't committed, the stash
  sweeps that up too — not malicious, just a known limitation.
- **It's recoverable, not automatic-recoverable.** `git stash` doesn't
  delete anything — see `git stash list` / `git stash pop` — but nothing
  restores it for you. That's intentional: an automatic un-revert would be
  one more thing that could silently do the wrong thing.
- **No git, no revert.** If the project isn't a git repository, hard-abort
  silently falls back to a clean stop — same as if you hadn't enabled it.
- **Try it somewhere disposable first.** A scratch repo, before you trust it
  on real work.

## Requirements

- `bash`, `python3`
- Claude Code CLI (`claude`), Pro/Max subscription (the usage endpoint only
  works on those plans)
- A valid OAuth token in `~/.claude/.credentials.json` (created automatically
  when you log into Claude Code)
- git, only if you plan to use `--enable-hard-abort`

## Verify / debug

```bash
python3 scripts/usage.py          # percentages as read
python3 scripts/usage.py --probe  # RAW API response (field-name check)
```

(For a plugin install, replace `scripts/` with the plugin's install path —
run `python3 "$CLAUDE_PLUGIN_ROOT/scripts/usage.py"` from a hook, or find the
cache path with `claude plugin list`.)

If `--probe` doesn't show `.five_hour.utilization` / `.seven_day.utilization`,
Anthropic likely changed the schema — update the field names in
`_normalize()` in `scripts/usage.py`.

## Honest warnings

- **The API is unofficial.** `/api/oauth/usage` is undocumented; Anthropic
  can change or remove it without notice. The hook **fails open**: if it
  can't read usage, it never blocks Claude. If the API goes down, protection
  silently turns off.
- **Detection isn't instant.** The hook now fires on every tool call (not
  just `TodoWrite`), so the real detection lag is roughly
  `CC_USAGE_CACHE_TTL` (default 30s) — much tighter than "a whole todo item,"
  but a single very large tool call inside that window can still overshoot a
  threshold. Set thresholds a bit below 100%, not right at it.
- **The machine has to stay on.** The wrapper sleeps until the reset; if the
  computer sleeps or shuts down, it won't resume on its own.
- **Don't rely on context recall.** `claude -c` brings the conversation back
  but isn't a hard guarantee. The real memory is `progress.md` + git commits
  — put anything critical there.
- **`acceptEdits` warning.** By default the wrapper runs with
  `--permission-mode acceptEdits` (so it can keep editing headlessly across
  resumes without asking). If that's not acceptable, set `CC_CLAUDE_ARGS=""`
  and run interactively. Check `claude --help` for current flags — they can
  change.
- **Plan.** The usage endpoint works on Pro/Max. On a different plan,
  `--probe` may return nothing or something different.

## Settings (environment variables)

| Variable | Default | Description |
|---|---|---|
| `CC_SESSION_SOFT` | 80 | Session SOFT threshold (%) — finishes the item, then stops |
| `CC_SESSION_HARD` | 95 | Session HARD threshold (%) — can fire mid-item |
| `CC_WEEKLY_HARD` | 98 | Weekly HARD threshold (%) — can fire mid-item |
| `CC_HARD_ABORT` | (unset/false) | Opt in to auto-revert (`git stash`) on a HARD threshold. Same as `cc-run --enable-hard-abort` |
| `CC_USAGE_CACHE_TTL` | 30 | Usage cache lifetime (s) — also the hard-threshold detection lag |
| `CC_RESUME_BUFFER` | 60 | Extra sleep after the reset time (s) |
| `CC_CLAUDE_ARGS` | `--permission-mode acceptEdits` | Extra flags passed to `claude` |

`.cc-quota/config.json` (per-project) works too, with keys `session_soft`,
`session_hard`, `weekly_hard`, `hard_abort_enabled` — environment variables
take priority over it.

## Uninstall

Plugin install:

```
/plugin uninstall cc-quota-guard
```

Manual install:

```bash
rm -rf ~/.claude/cc-quota-guard ~/.claude/.cc-quota-cache.json ~/.local/bin/cc-run
# then remove the two quota_gate.py PostToolUse entries from settings.json by hand
```

## Contributing

Issues and PRs welcome. If you change the quota-detection or revert logic,
keep the "fail open, opt in to anything destructive, document the
limitation" style — that's the whole point of this tool.

## License

MIT — see [LICENSE](LICENSE).
