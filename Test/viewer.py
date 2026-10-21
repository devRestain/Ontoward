import json
from pathlib import Path

from inspection import inspect_run


UI = Path(__file__).with_name('ui')


def collect(root):
    root = Path(root)
    warnings = []
    def read(name, default):
        try:
            return json.loads((root / name).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return default
    def lines(name):
        result = []
        try:
            content = (root / name).read_text(encoding='utf-8').splitlines()
        except OSError:
            return result
        for number, line in enumerate(content, 1):
            try:
                result.append(json.loads(line))
            except ValueError:
                warnings.append(f'{name}:{number} incomplete JSON')
        return result
    def tail(name):
        try:
            with (root / name).open('rb') as stream:
                stream.seek(max(0, (root / name).stat().st_size - 65536))
                return stream.read().decode('utf-8', errors='replace')
        except OSError:
            return ''
    events = lines('agent/trace.jsonl')
    complete = (any(row.get('kind') == 'initial' for row in events)
                and any(row.get('kind') == 'end' for row in events)
                and not any(row.get('kind') == 'observation_error' for row in events)
                and [row.get('seq') for row in events] == list(range(1, len(events) + 1))
                and not warnings)
    meta = read('run.json', {})
    if not meta:
        try:
            args = (root / 'run.args').read_text().splitlines()
            meta = {'case': args[0], 'backend': args[1], 'maximum': args[2]}
        except (OSError, IndexError):
            pass
    try:
        run_id = (root / 'run-id').read_text().strip()
    except OSError:
        run_id = root.name
    data = {'run_id': meta.get('id') or run_id, 'result': read('result.json', {}), 'process': read('agent/process.json', {}),
            'summary': read('simulator/summary.json', {}), 'run': meta,
            'transcript': read('simulator/transcript.json', {}), 'requests': read('simulator/requests.json', {}),
            'record': read('simulator/record.json', {}), 'models': lines('simulator/model-calls.jsonl'),
            'trace': {'status': 'complete' if complete else 'incomplete' if events else 'not_collected', 'events': events},
            'logs': {'runner': tail('runner.log'), 'stderr': tail('agent/stderr.log'), 'stdout': tail('agent/stdout.log')},
            'warnings': warnings}
    data['inspection'] = inspect_run(data)
    structural = {'call_boundaries', 'node_boundaries', 'sdk_boundaries', 'state_reconstruction', 'recorded_values'}
    if events and any(c['status'] == 'fail' and c['id'] in structural for c in data['inspection']['checks']):
        data['trace']['status'] = 'incomplete'
    return data


def render(root):
    root = Path(root)
    data = collect(root)
    inspection = root / 'inspection.json'
    inspection.with_suffix('.json.tmp').write_text(json.dumps(data['inspection'], ensure_ascii=False, indent=2) + '\n')
    inspection.with_suffix('.json.tmp').replace(inspection)
    # Keep untrusted patient/model strings inside inert JSON, including on file://.
    packed = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c').replace('&', '\\u0026')
    html = '''<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Ontoward · 진료 과정 리포트</title>
<style>@@CSS@@</style></head><body class="report-page">
<header class="report-heading"><div><h1>진료 내부 흐름</h1><p id="report-meta" class="muted"></p><p id="report-outcome" class="error-text small" role="status" hidden></p></div><div class="report-tools"><span id="trace-status" class="badge"></span><a href="inspection.json" download>검증 JSON</a></div></header>
<section id="summary" class="metrics" aria-label="실행 요약"></section>
<div class="report-layout"><aside class="timeline-panel"><label for="session-filter">내부 세션</label><select id="session-filter"><option value="">전체 세션</option></select><label class="turn-picker-label" for="turn-picker">관측 턴</label><select id="turn-picker" class="turn-picker"></select><nav id="timeline" aria-label="세션과 턴"></nav></aside>
<div class="report-content"><details class="final-record" open><summary>최종 결과 · SOAP · 수신 확인</summary><div id="final-record"></div></details>
<main id="turn-detail" aria-live="polite"></main>
<details class="all-logs"><summary>실행 로그 · 수집 상태</summary><div id="all-logs"></div></details>
</div></div>
<script type="application/json" id="report-data">@@DATA@@</script><script>@@JS@@</script></body></html>'''
    scripts = (UI / 'viewer.js').read_text() + '\n' + (UI / 'flow.js').read_text()
    html = html.replace('@@CSS@@', (UI / 'style.css').read_text()).replace('@@JS@@', scripts).replace('@@DATA@@', packed)
    target = root / 'report.html'
    temporary = target.with_suffix('.html.tmp')
    temporary.write_text(html, encoding='utf-8')
    temporary.replace(target)
    return data
