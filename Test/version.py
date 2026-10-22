"""Pin executable Test sources without reading credentials or project data."""
import hashlib
import json
from pathlib import Path
import sys


def source_version(root=None):
    root = Path(root) if root is not None else Path(__file__).parent
    suffixes = {'.py', '.js', '.html', '.css', '.yaml', '.sh'}
    sources = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
               for path in sorted(root.rglob('*')) if path.is_file() and not path.is_symlink()
               and (path.suffix in suffixes or path.name == 'Dockerfile')}
    digest = hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()
    return {'format': 1, 'sha256': digest, 'source_sha256': sources}


def main():
    image = source_version()
    expected = source_version(sys.argv[2]) if len(sys.argv) == 3 and sys.argv[1] == '--check' else image
    changed = sorted(name for name in image['source_sha256'].keys() | expected['source_sha256'].keys()
                     if image['source_sha256'].get(name) != expected['source_sha256'].get(name))
    print(json.dumps({'status': 'fail' if changed else 'pass', 'image': image,
                      'workspace_sha256': expected['sha256'], 'changed': changed}))
    if changed:
        print('Test image is stale. Run: docker compose -f Test/compose.yaml build --pull=false test-simulator', file=sys.stderr)
    return bool(changed)


if __name__ == '__main__':
    raise SystemExit(main())
