import fcntl
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from .models import canonical, digest, CONTRACT


class PauseRequested(Exception):
    pass


class OutcomeUnknown(RuntimeError):
    pass


class Jobs:
    def __init__(self, directory, identity=None, readonly=False):
        self.directory = Path(directory).resolve()
        self.path = self.directory / 'jobs.sqlite3'
        if readonly:
            self.db = sqlite3.connect(f'{self.path.as_uri()}?mode=ro', uri=True, timeout=30)
        else:
            self.directory.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(self.path, timeout=30)
            self.db.executescript('''
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=FULL;
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs(job_id TEXT PRIMARY KEY, phase TEXT NOT NULL,
                    normalized_input TEXT NOT NULL, status TEXT NOT NULL, result TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0, next_retry_at REAL, error TEXT);
                CREATE TABLE IF NOT EXISTS requests(request_id TEXT PRIMARY KEY, provider TEXT NOT NULL,
                    payload TEXT NOT NULL, job_ids TEXT NOT NULL, state TEXT NOT NULL, response TEXT, error TEXT);
                CREATE TABLE IF NOT EXISTS usage(day TEXT NOT NULL, model TEXT NOT NULL,
                    calls INTEGER NOT NULL, input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(day,model));
                CREATE TABLE IF NOT EXISTS source_rows(source TEXT NOT NULL, row_id TEXT NOT NULL,
                    payload TEXT NOT NULL, PRIMARY KEY(source,row_id));
                CREATE TABLE IF NOT EXISTS rf2(id TEXT PRIMARY KEY, effective TEXT NOT NULL,
                    active TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS rf2_modules(module TEXT NOT NULL, release TEXT NOT NULL,
                    PRIMARY KEY(module,release));
            ''')
        self.db.row_factory = sqlite3.Row
        self.interrupted = False
        if identity is not None:
            previous = self.get('identity')
            if previous is not None and previous != identity:
                self.db.close()
                raise ValueError('checkpoint_fingerprint_mismatch')
            if previous is None:
                self.set('identity', identity)
                self.set('state', 'ready')

    def close(self):
        self.db.close()

    def get(self, key, default=None):
        row = self.db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)', (key, canonical(value)))

    @contextmanager
    def worker(self):
        with (self.directory / '.worker.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError('worker_already_running') from error
            self.set('pause_requested', False)
            self.set('state', 'running')
            self.set('error', None)
            try:
                yield
            except PauseRequested:
                self.set('state', 'paused')
            except BaseException:
                self.set('state', 'failed')
                raise
            finally:
                self.db.execute('PRAGMA wal_checkpoint(FULL)')
                fcntl.flock(lock, fcntl.LOCK_UN)

    def boundary(self):
        if self.interrupted or self.get('pause_requested', False):
            raise PauseRequested()

    def pause(self):
        if self.get('state') in {'running', 'waiting_quota', 'pausing'}:
            self.set('pause_requested', True)
            self.set('state', 'pausing')
        return self.status()

    def add(self, phase, value):
        ident = digest([CONTRACT, phase, value])
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO jobs(job_id,phase,normalized_input,status) VALUES(?,?,?,?)',
                (ident, phase, canonical(value), 'pending'))
        return ident

    def pending(self, phase):
        return [dict(row) for row in self.db.execute("SELECT * FROM jobs WHERE phase=? AND status != 'done' ORDER BY job_id", (phase,))]

    def results(self, phase):
        return [json.loads(row[0]) for row in self.db.execute("SELECT result FROM jobs WHERE phase=? AND status='done' ORDER BY job_id", (phase,))]

    def prepare_request(self, request_id, provider, payload, job_ids):
        with self.db:
            self.db.execute('INSERT INTO requests VALUES(?,?,?,?,?,?,?)',
                (request_id, provider, canonical(payload), canonical(job_ids), 'prepared', None, None))
            self.db.executemany("UPDATE jobs SET status='running', attempt_count=attempt_count+1 WHERE job_id=?", [(j,) for j in job_ids])

    def request_state(self, ident, state, response=None, error=None):
        with self.db:
            self.db.execute('UPDATE requests SET state=?,response=COALESCE(?,response),error=? WHERE request_id=?',
                (state, canonical(response) if response is not None else None, error, ident))

    def accept(self, request_id, valid, invalid, usage=None):
        with self.db:
            for ident, result in valid.items():
                self.db.execute("UPDATE jobs SET status='done',result=?,error=NULL WHERE job_id=?", (canonical(result),ident))
            for ident, error in invalid.items():
                self.db.execute("UPDATE jobs SET status='retry',error=? WHERE job_id=?", (error,ident))
            if usage:
                self.db.execute('''INSERT INTO usage(day,model,calls,input_tokens,output_tokens) VALUES(?,?,1,?,?)
                    ON CONFLICT(day,model) DO UPDATE SET calls=calls+1,
                    input_tokens=input_tokens+excluded.input_tokens,output_tokens=output_tokens+excluded.output_tokens''',
                    (usage['day'],usage['model'],usage.get('input_tokens',0),usage.get('output_tokens',0)))
            self.db.execute("UPDATE requests SET state='accepted' WHERE request_id=?", (request_id,))

    def status(self):
        return {'run_id': self.directory.name, 'state': self.get('state'), 'phase': self.get('phase'),
            'provider': self.get('identity',{}).get('config',{}).get('provider'),
            'pause_requested': self.get('pause_requested',False),
            'jobs': {row[0]:row[1] for row in self.db.execute('SELECT status,COUNT(*) FROM jobs GROUP BY status')},
            'requests': {row[0]:row[1] for row in self.db.execute('SELECT state,COUNT(*) FROM requests GROUP BY state')},
            'usage': [dict(row) for row in self.db.execute('SELECT * FROM usage ORDER BY day,model')],
            'error': self.get('error')}
