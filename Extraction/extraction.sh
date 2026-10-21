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
  recover-empty) docker compose run --rm --no-deps -T recovery recover-normalize-empty "$@" ;;
  switch-sol) docker compose run --rm --no-deps -T recovery recover-questions-sol --config /app/config.sol.json "$@" ;;
  recover-questions) docker compose run --rm --no-deps -T recovery recover-questions "$@" ;;
  recover-draft) docker compose run --rm --no-deps -T recovery recover-draft --config /app/config.sol.json "$@" ;;
  switch-provider) docker compose run --rm --no-deps -T recovery recover-draft-provider --config /app/config.api-luna.json "$@" ;;
  recover-endpoints) docker compose run --rm --no-deps -T recovery recover-draft-endpoints --config /app/config.api-luna.json "$@" ;;
  recover-packets) docker compose run --rm --no-deps -T recovery recover-draft-packets --config /app/config.api-luna.json "$@" ;;
  recover-patch) docker compose run --rm --no-deps -T recovery recover-patch --config /app/config.api-luna.json "$@" ;;
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
  *) printf 'Usage: %s [status|watch|pause|recover|recover-text|recover-provider|recover-batch|recover-empty|recover-questions|recover-draft|recover-endpoints|recover-packets|recover-patch|switch-provider|switch-sol|run|resume|logs] [arguments]\n' "$0" >&2; exit 2 ;;
esac
