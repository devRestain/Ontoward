import json
import os
from pathlib import Path
import subprocess
import sys
import time


def sandbox():
    def read(path):
        value = Path(path)
        return value.read_text().strip() if value.exists() else 'unknown'
    mounts = [line.split() for line in read('/proc/mounts').splitlines()]
    options = {row[1]: row[3].split(',') for row in mounts if len(row) >= 4}
    return {'cpu_max': read('/sys/fs/cgroup/cpu.max'), 'memory_max': read('/sys/fs/cgroup/memory.max'),
            'root_read_only': 'ro' in options.get('/', []),
            'submission_read_only': 'ro' in options.get('/submission', []),
            'tmp_options': options.get('/tmp', []), 'output_writable': os.access('/output', os.W_OK)}


def main():
    output = Path('/output')
    started = time.monotonic()
    report = {'status': 'failed', 'exit_code': None}
    # The simulator separately starts the 30-minute clock at ready().
    try:
        with (output / 'stdout.log').open('w') as stdout, (output / 'stderr.log').open('w') as stderr:
            entry = '/submission/run.py' if os.getenv('TEST_TRACE') == '0' else '/test/observe.py'
            process = subprocess.run([sys.executable, entry], stdout=stdout, stderr=stderr, timeout=2400)
        report.update(status='exited', exit_code=process.returncode)
    except subprocess.TimeoutExpired:
        report['status'] = 'timeout'
    report.update(seconds=round(time.monotonic() - started, 3), uid=os.getuid(),
                  development_key_present=bool(os.getenv('NOVA_DEV_KEY')),
                  openai_key_present=bool(os.getenv('OPENAI_API_KEY')),
                  samples_visible=Path('/cases').exists(), sandbox=sandbox())
    (output / 'process.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
    return report['exit_code'] if report['exit_code'] is not None else 124


if __name__ == '__main__':
    raise SystemExit(main())
