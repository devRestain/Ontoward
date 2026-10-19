import json
import os
from pathlib import Path
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
import uuid

from viewer import render, UI


ACTIVE = {'starting', 'running'}
RUN_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z')


def write(path, value):
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(value, encoding='utf-8')
    temporary.replace(path)


def read(path, fallback=''):
    try:
        return path.read_text(encoding='utf-8').strip()
    except OSError:
        return fallback


def read_json(path):
    try:
        return json.loads(read(path))
    except ValueError:
        return {}


class Runs:
    def __init__(self, root):
        self.root = Path(root)
        self.control = self.root / '.web'
        self.control.mkdir(parents=True, exist_ok=True)
        self.lock = self.root / '.run-lock'
        self.guard = threading.Lock()

    def directory(self, run_id):
        if not RUN_ID.fullmatch(run_id):
            raise ValueError('Invalid run ID')
        path = self.root / run_id
        if path.is_symlink() or path.resolve().parent != self.root.resolve():
            raise ValueError('Invalid run directory')
        return path

    def online(self):
        try:
            return time.time() - float(read(self.control / 'heartbeat')) < 12
        except ValueError:
            return False

    def status(self, run_id):
        path = self.directory(run_id)
        if not path.is_dir():
            raise FileNotFoundError(run_id)
        meta, summary = read_json(path / 'run.json'), read_json(path / 'simulator/summary.json')
        args = read(path / 'run.args').splitlines()
        state = read(path / 'status') or ('completed' if summary.get('status') == 'completed' else 'saved')
        error = None
        if state in ACTIVE and meta.get('origin') == 'web' and not self.online():
            state, error = 'interrupted', '실행기 연결이 끊겼습니다. 시작한 터미널을 확인하세요.'
        result = read_json(path / 'result.json')
        try:
            started = float(read(path / 'started'))
            ended = float(read(path / 'ended')) if read(path / 'ended') else time.time()
            seconds = max(0, round(ended - started))
        except ValueError:
            seconds = 0
        try:
            created = float(read(path / 'started'))
        except ValueError:
            created = (path / 'run.args').stat().st_mtime if (path / 'run.args').is_file() else path.stat().st_mtime
        return {'id': run_id, 'case': meta.get('case') or (args[0] if args else summary.get('case_id', 'unknown')),
                'backend': meta.get('backend') or (args[1] if len(args) > 1 else summary.get('backend', 'unknown')),
                'maximum': meta.get('maximum') or (args[2] if len(args) > 2 else None),
                'fixture_kind': meta.get('fixture_kind'),
                'created': meta.get('created', created), 'state': state, 'seconds': seconds,
                'result': result.get('status', 'unknown'), 'error': error,
                'report_url': f'/runs/{run_id}/report.html' if state not in ACTIVE else None}

    def listing(self):
        entries = []
        for path in self.root.iterdir():
            if path.is_dir() and not path.is_symlink() and RUN_ID.fullmatch(path.name) and any(
                    (path / name).exists() for name in ('run.json', 'run.args', 'simulator/summary.json', 'result.json')):
                if read(path / 'run.args').splitlines()[:1] == ['verify']:
                    continue
                entries.append(self.status(path.name))
        entries.sort(key=lambda row: row['created'], reverse=True)
        return entries

    def start(self, body):
        if not isinstance(body, dict) or set(body) != {'case', 'backend', 'maximum'}:
            raise ValueError('Choose case, backend and maximum')
        case, backend, maximum = body['case'], body['backend'], body['maximum']
        if case not in ('C01', 'C03', 'C10') or backend not in ('nova', 'scripted') or type(maximum) is not int or not 1 <= maximum <= 1000:
            raise ValueError('Invalid case, backend or request ceiling')
        with self.guard:
            if not self.online():
                raise RuntimeError('실행기가 연결되지 않았습니다. sh Test/web.sh로 시작하세요.')
            if read(self.control / 'active'):
                raise FileExistsError('A test is already running')
            self.lock.mkdir()
            run_id = case + '-' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-' + uuid.uuid4().hex[:10]
            path = self.directory(run_id)
            try:
                write(self.lock / 'owner', run_id)
                path.mkdir()
                meta = {'id': run_id, 'case': case, 'backend': backend, 'maximum': maximum,
                        'created': time.time(), 'origin': 'web'}
                write(path / 'run.json', json.dumps(meta))
                write(path / 'status', 'starting')
                write(path / 'started', str(time.time()))
                write(self.control / 'request', f'{run_id} {case} {backend} {maximum}')
            except Exception:
                self.release(run_id)
                raise
            return self.status(run_id)

    def release(self, run_id):
        if read(self.lock / 'owner') == run_id:
            (self.lock / 'owner').unlink(missing_ok=True)
            started = self.lock / 'started'
            if started.is_dir():
                started.rmdir()
            self.lock.rmdir()

    def worker(self, command, args):
        if command == 'tick':
            write(self.control / 'heartbeat', str(time.time()))
        elif command == 'claim':
            request = read(self.control / 'request')
            if request:
                run_id = request.split()[0]
                self.directory(run_id)
                write(self.control / 'active', run_id)
                (self.control / 'request').unlink()
                print(request)
        elif command in ('finish', 'stop'):
            run_id = args[0] if command == 'finish' else read(self.control / 'active') or read(self.control / 'request').split(' ')[0]
            if run_id:
                path = self.directory(run_id)
                unfinished = read(path / 'status') in ACTIVE
                if unfinished:
                    write(path / 'ended', str(time.time()))
                render(path)
                if unfinished:
                    write(path / 'status', 'interrupted' if command == 'stop' else 'failed')
                self.release(run_id)
            write(self.control / 'active', '')
            (self.control / 'request').unlink(missing_ok=True)
            if command == 'stop':
                (self.control / 'heartbeat').unlink(missing_ok=True)


def http_server(runs, address=('0.0.0.0', 8080)):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, status, value, content_type='application/json; charset=utf-8'):
            data = json.dumps(value, ensure_ascii=False).encode() if isinstance(value, (dict, list)) else value
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(data)

        def handle_request(self):
            host = self.headers.get('Host', '')
            if urlsplit('http://' + host).hostname not in ('127.0.0.1', 'localhost'):
                return self.respond(403, {'error': 'LOCAL_HOST_REQUIRED'})
            path = urlsplit(self.path).path
            try:
                if self.command == 'POST':
                    if path != '/api/runs':
                        return self.respond(404, {'error': 'NOT_FOUND'})
                    if self.headers.get('Origin', 'http://' + host) != 'http://' + host or self.headers.get('Sec-Fetch-Site') == 'cross-site':
                        return self.respond(403, {'error': 'SAME_ORIGIN_REQUIRED'})
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 4096 or self.headers.get_content_type() != 'application/json':
                        return self.respond(400, {'error': 'JSON_REQUIRED'})
                    return self.respond(202, runs.start(json.loads(self.rfile.read(length))))
                if path == '/health':
                    return self.respond(200, {'ready': True})
                if path == '/api/runs':
                    return self.respond(200, {'runs': runs.listing(), 'worker_online': runs.online(),
                                              'busy': runs.lock.exists() or bool(read(runs.control / 'active'))})
                if path.startswith('/api/runs/'):
                    return self.respond(200, runs.status(path[len('/api/runs/'):]))
                if path.startswith('/runs/') and path.rsplit('/', 1)[-1] in {'report.html', 'inspection.json'}:
                    run_id, filename = path[len('/runs/'):].rsplit('/', 1)
                    folder = runs.directory(run_id)
                    runs.status(run_id)
                    with runs.guard:
                        render(folder)
                    kind = 'text/html' if filename == 'report.html' else 'application/json'
                    return self.respond(200, (folder / filename).read_bytes(), kind + '; charset=utf-8')
                files = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'),
                         '/style.css': ('style.css', 'text/css')}
                if path in files:
                    name, kind = files[path]
                    return self.respond(200, (UI / name).read_bytes(), kind + '; charset=utf-8')
                self.respond(404, {'error': 'NOT_FOUND'})
            except FileExistsError:
                self.respond(409, {'error': 'BUSY', 'message': '이미 테스트가 실행 중입니다.'})
            except FileNotFoundError:
                self.respond(404, {'error': 'NOT_FOUND'})
            except (ValueError, TypeError):
                self.respond(400, {'error': 'INVALID_REQUEST'})
            except RuntimeError as error:
                self.respond(503, {'error': 'WORKER_OFFLINE', 'message': str(error)})
            except OSError:
                self.respond(500, {'error': 'STORAGE_ERROR', 'message': '테스트 출력 디렉터리의 권한과 저장 공간을 확인하세요.'})

        do_GET = do_POST = handle_request
    return ThreadingHTTPServer(address, Handler)


if __name__ == '__main__':
    runs = Runs(os.environ.get('TEST_RUNS_DIR', '/runs'))
    if len(sys.argv) > 1:
        runs.worker(sys.argv[1], sys.argv[2:])
    else:
        http_server(runs).serve_forever()
