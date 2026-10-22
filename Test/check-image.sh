#!/bin/sh
set -eu
test_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
# Use the project's local Test image with no network, credentials, or writable mounts.
if ! docker run --rm --pull never --network none --read-only \
    --user "$(id -u):$(id -g)" --entrypoint python \
    --mount "type=bind,source=$test_root/Test,target=/current-test,readonly" \
    ontoward-test:local /test/version.py --check /current-test; then
    echo 'Rebuild the Test image before launching: docker compose -f Test/compose.yaml build --pull=false test-simulator' >&2
    exit 2
fi
