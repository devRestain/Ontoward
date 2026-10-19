#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
command=${1:-status}
if (($#)); then shift; fi
case "$command" in
  status) docker compose run --rm --no-deps -T control status --human "$@" ;;
  watch) docker compose run --rm --no-deps -T control status --watch --human "$@" ;;
  pause) docker compose run --rm --no-deps -T control pause --human "$@" ;;
  recover) docker compose run --rm --no-deps -T recovery recover-normalize "$@" ;;
  recover-text) docker compose run --rm --no-deps -T recovery recover-normalize-text "$@" ;;
  recover-provider) docker compose run --rm --no-deps -T recovery recover-normalize-provider "$@" ;;
  recover-batch) docker compose run --rm --no-deps -T recovery recover-normalize-batch "$@" ;;
  run|resume)
    log_dir="$ROOT/data/extraction/v5-enum/logs"
    mkdir -p "$log_dir"
    log_name="$(date -u +%Y%m%dT%H%M%SZ)-$$.log"
    ln -sfn "$log_name" "$log_dir/latest.log"
    printf 'Console log: %s\n' "$log_dir/$log_name"
    arguments=(run)
    if [[ "$command" == resume ]]; then arguments+=(--resume); fi
    set +e
    docker compose run --rm --no-deps -T extraction "${arguments[@]}" "$@" 2>&1 | tee "$log_dir/$log_name"
    results=("${PIPESTATUS[@]}")
    set -e
    if ((results[0])); then exit "${results[0]}"; fi
    exit "${results[1]}"
    ;;
  logs)
    log="$ROOT/data/extraction/v5-enum/logs/latest.log"
    if [[ ! -f "$log" ]]; then
      printf 'No saved console log. Use status for the checkpoint error; use this script for the next run.\n' >&2
      exit 1
    fi
    tail -n 80 -F "$log"
    ;;
  *) printf 'Usage: %s [status|watch|pause|recover|recover-text|recover-provider|recover-batch|run|resume|logs] [arguments]\n' "$0" >&2; exit 2 ;;
esac
