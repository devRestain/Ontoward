#!/bin/sh
set -eu

test_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
test_case=${1:-C10}
test_mode=${2:-scripted}
case "$test_case" in
    C01|C03|C10|verify) ;;
    *) echo 'Usage: sh Test/run.sh [C01|C03|C10] [scripted|nova], or sh Test/run.sh verify' >&2; exit 2 ;;
esac
case "$test_mode" in
    scripted|nova) ;;
    *) echo 'Choose scripted or nova mode' >&2; exit 2 ;;
esac
if [ "$test_case" = verify ] && [ "$test_mode" != scripted ]; then
    echo 'Verification always runs offline' >&2
    exit 2
fi

export TEST_CASE="$test_case"
export TEST_RUN_ID="${TEST_RUN_ID:-$test_case-$(date -u +%Y%m%dT%H%M%SZ)-$$}"
case "$TEST_RUN_ID" in
    ''|*[!A-Za-z0-9_-]*|-*|_*) echo 'Invalid test run ID' >&2; exit 2 ;;
esac
if [ "${#TEST_RUN_ID}" -gt 128 ]; then
    echo 'Test run ID is too long' >&2
    exit 2
fi
export TEST_MAX_NOVA_REQUESTS="${TEST_MAX_NOVA_REQUESTS:-200}"
case "$TEST_MAX_NOVA_REQUESTS" in
    [0-9]|[0-9][0-9]|[0-9][0-9][0-9]|1000) ;;
    *) echo 'Choose a NOVA request ceiling from 1 to 1000' >&2; exit 2 ;;
esac
if [ "$TEST_MAX_NOVA_REQUESTS" -eq 0 ]; then
    echo 'Choose a NOVA request ceiling from 1 to 1000' >&2
    exit 2
fi
test_runs="$test_root/Tmp/test-evaluator"
export TEST_OUTPUT="$test_runs/$TEST_RUN_ID"
export ONTOWARD_TEST_UID="$(id -u)"
export ONTOWARD_TEST_GID="$(id -g)"
mkdir -p "$test_runs"
test_lock="$test_runs/.run-lock"
if ! mkdir "$test_lock" 2>/dev/null; then
    if [ "${TEST_WEB_RUN:-}" != "$TEST_RUN_ID" ] || [ "$(cat "$test_lock/owner" 2>/dev/null)" != "$TEST_RUN_ID" ]; then
        echo 'Another test owns Tmp/test-evaluator/.run-lock. Finish that run before starting another.' >&2
        exit 2
    fi
else
    printf '%s\n' "$TEST_RUN_ID" > "$test_lock/owner"
fi
if ! mkdir "$test_lock/started" 2>/dev/null; then
    echo 'This test has already been started.' >&2
    exit 2
fi
simulator_owned=0
output_owned=0
agent_pid=
reported=0
agent_name="ontoward-test-agent-$TEST_RUN_ID"

compose_base() {
    docker compose -f "$test_root/Test/compose.yaml" "$@"
}
set_status() {
    printf '%s\n' "$1" > "$TEST_OUTPUT/status.tmp"
    mv "$TEST_OUTPUT/status.tmp" "$TEST_OUTPUT/status"
}
cleanup_test() {
    test_exit=$?
    trap - EXIT INT TERM
    if [ -n "$agent_pid" ]; then
        kill -TERM "$agent_pid" 2>/dev/null || true
        agent_owner=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}|{{index .Config.Labels "com.docker.compose.service"}}|{{index .Config.Labels "io.ontoward.test-run"}}' "$agent_name" 2>/dev/null || true)
        if [ "$agent_owner" = "ontoward|test-agent|$TEST_RUN_ID" ]; then
            docker stop -t 3 "$agent_name" >/dev/null 2>&1 || true
        fi
        wait "$agent_pid" 2>/dev/null || true
    fi
    if [ "$simulator_owned" = 1 ]; then
        simulator_id=$(compose_base ps -a -q test-simulator 2>/dev/null || true)
        simulator_owner=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}|{{index .Config.Labels "com.docker.compose.service"}}|{{index .Config.Labels "io.ontoward.test-run"}}' "$simulator_id" 2>/dev/null || true)
        if [ "$simulator_owner" = "ontoward|test-simulator|$TEST_RUN_ID" ]; then
            docker stop -t 3 "$simulator_id" >/dev/null 2>&1 || true
            docker rm "$simulator_id" >/dev/null 2>&1 || true
        fi
    fi
    if [ "$output_owned" = 1 ]; then
        case "$test_exit" in
            0) final_status=completed ;;
            124) final_status=timeout ;;
            130|143) final_status=interrupted ;;
            *) final_status=failed ;;
        esac
        date +%s > "$TEST_OUTPUT/ended"
        printf '%s\n' "$test_exit" > "$TEST_OUTPUT/exit-code"
        if [ "$test_case" != verify ] && [ "$reported" = 0 ]; then
            compose_base run --rm --no-deps --pull never -T test-check python /test/report.py >> "$TEST_OUTPUT/runner.log" 2>&1 || true
        fi
        set_status "$final_status"
        echo "Evidence: $TEST_OUTPUT"
    fi
    if [ "$(cat "$test_lock/owner" 2>/dev/null)" = "$TEST_RUN_ID" ]; then
        unlink "$test_lock/owner"
        rmdir "$test_lock/started" "$test_lock"
    fi
    exit "$test_exit"
}
trap cleanup_test EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
if [ -d "$TEST_OUTPUT" ] && [ "${TEST_WEB_RUN:-}" != "$TEST_RUN_ID" ]; then
    echo 'Refusing to reuse an existing run directory.' >&2
    exit 2
fi
mkdir -p "$TEST_OUTPUT/agent" "$TEST_OUTPUT/simulator"
output_owned=1
printf '%s\n' "$TEST_RUN_ID" > "$TEST_OUTPUT/run-id"
printf '%s\n' "$test_case" "$test_mode" "$TEST_MAX_NOVA_REQUESTS" > "$TEST_OUTPUT/run.args"
date +%s > "$TEST_OUTPUT/started"
set_status starting

compose_test() {
    if [ "$test_mode" = nova ]; then
        if [ -f "$test_root/.env" ]; then
            docker compose --env-file "$test_root/.env" -f "$test_root/Test/compose.yaml" -f "$test_root/Test/compose.nova.yaml" "$@"
        else
            docker compose -f "$test_root/Test/compose.yaml" -f "$test_root/Test/compose.nova.yaml" "$@"
        fi
    else
        docker compose -f "$test_root/Test/compose.yaml" "$@"
    fi
}

if [ "$test_case" = verify ]; then
    compose_test run --rm --no-deps --pull never -T test-check
    echo "Evidence: $TEST_OUTPUT/verification.json"
    exit 0
fi

if [ -n "$(compose_base ps -q --status running test-simulator)" ]; then
    echo 'A test-simulator is already running; finish that case before starting another.' >&2
    exit 2
fi
simulator_owned=1
compose_test up -d --no-build --pull never --wait --wait-timeout 30 test-simulator >> "$TEST_OUTPUT/runner.log" 2>&1
set_status running
test_agent_status=0
compose_base run --rm --name "$agent_name" --label "io.ontoward.test-run=$TEST_RUN_ID" --no-deps --pull never -T test-agent &
agent_pid=$!
wait "$agent_pid" || test_agent_status=$?
agent_pid=
test_report_status=0
compose_base run --rm --no-deps --pull never -T test-check python /test/report.py || test_report_status=$?
reported=1
if [ "$test_agent_status" -ne 0 ]; then
    exit "$test_agent_status"
fi
exit "$test_report_status"
