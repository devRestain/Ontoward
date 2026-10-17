#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
case "${1:-start}" in
  start)
    docker compose -f Test/compose.knowledge.yaml up -d --no-build --pull never --wait knowledge-viewer
    printf '\nKnowledge viewer: http://127.0.0.1:8766\n'
    ;;
  stop)
    docker compose -f Test/compose.knowledge.yaml stop knowledge-viewer
    ;;
  status)
    docker compose -f Test/compose.knowledge.yaml ps knowledge-viewer
    ;;
  verify)
    docker compose -f compose.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm --no-deps --pull never -T \
      -v "$ROOT/data:/workspace/data:ro" -v "$ROOT/submission:/workspace/submission:ro" \
      dev python -B Test/test_knowledge.py
    ;;
  *) printf 'Usage: sh Test/knowledge.sh [start|stop|status|verify]\n' >&2; exit 2 ;;
esac
