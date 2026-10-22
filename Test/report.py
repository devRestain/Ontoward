import json
from pathlib import Path
import sys

from viewer import collect, render


def report(root):
    root = Path(root)
    missing = []
    def read(name, fallback):
        path = root / name
        if not path.exists():
            missing.append(name)
            return fallback
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            missing.append(name + ':unreadable')
            return fallback
    summary = read('simulator/summary.json', {'status': 'unknown', 'receipt': None, 'ready': False,
                   'doctor_successes': 0, 'turns': 0, 'backend': 'unknown', 'case_id': 'unknown',
                   'doctor_calls': 0, 'model_requests': 0, 'input_tokens': 0, 'output_tokens': 0})
    process = read('agent/process.json', {'exit_code': None, 'development_key_present': None,
                   'samples_visible': None, 'sandbox': {}})
    sandbox = process['sandbox']
    checks = {'agent_exit_zero': process['exit_code'] == 0,
              'confirmed_submission': summary['status'] == 'completed' and (summary['receipt'] or {}).get('status') == 'completed',
              'ready_handshake': summary['ready'], 'nonempty_gateway_response': summary['doctor_successes'] > 0,
              'within_turn_limit': summary['turns'] <= 50,
              'within_model_limits': summary['doctor_calls'] <= 200 and summary['input_tokens'] <= 500000
                  and summary['output_tokens'] <= 100000,
              'no_development_key_in_agent': process['development_key_present'] is False,
              'no_samples_in_agent': process['samples_visible'] is False,
              'root_read_only': sandbox.get('root_read_only') is True,
              'submission_read_only': sandbox.get('submission_read_only') is True,
              'output_writable': sandbox.get('output_writable') is True}
    if 'openai_key_present' in process or summary['backend'] == 'openai_api':
        checks['no_openai_key_in_agent'] = process.get('openai_key_present') is False
    result = {'status': 'pass' if all(checks.values()) else 'fail', 'backend': summary['backend'],
              'case_id': summary['case_id'], 'turns': summary['turns'], 'doctor_calls': summary['doctor_calls'],
              'nonempty_gateway_responses': summary['doctor_successes'],
              'sandbox': sandbox, 'missing_evidence': missing,
              'model_requests': summary['model_requests'], 'checks': checks, 'score_status': 'not_scored',
              'actual_nova': 'run' if summary['backend'] == 'nova' and summary['model_requests'] else 'not_run',
              'actual_openai_api': 'run' if summary['backend'] == 'openai_api' and summary['model_requests'] else 'not_run',
              'provider_model': summary.get('provider_model'),
              'official_submission': 'not_run', 'clinical_accuracy': 'not_evaluated'}
    observed = collect(root)
    result['trace_status'] = observed['trace']['status']
    result['outcome'] = observed['inspection']['outcome']
    (root / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    render(root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(report(sys.argv[1] if len(sys.argv) > 1 else '/output'))
