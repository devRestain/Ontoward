#!/bin/sh
set -eu
set -f

test_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
test_runs="$test_root/Tmp/test-evaluator"
export ONTOWARD_TEST_UID="$(id -u)"
export ONTOWARD_TEST_GID="$(id -g)"
mkdir -p "$test_runs/.web"

compose_web() {
    docker compose -f "$test_root/Test/compose.yaml" "$@"
}
worker() {
    compose_web exec -T test-web python /test/web.py "$@"
}
if ! mkdir "$test_runs/.web/launcher" 2>/dev/null; then
    previous_pid=$(cat "$test_runs/.web/launcher/pid" 2>/dev/null || true)
    case "$previous_pid" in
        ''|*[!0-9]*) echo 'The web launcher lock has no valid owner; inspect Tmp/test-evaluator/.web/launcher.' >&2; exit 2 ;;
    esac
    if kill -0 "$previous_pid" 2>/dev/null; then
        echo 'A web launcher is already running. Use http://127.0.0.1:8765 or stop its terminal.' >&2
        exit 2
    fi
    if [ -n "$(compose_web ps -q --status running test-simulator)" ] || \
       [ -n "$(docker ps -q --filter label=com.docker.compose.project=ontoward --filter label=com.docker.compose.service=test-agent)" ]; then
        echo 'The old launcher stopped, but a test container is still running. Inspect that Ontoward test before restarting.' >&2
        exit 2
    fi
    unlink "$test_runs/.web/launcher/pid"
fi
echo "$$" > "$test_runs/.web/launcher/pid"
runner_pid=
web_started=0
cleanup_web() {
    trap - EXIT INT TERM
    if [ -n "$runner_pid" ]; then
        kill -TERM "$runner_pid" 2>/dev/null || true
        wait "$runner_pid" 2>/dev/null || true
    fi
    if [ "$web_started" = 1 ]; then
        worker stop >/dev/null 2>&1 || true
        compose_web stop -t 3 test-web >/dev/null 2>&1 || true
        compose_web rm -f test-web >/dev/null 2>&1 || true
    fi
    unlink "$test_runs/.web/launcher/pid"
    rmdir "$test_runs/.web/launcher"
}
trap cleanup_web EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
web_started=1
compose_web up -d --no-build --pull never --wait --wait-timeout 30 test-web
worker stop
worker tick
echo 'Ontoward Test: http://127.0.0.1:8765'
echo 'Keep this terminal open. Press Ctrl+C to stop the website and its current test.'
while :; do
    date +%s > "$test_runs/.web/heartbeat.tmp"
    mv "$test_runs/.web/heartbeat.tmp" "$test_runs/.web/heartbeat"
    if [ -z "$runner_pid" ]; then
        request=
        if [ -f "$test_runs/.web/request" ]; then
            request=$(worker claim)
        fi
        if [ -n "$request" ]; then
            set -- $request
            if [ "$#" -ne 4 ]; then
                echo 'Invalid web request' >&2
                exit 2
            fi
            run_id=$1
            TEST_RUN_ID="$1" TEST_WEB_RUN="$1" TEST_MAX_NOVA_REQUESTS="$4" \
                sh "$test_root/Test/run.sh" "$2" "$3" >> "$test_runs/$1/runner.log" 2>&1 &
            runner_pid=$!
        fi
    elif ! kill -0 "$runner_pid" 2>/dev/null; then
        wait "$runner_pid" || true
        runner_pid=
        worker finish "$run_id"
    fi
    sleep 2
done
