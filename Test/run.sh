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
export TEST_OUTPUT="$test_root/Tmp/test-evaluator/$test_case-$(date -u +%Y%m%dT%H%M%SZ)-$$"
export ONTOWARD_TEST_UID="$(id -u)"
export ONTOWARD_TEST_GID="$(id -g)"
mkdir -p "$TEST_OUTPUT/agent" "$TEST_OUTPUT/simulator"

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

# Refuse to replace a currently running case belonging to another invocation.
if [ -n "$(compose_test ps -q --status running test-simulator)" ]; then
    echo 'A test-simulator is already running; finish that case before starting another.' >&2
    exit 2
fi
cleanup_test() {
    compose_test stop -t 3 test-simulator >/dev/null 2>&1 || true
    compose_test rm -f test-simulator >/dev/null 2>&1 || true
}
trap cleanup_test EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
compose_test up -d --no-build --pull never --wait --wait-timeout 30 test-simulator
test_agent_status=0
compose_test run --rm --no-deps --pull never -T test-agent || test_agent_status=$?
test_report_status=0
compose_test run --rm --no-deps --pull never -T test-check python /test/report.py || test_report_status=$?
echo "Evidence: $TEST_OUTPUT"
if [ "$test_agent_status" -ne 0 ]; then
    exit "$test_agent_status"
fi
exit "$test_report_status"
