#!/usr/bin/env bash
# tests/test_cc_run.sh — regression tests for bin/cc-run's retry/backoff/
# timeout resilience and language output, using a fake `claude` on PATH
# instead of the real CLI. These mirror scenarios originally verified by
# hand with real subprocess runs during development (see CHANGELOG.md's
# 0.6.0 entry for the incident that motivated the retry logic).
#
# Usage: bash tests/test_cc_run.sh
# Exits 0 if everything passes, 1 otherwise (also prints a PASS/FAIL per
# scenario so a CI log shows exactly what ran).
#
# Runtime note: on Windows/Git-Bash this can take a few minutes (each
# scenario invokes cc-run, which backgrounds `claude` with `&` inside its
# heartbeat loop — command substitution waiting for every backgrounded
# job's file descriptors to close adds real wall-clock delay under Git
# Bash's process emulation, independent of any of the retry/backoff
# sleeps). It's a known environment characteristic, not a hang — the CI
# workflow's job-level timeout accounts for it.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CC_RUN="$REPO_ROOT/bin/cc-run"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

FAILURES=0
pass() { echo "  PASS: $1"; }
fail() { echo "  FAIL: $1"; FAILURES=$((FAILURES + 1)); }

to_py() {
  if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi
}

# Fresh fake-claude harness for each scenario: a project dir + a fakebin/
# with a `claude` script whose behavior is set by the caller.
new_scenario() {
  local name="$1"
  SCENARIO_DIR="$WORK/$name"
  rm -rf "$SCENARIO_DIR"
  mkdir -p "$SCENARIO_DIR/proj" "$SCENARIO_DIR/fakebin"
}

echo "=== 1) retry-then-succeed: fails twice, succeeds on 3rd attempt ==="
new_scenario retry_then_succeed
cat > "$SCENARIO_DIR/fakebin/claude" <<SH
#!/usr/bin/env bash
STATE_FILE="$(to_py "$SCENARIO_DIR")/attempt_count"
N=0
[[ -f "\$STATE_FILE" ]] && N=\$(cat "\$STATE_FILE")
N=\$((N+1))
echo "\$N" > "\$STATE_FILE"
if [[ "\$N" -lt 3 ]]; then exit 1; fi
mkdir -p "$(to_py "$SCENARIO_DIR")/proj/.cc-quota"
echo "CC_QUOTA_DONE" >> "$(to_py "$SCENARIO_DIR")/proj/.cc-quota/progress.md"
SH
chmod +x "$SCENARIO_DIR/fakebin/claude"
OUT=$(cd "$SCENARIO_DIR/proj" && PATH="$SCENARIO_DIR/fakebin:$PATH" CC_RETRY_BACKOFF=1 CC_MAX_RETRIES=5 CC_ROUND_TIMEOUT=30 bash "$CC_RUN" "task" 2>&1)
if echo "$OUT" | grep -q "Task complete" && [[ "$(cat "$SCENARIO_DIR/attempt_count")" == "3" ]]; then
  pass "retried through 2 failures and completed on attempt 3"
else
  fail "expected completion after 3 attempts; got: $OUT"
fi

echo "=== 2) gives up after CC_MAX_RETRIES, exits non-zero ==="
new_scenario gives_up
cat > "$SCENARIO_DIR/fakebin/claude" <<'SH'
#!/usr/bin/env bash
exit 1
SH
chmod +x "$SCENARIO_DIR/fakebin/claude"
(cd "$SCENARIO_DIR/proj" && PATH="$SCENARIO_DIR/fakebin:$PATH" CC_RETRY_BACKOFF=1 CC_MAX_RETRIES=2 CC_ROUND_TIMEOUT=30 bash "$CC_RUN" "task" >"$SCENARIO_DIR/out.log" 2>&1)
STATUS=$?
if [[ "$STATUS" -ne 0 ]] && grep -q "giving up" "$SCENARIO_DIR/out.log"; then
  pass "gave up after exhausting retries and exited non-zero ($STATUS)"
else
  fail "expected non-zero exit + 'giving up' message; exit=$STATUS, log:
$(cat "$SCENARIO_DIR/out.log")"
fi

echo "=== 3) stuck round is killed at CC_ROUND_TIMEOUT and retried ==="
new_scenario timeout_retry
cat > "$SCENARIO_DIR/fakebin/claude" <<SH
#!/usr/bin/env bash
STATE_FILE="$(to_py "$SCENARIO_DIR")/attempt_count"
N=0
[[ -f "\$STATE_FILE" ]] && N=\$(cat "\$STATE_FILE")
N=\$((N+1))
echo "\$N" > "\$STATE_FILE"
if [[ "\$N" -eq 1 ]]; then sleep 20; else
  mkdir -p "$(to_py "$SCENARIO_DIR")/proj/.cc-quota"
  echo "CC_QUOTA_DONE" >> "$(to_py "$SCENARIO_DIR")/proj/.cc-quota/progress.md"
fi
SH
chmod +x "$SCENARIO_DIR/fakebin/claude"
# No external timeout wrapper needed: CC_ROUND_TIMEOUT=5 makes cc-run
# itself kill the hung fake claude well before its 20s sleep finishes. 20s
# (not something much longer) also caps how long this scenario can take in
# the worst case on a platform where the kill doesn't take effect
# immediately and cc-run ends up waiting out the natural sleep instead.
OUT=$(cd "$SCENARIO_DIR/proj" && PATH="$SCENARIO_DIR/fakebin:$PATH" CC_RETRY_BACKOFF=1 CC_MAX_RETRIES=3 CC_ROUND_TIMEOUT=5 bash "$CC_RUN" "task" 2>&1)
if echo "$OUT" | grep -q "No progress for" && echo "$OUT" | grep -q "Task complete"; then
  pass "hung round was force-ended by CC_ROUND_TIMEOUT, retried, then completed"
else
  fail "expected a timeout message then completion; got: $OUT"
fi

echo "=== 4) a FAST round is never misreported as a timeout (race-condition fix) ==="
new_scenario no_false_timeout
cat > "$SCENARIO_DIR/fakebin/claude" <<SH
#!/usr/bin/env bash
mkdir -p "$(to_py "$SCENARIO_DIR")/proj/.cc-quota"
echo "CC_QUOTA_DONE" >> "$(to_py "$SCENARIO_DIR")/proj/.cc-quota/progress.md"
SH
chmod +x "$SCENARIO_DIR/fakebin/claude"
OUT=$(cd "$SCENARIO_DIR/proj" && PATH="$SCENARIO_DIR/fakebin:$PATH" CC_ROUND_TIMEOUT=5 bash "$CC_RUN" "task" 2>&1)
if echo "$OUT" | grep -q "Task complete" && ! echo "$OUT" | grep -q "No progress for"; then
  pass "fast completion was not misreported as a timeout"
else
  fail "a fast round should never see a timeout message; got: $OUT"
fi

echo "=== 5) stale CC_QUOTA_DONE from a previous run is archived, not reused ==="
new_scenario stale_done
mkdir -p "$SCENARIO_DIR/proj/.cc-quota"
echo "CC_QUOTA_DONE" >> "$SCENARIO_DIR/proj/.cc-quota/progress.md"
cat > "$SCENARIO_DIR/fakebin/claude" <<SH
#!/usr/bin/env bash
mkdir -p "$(to_py "$SCENARIO_DIR")/proj/.cc-quota"
echo "did real work" >> "$(to_py "$SCENARIO_DIR")/proj/.cc-quota/progress.md"
echo "CC_QUOTA_DONE" >> "$(to_py "$SCENARIO_DIR")/proj/.cc-quota/progress.md"
SH
chmod +x "$SCENARIO_DIR/fakebin/claude"
OUT=$(cd "$SCENARIO_DIR/proj" && PATH="$SCENARIO_DIR/fakebin:$PATH" bash "$CC_RUN" "new task" 2>&1)
if echo "$OUT" | grep -q "archived" && ls "$SCENARIO_DIR/proj/.cc-quota/"progress.md.done-* >/dev/null 2>&1; then
  pass "stale CC_QUOTA_DONE was archived before the new run started"
else
  fail "expected the old progress.md to be archived; got: $OUT"
fi

echo "=== 6) CC_LANG=tr localizes cc-run's own output ==="
new_scenario language_tr
cat > "$SCENARIO_DIR/fakebin/claude" <<SH
#!/usr/bin/env bash
mkdir -p "$(to_py "$SCENARIO_DIR")/proj/.cc-quota"
echo "CC_QUOTA_DONE" >> "$(to_py "$SCENARIO_DIR")/proj/.cc-quota/progress.md"
SH
chmod +x "$SCENARIO_DIR/fakebin/claude"
OUT=$(cd "$SCENARIO_DIR/proj" && PATH="$SCENARIO_DIR/fakebin:$PATH" CC_LANG=tr bash "$CC_RUN" "task" 2>&1)
if echo "$OUT" | grep -q "Görev tamamlandı"; then
  pass "CC_LANG=tr produced Turkish output"
else
  fail "expected Turkish 'Görev tamamlandı'; got: $OUT"
fi

echo "=== 7) .cc-quota/config.json's \"language\" key works without CC_LANG ==="
new_scenario language_config_json
mkdir -p "$SCENARIO_DIR/proj/.cc-quota"
echo '{"language": "tr"}' > "$SCENARIO_DIR/proj/.cc-quota/config.json"
cat > "$SCENARIO_DIR/fakebin/claude" <<SH
#!/usr/bin/env bash
mkdir -p "$(to_py "$SCENARIO_DIR")/proj/.cc-quota"
echo "CC_QUOTA_DONE" >> "$(to_py "$SCENARIO_DIR")/proj/.cc-quota/progress.md"
SH
chmod +x "$SCENARIO_DIR/fakebin/claude"
OUT=$(cd "$SCENARIO_DIR/proj" && PATH="$SCENARIO_DIR/fakebin:$PATH" bash "$CC_RUN" "task" 2>&1)
if echo "$OUT" | grep -q "Görev tamamlandı"; then
  pass "config.json's language key selected Turkish with no CC_LANG set"
else
  fail "expected Turkish output from config.json alone; got: $OUT"
fi

echo
echo "--- bin/cc-run syntax check ---"
if bash -n "$CC_RUN"; then
  pass "bash -n bin/cc-run"
else
  fail "bash -n bin/cc-run reported a syntax error"
fi

echo
if [[ "$FAILURES" -eq 0 ]]; then
  echo "ALL SCENARIOS PASSED"
  exit 0
else
  echo "$FAILURES SCENARIO(S) FAILED"
  exit 1
fi
