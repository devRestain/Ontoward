from __future__ import annotations

import json
from pathlib import Path
import shutil
import sqlite3
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from Dev.ontology.patient_text import NovaDevClient, bounded_schema, freeze, run
from Dev.ontology.korean import validate
from Dev.ontology.v5 import write


def main():
    checks = []
    def require(condition, name):
        if not condition:
            raise AssertionError(name)
        checks.append(name)

    def fails(callback, name):
        try:
            callback()
        except (ValueError, RuntimeError):
            checks.append(name)
        else:
            raise AssertionError(name)

    class Fake:
        identity = {'mode':'scripted_offline'}
        def __init__(self, failure=None):
            self.calls, self.failure = [], failure
        def chat(self, messages, **settings):
            self.calls.append(settings)
            packets = json.loads(messages[-1]['content'])['items']
            review = 'text' not in settings['output_schema']['properties']['items']['items']['properties']
            if self.failure == 'unknown':
                raise TimeoutError('scripted unknown outcome')
            items = []
            for packet in packets:
                item = {'job_id':packet['job_id'], 'decision':'reject' if review and self.failure == 'semantic' else
                        'accept' if review else 'candidate', 'reason':'scripted offline fixture'}
                if not review:
                    item['text'] = '가' * 31 if self.failure == 'length' else '합성 질문인가요?'
                items.append(item)
            return {'choices':[{'message':{'content':json.dumps({'items':items}, ensure_ascii=False)}}]}

    scratch = ROOT / 'Tmp/d21-verification'
    scratch.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='d21-offline-', dir=ROOT / 'data/preparation/v5') as name:
        directory = Path(name)
        workset_path = directory / 'workset.json'
        frozen = freeze(ROOT / 'data/preparation/v5/competition-graph-2026-10-16', workset_path, provider='nova_dev_key')
        workset = json.loads(workset_path.read_text())
        require(frozen['label_jobs'] == 0 and all(job['action'] in {'SAY', 'EXAM'} for job in workset['jobs']),
                'generate_only_patient_reachable_actions_without_internal_label_jobs')
        require(frozen['by_purpose']['context'] == 243 and frozen['by_purpose']['examination'] == 1,
                'include_actual_admitted_context_and_examination_consumers')
        require(len(workset['exclusions']) == 15, 'preserve_diagnosis_qualified_target_exclusions')
        require(all(job['source_proof_sha256'] for job in workset['jobs']), 'bind_every_action_to_source_proofs')
        representative = [next(job for job in workset['jobs'] if job['purpose'] == purpose)
                          for purpose in ('presence', 'attribute', 'context', 'examination')]
        workset.update(jobs=representative, max_calls=2)
        write(workset_path, workset)
        accepted = Fake()
        result = run(workset_path, directory / 'complete', client=accepted)
        require(result['status'] == 'complete' and len(accepted.calls) == 2 and result['accepted_jobs'] == 4,
                'require_separate_generation_and_semantic_comparison_before_acceptance')
        require((directory / 'complete/questions.ko.json').is_file() and
                (directory / 'complete/exam-requests.ko.json').is_file(), 'export_runtime_compatible_say_and_exam_assets')
        require(all(call['model'] == 'gpt-6-luna' for call in accepted.calls), 'preserve_requested_model_for_both_stages')
        write(directory / 'complete/verification.json', {'status':'pass', 'accepted_jobs':4})
        remaining = freeze(ROOT / 'data/preparation/v5/competition-graph-2026-10-16',
                           directory / 'remaining.json', provider='nova_dev_key', exclude_accepted=directory / 'complete')
        remainder = json.loads((directory / 'remaining.json').read_text())
        require(remaining['jobs'] == frozen['jobs'] - 4 and remaining['previously_accepted_jobs'] == 4
                and not {job['job_id'] for job in representative} & {job['job_id'] for job in remainder['jobs']},
                'exclude_only_previously_reviewed_actions_from_new_model_requests')
        fails(lambda:run(workset_path, directory / 'complete', client=accepted), 'forbid_automatic_resume_and_retransmission')
        for mode, expected_calls in (('length', 1), ('semantic', 2), ('unknown', 1)):
            client = Fake(mode)
            result = run(workset_path, directory / mode, client=client)
            require(result['status'] == 'blocked' and result['accepted_jobs'] == 0 and len(client.calls) == expected_calls,
                    mode + '_failure_stops_the_entire_batch_without_retry')
            require(not (directory / mode / 'questions.ko.json').exists(), mode + '_failure_cannot_export_complete_assets')
            with sqlite3.connect(directory / mode / 'requests.sqlite3') as ledger:
                require(ledger.execute("SELECT COUNT(*) FROM calls WHERE state='failed_or_unknown'").fetchone()[0] == 1,
                        mode + '_failure_preserves_reserved_request_identity')
        resumed_workset = {**workset, 'continue_on_failure':True, 'max_calls':4}
        write(directory / 'resumed-workset.json', resumed_workset)
        class OnceRejected(Fake):
            def chat(self, messages, **settings):
                self.failure = 'semantic' if len(self.calls) < 2 else None
                response = super().chat(messages, **settings)
                if len(self.calls) == 2:
                    body = json.loads(response['choices'][0]['message']['content'])
                    for item in body['items']:
                        item['reason'] = 'Changes iodine deficiency to insufficient iodine intake.'
                    response['choices'][0]['message']['content'] = json.dumps(body)
                return response
        resumed = run(directory / 'resumed-workset.json', directory / 'resumed', client=OnceRejected())
        require(resumed['status'] == 'complete' and resumed['calls_total'] == 4
                and resumed['authorized_failure_resumptions'] == 1,
                'resume_a_failed_batch_only_under_explicit_frozen_authorization')
        require(resumed['failure'] is None, 'never_classify_semantic_insufficient_wording_as_a_service_quota')
        exhausted = run(directory / 'resumed-workset.json', directory / 'bounded-recovery', client=Fake('semantic'))
        require(exhausted['status'] == 'blocked' and exhausted['calls_total'] == 4,
                'stop_authorized_resumptions_at_the_frozen_request_ceiling')
        class Quota(Fake):
            def chat(self, messages, **settings):
                self.calls.append(settings)
                raise RuntimeError('MODEL_CALL_LIMIT')
        quota = run(directory / 'resumed-workset.json', directory / 'quota', client=Quota())
        require(quota['status'] == 'blocked' and quota['calls_total'] == 1,
                'stop_at_nova_call_limit_without_switching_provider')
        job = representative[0]
        item = {'job_id':job['job_id'], 'decision':'candidate', 'text':'가' * 30, 'reason':'boundary fixture'}
        require(validate({'items':[item]}, [job])[job['job_id']]['text'] == item['text'], 'accept_exactly_30_nfc_codepoints')
        for value in ('가' * 31, '가?', '증상\r인가요?', '증상\n인가요?', ' '):
            fails(lambda value=value:validate({'items':[{**item, 'text':value}]}, [job]), 'reject_invalid_text_' + str(len(checks)))
        fails(lambda:validate({'items':[item, item]}, [job]), 'reject_duplicate_identifiers')
        fails(lambda:validate({'items':[]}, [job]), 'reject_partial_whole_response')
        changed = dict(workset)
        changed['max_calls'] = 3
        write(directory / 'changed.json', changed)
        fails(lambda:run(directory / 'changed.json', directory / 'changed-output', client=Fake()), 'reject_modified_call_ceiling_before_transport')
        for path in directory.iterdir():
            if path.is_dir():
                shutil.copytree(path, scratch / path.name, dirs_exist_ok=True)
        captured = {}
        class NovaTransport:
            def chat(self, **request):
                captured.update(request)
                alias = json.loads(request['messages'][-1]['content'])['items'][0]['job_id']
                content = {'items':[{'job_id':alias, 'decision':'candidate', 'text':'합성 질문인가요?', 'reason':'scripted'}]}
                return {'choices':[{'finish_reason':'stop', 'message':{'content':json.dumps(content)}}]}
        nova = NovaDevClient.__new__(NovaDevClient)
        nova.client, nova.identity = NovaTransport(), {'mode':'scripted_offline'}
        bound = nova.chat([{'role':'system','content':'fixture'},
                          {'role':'user','content':json.dumps({'items':[{'job_id':job['job_id']}]})}],
                         model='gpt-6-luna', request_id='fixture',
                         output_schema=bounded_schema([job]), audit_directory=directory / 'nova-transport')
        require(captured['max_tokens'] == 8000 and captured['model'] == 'openai/gpt-6-luna'
                and captured['reasoning_effort'] == 'medium' and 'session_id' not in captured,
                'use_documented_nova_luna_ceiling_and_session_free_medium_route')
        require(json.loads(captured['messages'][-1]['content'])['items'][0]['job_id'] == 'J01'
                and json.loads(bound['choices'][0]['message']['content'])['items'][0]['job_id'] == job['job_id'],
                'bind_short_wire_ids_to_exact_canonical_jobs_without_text_repair')
    report = {'status':'pass', 'check_count':len(checks), 'checks':checks, 'real_model_calls':0}
    write(scratch / 'verification.json', report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
