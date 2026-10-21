import fcntl
import json
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path

from .models import Result, canonical, digest


def recover_patch(work, source_run_id, identity, boundary=lambda: None):
    """Fork only the settled oversized first patch request, preserving immutable source custody."""
    work=Path(work);source=work/source_run_id;run_id=digest(identity)[:32];target=work/run_id
    if source_run_id==run_id or target.exists():raise ValueError('recovery_target_exists_use_resume')
    if not (source/'jobs.sqlite3').is_file():raise ValueError('recovery_source_not_found')
    with (source/'.worker.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        wal=source/'jobs.sqlite3-wal'
        if wal.exists() and wal.stat().st_size:raise ValueError('recovery_requires_closed_checkpoint')
        db=sqlite3.connect((source/'jobs.sqlite3').as_uri()+'?mode=ro&immutable=1',uri=True)
        db.row_factory=sqlite3.Row;staging=None
        try:
            meta={r['key']:json.loads(r['value']) for r in db.execute('SELECT * FROM meta')};old=meta['identity']
            if digest(old)[:32]!=source_run_id:raise ValueError('recovery_source_fingerprint_mismatch')
            for key in ('contract','inputs','config','schema','runtime_contract','guideline_catalog'):
                if old.get(key)!=identity.get(key):raise ValueError('recovery_identity_mismatch:'+key)
            config=old['config']
            if (meta.get('state')!='failed' or meta.get('phase')!='patch' or meta.get('error')!='string_above_max_length' or
                config['provider']!='openai_api' or config['models']!={'draft':'gpt-6-luna','final':'gpt-6-luna'} or
                config['effort']!='medium' or config['batch_size']!=40):raise ValueError('recovery_requires_oversized_api_patch')
            changed={k for k in old['generator'].keys()|identity['generator'].keys() if old['generator'].get(k)!=identity['generator'].get(k)}
            if 'build.py' not in changed or changed-{'build.py','recovery.py','__main__.py'}:raise ValueError('recovery_unrelated_generator_changed')
            if any(old['prompts'].get(k)!=identity['prompts'].get(k) for k in old['prompts'].keys()|identity['prompts'].keys() if k!='patch.txt'):
                raise ValueError('recovery_unrelated_prompt_changed')
            if not old['inputs'] or not all(meta.get('indexed:'+canonical([e['relative_path'],e.get('member')])) for e in old['inputs']):
                raise ValueError('recovery_requires_complete_raw_index')
            if not all(meta.get(key+'_frozen') for key in ('normalize','questions','draft','final','conflict','patch')):
                raise ValueError('recovery_requires_frozen_patch')
            rows=[dict(r) for r in db.execute('SELECT job_id,phase,status,attempt_count FROM jobs')]
            if (not any(r['phase']=='patch' for r in rows) or any(r['phase'] not in {'normalize','questions','draft','final','conflict','patch'} or
                r['phase']!='patch' and r['status']!='done' or r['phase']=='patch' and (r['status']=='done' or r['attempt_count']>=6) for r in rows)):
                raise ValueError('recovery_requires_completed_prior_phases')
            if db.execute("SELECT 1 FROM requests WHERE state NOT IN ('accepted','failed','superseded') LIMIT 1").fetchone():
                raise ValueError('recovery_requires_settled_requests')
            last=db.execute("SELECT request_id,state,error,job_ids,response,length(json_extract(payload,'$.body.input[1].content')) AS characters FROM requests ORDER BY rowid DESC LIMIT 1").fetchone()
            if (not last or last['state']!='failed' or last['error']!='string_above_max_length' or last['response'] is not None or
                not last['characters'] or last['characters']<=50000 or
                any(not any(r['job_id']==ident and r['phase']=='patch' and r['status']=='running' for r in rows) for ident in json.loads(last['job_ids']))):
                raise ValueError('recovery_requires_confirmed_patch_rejection')
            from .build import patch_messages
            batch=db.execute("SELECT job_id,normalized_input,error FROM jobs WHERE phase='patch' ORDER BY job_id LIMIT ?",(config['batch_size'],)).fetchall()
            messages=patch_messages([dict(job_id=r['job_id'],input=json.loads(r['normalized_input']),validation_error=r['error']) for r in batch])
            receipt=dict(contract='patch-shared-recovery-1',source_run_id=source_run_id,run_id=run_id,
                source_identity=digest(old),target_identity=digest(identity),phase='patch',failed_request_id=last['request_id'],
                rejected_characters=last['characters'],maximum_message_characters=max(len(m['content']) for m in messages),
                completed_by_phase={p:sum(r['phase']==p and r['status']=='done' for r in rows) for p in ('normalize','questions','draft','final','conflict')},
                jobs_pending=sum(r['phase']=='patch' for r in rows),model_calls_started=0,counters_reset=0)
            boundary();stage_root=work/'.recovery-staging';stage_root.mkdir(exist_ok=True)
            staging=Path(tempfile.mkdtemp(prefix='.patch-'+run_id+'-',dir=stage_root))
            print(canonical(dict(event='patch_recovery_copy_started',**receipt)),flush=True)
            copy=sqlite3.connect(staging/'jobs.sqlite3')
            try:
                db.backup(copy,pages=4096,progress=lambda *args:boundary());copy.execute('PRAGMA journal_mode=DELETE')
                with copy:
                    copy.execute("UPDATE jobs SET status='pending' WHERE phase='patch' AND status='running'")
                    values=dict(identity=identity,state='ready',phase='patch',error=None,pause_requested=False,updated_at=time.time(),
                        recovery=receipt,recovery_source_identity=old,recovery_history=meta.get('recovery_history',[])+
                        ([dict(recovery=meta['recovery'],source_identity=meta.get('recovery_source_identity'))] if meta.get('recovery') else []))
                    copy.executemany('INSERT OR REPLACE INTO meta VALUES(?,?)',[(k,canonical(v)) for k,v in values.items()])
            finally:copy.close()
            boundary()
            if target.exists():raise ValueError('recovery_target_exists_use_resume')
            staging.rename(target);staging=None
            return dict(event='patch_recovered',state='ready',**receipt)
        finally:
            db.close()
            if staging is not None:shutil.rmtree(staging)


def recover_draft(work, source_run_id, identity, boundary=lambda: None, switch_provider=False, repair_endpoints=False, repair_packets=False):
    if sum((switch_provider,repair_endpoints,repair_packets))>1:raise ValueError('choose_one_draft_recovery')
    partial=repair_endpoints or repair_packets
    work=Path(work);source=work/source_run_id;run_id=digest(identity)[:32];target=work/run_id
    if source_run_id==run_id or target.exists():raise ValueError('recovery_target_exists_use_resume')
    if not (source/'jobs.sqlite3').is_file():raise ValueError('recovery_source_not_found')
    with (source/'.worker.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        wal=source/'jobs.sqlite3-wal'
        if wal.exists() and wal.stat().st_size:raise ValueError('recovery_requires_closed_checkpoint')
        db=sqlite3.connect((source/'jobs.sqlite3').as_uri()+'?mode=ro&immutable=1',uri=True)
        db.row_factory=sqlite3.Row;staging=None
        try:
            meta={r['key']:json.loads(r['value']) for r in db.execute('SELECT * FROM meta')};old=meta['identity']
            if digest(old)[:32]!=source_run_id:raise ValueError('recovery_source_fingerprint_mismatch')
            for key in ('contract','inputs','schema','runtime_contract','guideline_catalog'):
                if old.get(key)!=identity.get(key):raise ValueError('recovery_identity_mismatch:'+key)
            if switch_provider:
                expected=json.loads(canonical(old['config']));expected.pop('api_base',None)
                expected['provider']=identity['config']['provider']
                if expected['provider']=='openai_api':expected['models']={'draft':'gpt-6-luna','final':'gpt-6-luna'}
                selected_models={'draft':'gpt-6-luna','final':'gpt-6-luna'} if expected['provider']=='openai_api' else {'draft':'gpt-6.1-sol','final':'gpt-6.1-sol'}
                if (old['config']['provider']!='nova_dev' or expected['provider'] not in {'openai_api','codex_subscription'} or
                    old['config']['models']!={'draft':'gpt-6.1-sol','final':'gpt-6.1-sol'} or
                    expected!=identity['config'] or expected['models']!=selected_models or
                    expected['effort']!='medium' or expected['batch_size']!=40 or
                    expected['max_tokens']!={'draft':32000,'final':32000}):
                    raise ValueError('recovery_requires_explicit_provider_profile')
            elif old['config']!=identity['config']:raise ValueError('recovery_identity_mismatch:config')
            if repair_packets:
                if (meta.get('state')!='failed' or meta.get('phase')!='draft' or
                    meta.get('error')!='draft_packet_item_too_large:jobs' or
                    old['config']['provider']!='openai_api' or old['config']['models']!={'draft':'gpt-6-luna','final':'gpt-6-luna'}):
                    raise ValueError('recovery_requires_local_job_packet_failure')
            elif repair_endpoints:
                if (switch_provider or meta.get('state')!='paused' or meta.get('phase')!='draft' or
                    old['config']['provider']!='openai_api' or old['config']['models']!={'draft':'gpt-6-luna','final':'gpt-6-luna'}):
                    raise ValueError('recovery_requires_paused_api_draft_validation')
            elif (meta.get('state')!='failed' or meta.get('phase')!='draft' or
                meta.get('error')!=('INVALID_REQUEST_BODY' if switch_provider else 'INVALID_API_RESPONSE') or
                not switch_provider and identity['config']['provider']!='nova_dev'):
                raise ValueError('recovery_requires_oversized_nova_draft_failure')
            if not all(meta.get(key) for key in ('normalize_frozen','questions_frozen','draft_frozen')):
                raise ValueError('recovery_requires_frozen_draft')
            if not old['inputs'] or not all(meta.get('indexed:'+canonical([e['relative_path'],e.get('member')])) for e in old['inputs']):
                raise ValueError('recovery_requires_complete_raw_index')
            changed={key for key in old['generator'].keys()|identity['generator'].keys() if old['generator'].get(key)!=identity['generator'].get(key)}
            prompt_correction=(repair_endpoints and meta.get('recovery',{}).get('contract')=='draft-endpoint-recovery-1' and
                old['prompts'].get('draft.txt')!=identity['prompts'].get('draft.txt') and not changed-{'build.py','recovery.py','__main__.py'})
            if (not switch_provider and not prompt_correction and 'build.py' not in changed or changed-({'recovery.py','__main__.py'} if switch_provider else {'build.py','recovery.py','__main__.py'})):
                raise ValueError('recovery_not_a_draft_packet_change')
            if any(old['prompts'].get(key)!=identity['prompts'].get(key) for key in old['prompts'].keys()|identity['prompts'].keys() if switch_provider or key!='draft.txt'):
                raise ValueError('recovery_unrelated_prompt_changed')
            rows=[dict(r) for r in db.execute('SELECT job_id,phase,status,attempt_count FROM jobs')]
            if (any(r['phase'] not in {'normalize','questions','draft'} or r['phase']!='draft' and r['status']!='done' or
                r['phase']=='draft' and (not partial and r['status']=='done' or r['status']!='done' and r['attempt_count']>=6) for r in rows) or
                not any(r['phase']=='draft' for r in rows)):
                raise ValueError('recovery_requires_zero_accepted_drafts')
            if repair_endpoints and not prompt_correction and not db.execute("SELECT 1 FROM jobs WHERE phase='draft' AND status!='done' AND error LIKE 'invalid_relation_endpoint%' LIMIT 1").fetchone():
                raise ValueError('recovery_requires_diagnosed_endpoint_failure')
            requests=[dict(r) for r in db.execute('SELECT rowid,* FROM requests ORDER BY rowid')]
            last=requests[-1] if requests else {}
            # The diagnosed first draft exceeded the gateway body limit. Do not reinterpret small or unknown responses.
            if partial:
                if last.get('state')!='accepted' or not last.get('response'):
                    raise ValueError('recovery_requires_settled_draft_response')
            elif (last.get('state')!='failed' or last.get('error')!=('INVALID_REQUEST_BODY' if switch_provider else 'INVALID_API_RESPONSE') or
                last.get('response') is not None or not switch_provider and len(last.get('payload','').encode())<=100_000_000):
                raise ValueError('recovery_requires_oversized_settled_request')
            ids=json.loads(last['job_ids']);by_id={r['job_id']:r for r in rows}
            if not ids or any(by_id[i]['phase']!='draft' for i in ids):raise ValueError('recovery_requires_draft_request')
            from .build import draft_catalog
            draft_catalog([dict(job_id=i,input=json.loads(db.execute('SELECT normalized_input FROM jobs WHERE job_id=?',(i,)).fetchone()[0])) for i in ids])
            confirmed={'PROVIDER_RESPONSE_INVALID','nova_daily_quota','CONTEXT_LIMIT_EXCEEDED','INVALID_REQUEST_BODY'}
            if any(r['provider'] not in ({'nova_dev','openai_api'} if partial else {'nova_dev'}) or not (r['state']=='accepted' and r['response'] or
                r['state']=='failed' and r['provider']=='nova_dev' and r['response'] is None and (r['error'] in confirmed or
                    r['error']=='INVALID_API_RESPONSE' and len(r['payload'].encode())>100_000_000)) for r in requests):
                raise ValueError('recovery_requires_settled_requests')
            usage=[dict(r) for r in db.execute('SELECT * FROM usage ORDER BY day,model')]
            if sum(r['calls'] for r in usage)!=sum(r['state']=='accepted' for r in requests):raise ValueError('recovery_usage_not_reconciled')
            oversized=[]
            if repair_packets:
                from .build import draft_messages
                batch=[dict(job_id=r['job_id'],input=json.loads(r['normalized_input']),validation_error=r['error']) for r in db.execute(
                    "SELECT job_id,normalized_input,error FROM jobs WHERE phase='draft' AND status!='done' ORDER BY job_id LIMIT ?",(identity['config']['batch_size'],))]
                _,handles=draft_catalog(batch)
                for job in batch:
                    source_input={k:v for k,v in job['input'].items() if k not in {'available_targets','attributes_and_values'}}
                    source_input['disease']=handles[source_input['disease']['id']]
                    size=len(canonical(dict(phase='draft',wire_contract='draft-shared-1',jobs=[dict(job,input=source_input)])))
                    if size>50000:oversized.append(dict(job_id=job['job_id'],characters=size))
                if not oversized:raise ValueError('recovery_requires_reproduced_oversized_job')
                draft_messages(batch)
            receipt=dict(contract='draft-job-packet-recovery-1' if repair_packets else 'draft-endpoint-recovery-1' if repair_endpoints else 'draft-provider-switch-1' if switch_provider else 'draft-shared-recovery-1',source_run_id=source_run_id,run_id=run_id,
                source_identity=digest(old),target_identity=digest(identity),phase='draft',
                reason='split_oversized_job_source_records_within_one_request' if repair_packets else 'typed_draft_reference_constraints_preserve_accepted_results' if repair_endpoints else 'explicit_provider_switch_after_confirmed_nova_rejection' if switch_provider else 'share_compact_vocabulary_after_oversized_gateway_rejection',
                source_provider=old['config']['provider'],target_provider=identity['config']['provider'],
                source_models=old['config']['models'],target_models=identity['config']['models'],
                completed_by_phase={p:sum(r['phase']==p and r['status']=='done' for r in rows) for p in (('normalize','questions','draft') if partial else ('normalize','questions'))},
                jobs_pending=sum(r['phase']=='draft' and r['status']!='done' for r in rows),requests_preserved=len(requests),
                usage_preserved=usage,counters_reset=0,model_calls_started=0,failed_request_id=last['request_id'])
            if repair_packets:
                receipt.pop('failed_request_id')
                receipt.update(local_error=meta['error'],oversized_jobs=oversized)
            boundary();stage_root=work/'.recovery-staging';stage_root.mkdir(exist_ok=True)
            staging=Path(tempfile.mkdtemp(prefix='.draft-'+run_id+'-',dir=stage_root))
            print(canonical(dict(event='draft_recovery_copy_started',run_id=run_id,source_run_id=source_run_id)),flush=True)
            copy=sqlite3.connect(staging/'jobs.sqlite3')
            try:
                db.backup(copy,pages=4096,progress=lambda *args:boundary());copy.execute('PRAGMA journal_mode=DELETE')
                with copy:
                    copy.execute("UPDATE jobs SET status='pending' WHERE phase='draft' AND status='running'")
                    values=dict(identity=identity,state='ready',phase='draft',error=None,pause_requested=False,updated_at=time.time(),
                        recovery=receipt,recovery_source_identity=old,recovery_history=meta.get('recovery_history',[])+
                        ([dict(recovery=meta['recovery'],source_identity=meta.get('recovery_source_identity'))] if meta.get('recovery') else []))
                    copy.executemany('INSERT OR REPLACE INTO meta VALUES(?,?)',[(k,canonical(v)) for k,v in values.items()])
            finally:copy.close()
            boundary()
            if target.exists():raise ValueError('recovery_target_exists_use_resume')
            staging.rename(target);staging=None
            return dict(event='draft_recovered',state='ready',**receipt)
        finally:
            db.close()
            if staging is not None:shutil.rmtree(staging)


def recover_questions(work, source_run_id, identity, boundary=lambda: None, switch_sol=False):
    work=Path(work);source=work/source_run_id;run_id=digest(identity)[:32];target=work/run_id
    if source_run_id==run_id or target.exists(): raise ValueError('recovery_target_exists_use_resume')
    if not (source/'jobs.sqlite3').is_file(): raise ValueError('recovery_source_not_found')
    with (source/'.worker.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as error:raise RuntimeError('worker_already_running') from error
        wal=source/'jobs.sqlite3-wal'
        if wal.exists() and wal.stat().st_size:raise ValueError('recovery_requires_closed_checkpoint')
        db=sqlite3.connect((source/'jobs.sqlite3').as_uri()+'?mode=ro&immutable=1',uri=True)
        db.row_factory=sqlite3.Row;staging=None
        try:
            meta={row['key']:json.loads(row['value']) for row in db.execute('SELECT * FROM meta')}
            previous=meta['identity']
            if digest(previous)[:32]!=source_run_id:raise ValueError('recovery_source_fingerprint_mismatch')
            for key in ('contract','inputs','schema','runtime_contract','guideline_catalog'):
                if previous.get(key)!=identity.get(key):raise ValueError('recovery_identity_mismatch:'+key)
            expected=json.loads(canonical(previous['config']))
            sol_input_repair=(switch_sol and expected['models']=={'draft':'gpt-6.1-sol','final':'gpt-6.1-sol'} and
                expected['batch_size']==40 and meta.get('state')=='failed' and meta.get('error')=='INVALID_REQUEST_BODY' and
                previous['generator'].get('build.py')!=identity['generator'].get('build.py'))
            luna_source=expected['models']=={'draft':'gpt-6-luna','final':'gpt-6.1-sol'} and expected['batch_size']==10
            if expected['provider']!='nova_dev' or expected['effort']!='medium' or not (luna_source or sol_input_repair):
                raise ValueError('recovery_requires_luna_source')
            if switch_sol and luna_source:
                expected['models']['draft']='gpt-6.1-sol';expected['max_tokens']['draft']=32000
                expected['batch_size']=40;expected['nova_daily_calls']['draft']=100
            if expected!=identity['config']:raise ValueError('recovery_requires_explicit_sol_profile')
            for name in previous['prompts'].keys()|identity['prompts'].keys():
                if name!='questions.txt' and previous['prompts'].get(name)!=identity['prompts'].get(name):
                    raise ValueError('recovery_unrelated_prompt_changed:'+name)
            changed={name for name in previous['generator'].keys()|identity['generator'].keys()
                if previous['generator'].get(name)!=identity['generator'].get(name)}
            if changed-{'build.py','recovery.py','__main__.py'}:raise ValueError('recovery_clinical_generator_changed')
            failed_errors={'PROVIDER_RESPONSE_INVALID','nova_daily_quota'}
            source_errors={'persistent_provider_failure:PROVIDER_RESPONSE_INVALID',
                'persistent_provider_failure:nova_daily_quota','nova_daily_quota'}
            if switch_sol:
                failed_errors.add('CONTEXT_LIMIT_EXCEEDED')
                source_errors.add('CONTEXT_LIMIT_EXCEEDED')
            if sol_input_repair:
                failed_errors.add('INVALID_REQUEST_BODY')
                source_errors.add('INVALID_REQUEST_BODY')
            valid_failure=meta.get('state')=='failed' and meta.get('error') in source_errors
            if meta.get('phase')!='questions' or not meta.get('questions_frozen') or not meta.get('normalize_frozen'):
                raise ValueError('recovery_requires_frozen_questions')
            if not previous['inputs'] or not all(meta.get('indexed:'+canonical([entry['relative_path'],entry.get('member')])) for entry in previous['inputs']):
                raise ValueError('recovery_requires_complete_raw_index')
            rows=[dict(row) for row in db.execute('SELECT * FROM jobs')]
            if (not rows or any(row['phase'] not in {'normalize','questions'} for row in rows) or
                any(row['phase']=='normalize' and row['status']!='done' for row in rows) or
                any(row['status']!='done' and row['attempt_count']>=6 for row in rows)):
                raise ValueError('recovery_requires_completed_normalization_and_unexhausted_questions')
            requests=[dict(row) for row in db.execute('SELECT rowid,* FROM requests ORDER BY rowid')]
            if not requests or any(not (row['provider']=='nova_dev' and (
                row['state']=='accepted' and row['response'] or row['state']=='failed' and row['response'] is None and
                row['error'] in failed_errors)) for row in requests):
                raise ValueError('recovery_requires_settled_requests')
            last=requests[-1]
            truncated=(meta.get('state')=='paused' and last['state']=='accepted' and
                json.loads(last['response']).get('finish_reason')=='length' and
                all(next(row for row in rows if row['job_id']==ident)['status']!='done' for ident in json.loads(last['job_ids'])))
            if not (valid_failure or truncated or switch_sol and meta.get('state')=='paused'):
                raise ValueError('recovery_requires_failed_or_truncated_luna_questions')
            usage=[dict(row) for row in db.execute('SELECT * FROM usage ORDER BY day,model')]
            if sum(row['calls'] for row in usage)!=sum(row['state']=='accepted' for row in requests):
                raise ValueError('recovery_usage_not_reconciled')
            receipt=dict(contract='questions-output-recovery-1',source_run_id=source_run_id,run_id=run_id,
                source_identity=digest(previous),target_identity=digest(identity),phase='questions',
                reason='compact_sol_question_input_preserve_fixed_batch' if sol_input_repair else
                    'user_selected_sol_medium_larger_fixed_batches' if switch_sol else 'compact_question_output_keep_luna_medium',
                completed_by_phase={phase:sum(row['phase']==phase and row['status']=='done' for row in rows) for phase in ('normalize','questions')},
                jobs_pending=sum(row['status']!='done' for row in rows),requests_preserved=len(requests),
                usage_preserved=usage,counters_reset=0,model_calls_started=0,
                question_prompt_changed=previous['prompts']['questions.txt']!=identity['prompts']['questions.txt'])
            boundary();stage_root=work/'.recovery-staging';stage_root.mkdir(exist_ok=True)
            staging=Path(tempfile.mkdtemp(prefix='.questions-'+run_id+'-',dir=stage_root))
            print(canonical(dict(event='questions_recovery_copy_started',source_run_id=source_run_id,run_id=run_id)),flush=True)
            copy=sqlite3.connect(staging/'jobs.sqlite3')
            try:
                db.backup(copy,pages=4096,progress=lambda *args:boundary());copy.execute('PRAGMA journal_mode=DELETE')
                with copy:
                    copy.execute("UPDATE jobs SET status='pending' WHERE phase='questions' AND status='running'")
                    values=dict(identity=identity,state='ready',phase='questions',error=None,pause_requested=False,
                        updated_at=time.time(),recovery=receipt,recovery_source_identity=previous,
                        recovery_history=meta.get('recovery_history',[])+([dict(recovery=meta['recovery'],source_identity=meta.get('recovery_source_identity'))] if meta.get('recovery') else []))
                    copy.executemany('INSERT OR REPLACE INTO meta VALUES(?,?)',[(key,canonical(value)) for key,value in values.items()])
            finally:copy.close()
            boundary()
            if target.exists():raise ValueError('recovery_target_exists_use_resume')
            staging.rename(target);staging=None
            return dict(event='questions_recovered',state='ready',**receipt)
        finally:
            db.close()
            if staging is not None:shutil.rmtree(staging)


def recover_normalization(work, source_run_id, identity, boundary=lambda: None, repair='schema'):
    """Fork a settled normalization checkpoint after a bounded transport or phase-ownership fix."""
    if repair not in {'schema','text','provider','batch','empty'}: raise ValueError('unsupported_normalization_recovery')
    work = Path(work)
    source = work / source_run_id
    run_id = digest(identity)[:32]
    target = work / run_id
    if source_run_id == run_id or target.exists():
        raise ValueError('recovery_target_exists_use_resume')
    if not (source / 'jobs.sqlite3').is_file():
        raise ValueError('recovery_source_not_found')
    with (source / '.worker.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError('worker_already_running') from error
        wal = source / 'jobs.sqlite3-wal'
        if wal.exists() and wal.stat().st_size:
            raise ValueError('recovery_requires_closed_checkpoint')
        db = sqlite3.connect(f'{(source / "jobs.sqlite3").as_uri()}?mode=ro&immutable=1', uri=True)
        db.row_factory = sqlite3.Row
        staging = None
        try:
            meta = {row['key']:json.loads(row['value']) for row in db.execute('SELECT * FROM meta')}
            previous = meta['identity']
            if digest(previous)[:32] != source_run_id:
                raise ValueError('recovery_source_fingerprint_mismatch')
            for key in ('contract','config','inputs','schema','runtime_contract','guideline_catalog'):
                if previous.get(key) != identity.get(key):
                    raise ValueError('recovery_identity_mismatch:'+key)
            for name in ('inputs.py','models.py','normalize.py'):
                if not previous.get('generator',{}).get(name) or previous['generator'][name] != identity['generator'].get(name):
                    raise ValueError('recovery_index_or_semantic_contract_changed:'+name)
            allowed_state=(meta.get('state')=='failed' and meta.get('error')=='output_contract_failed:normalize')
            if repair=='text': allowed_state=allowed_state or meta.get('state')=='paused'
            if repair in {'batch','empty'}:
                if repair=='batch': allowed_state=meta.get('state')=='paused'
                if previous['prompts']!=identity['prompts']:
                    raise ValueError('recovery_'+repair+'_prompts_changed')
                changed={name for name in previous['generator'].keys() | identity['generator'].keys()
                    if previous['generator'].get(name)!=identity['generator'].get(name)}
                if not changed or changed-{'build.py','recovery.py','__main__.py'}:
                    raise ValueError('recovery_not_a_'+repair+'_scheduler_change')
            if repair=='provider':
                allowed_state=meta.get('state')=='failed' and meta.get('error')=='persistent_provider_failure:PROVIDER_RESPONSE_INVALID'
                if previous['prompts']!=identity['prompts']:
                    raise ValueError('recovery_provider_prompts_changed')
            if (identity['config']['provider'] != 'nova_dev' or not allowed_state or
                meta.get('phase') != 'normalize' or not meta.get('normalize_frozen')):
                raise ValueError('recovery_requires_failed_nova_normalization')
            if not previous['inputs'] or not all(meta.get('indexed:'+canonical([entry['relative_path'],entry.get('member')]))
                for entry in previous['inputs']):
                raise ValueError('recovery_requires_complete_raw_index')
            rows = [dict(row) for row in db.execute('SELECT job_id,phase,status,result,attempt_count,error FROM jobs')]
            if not rows or any(row['phase']!='normalize' for row in rows):
                raise ValueError('recovery_requires_normalization_only')
            if repair=='schema' and any(row['status']=='done' or row['result'] is not None for row in rows):
                raise ValueError('recovery_requires_zero_accepted_results')
            if repair=='empty':
                from .build import empty_bodhi_candidate
                exhausted=[row for row in rows if row['status']!='done' and row['attempt_count']>=6]
                if not exhausted or any(row['error']!='missing_generated_concepts' or
                    not empty_bodhi_candidate(json.loads(db.execute('SELECT normalized_input FROM jobs WHERE job_id=?',
                        (row['job_id'],)).fetchone()[0])) for row in exhausted):
                    raise ValueError('recovery_requires_empty_source_exhaustion_only')
            if repair=='text':
                from .build import normalization_result
                for row in rows:
                    if row['status']=='done':
                        Result.model_validate(normalization_result(json.loads(row['result'])))
                    elif row['error']:
                        if row['error']=='invalid_rendered_korean_length_or_normalization': continue
                        prefix='output_validation_failed:'
                        if row['error'].startswith(prefix):
                            errors=json.loads(row['error'][len(prefix):])
                            if errors and all(item['path'].endswith('.question') and item['type']=='value_error' for item in errors): continue
                        raise ValueError('recovery_not_an_action_text_failure:'+row['job_id'])
            requests = [dict(row) for row in db.execute('SELECT * FROM requests')]
            confirmed=[row for row in requests if (repair=='provider' and row['state'] in {'prepared','failed'} or
                repair in {'batch','empty'} and row['state']=='failed') and
                row['provider']=='nova_dev' and row['error']=='PROVIDER_RESPONSE_INVALID' and row['response'] is None]
            confirmed_ids={row['request_id'] for row in confirmed}
            if repair=='provider' and (not confirmed or any(row['error'] for row in rows if row['status']!='done')):
                raise ValueError('recovery_requires_confirmed_provider_failure_only')
            if not requests or any(row['provider'] != 'nova_dev' or row['state'] != 'accepted' or
                not row['response'] for row in requests if row['request_id'] not in confirmed_ids):
                raise ValueError('recovery_requires_settled_requests')
            supplied_schema=any('JSON Schema:\n' in message.get('content','') for row in requests
                for message in json.loads(row['payload']).get('messages',[]))
            if repair=='schema' and supplied_schema:
                raise ValueError('recovery_not_a_missing_schema_failure')
            if repair=='text' and not supplied_schema:
                raise ValueError('recovery_requires_schema_delivered_checkpoint')
            usage = [dict(row) for row in db.execute('SELECT * FROM usage')]
            if sum(row['calls'] for row in usage) != len(requests)-len(confirmed):
                raise ValueError('recovery_usage_not_reconciled')
            done=sum(row['status']=='done' for row in rows)
            receipt = dict(contract='normalize-'+repair+'-recovery-1',source_run_id=source_run_id,
                run_id=run_id,source_identity=digest(previous),target_identity=digest(identity),
                reason={'schema':'nova_schema_missing_from_messages','text':'defer_executable_text_to_questions',
                    'provider':'confirmed_provider_response_invalid_requires_new_id',
                    'batch':'replace_sticky_shrink_with_fixed_configured_batch_size',
                    'empty':'exclude_blank_bodhi_source_rows_without_inventing_concepts'}[repair],accepted_results=done,
                indexed_files=len(previous['inputs']),
                indexed_rows=sum(value for key,value in meta.items() if key.startswith('cursor:')),
                jobs_reset=0 if repair in {'provider','batch','empty'} else len(rows)-done,jobs_kept_done=done,jobs_pending=len(rows)-done,
                confirmed_failed_request_ids=sorted(confirmed_ids),
                requests_preserved=len(requests),usage_preserved=usage,
                previous_attempts=[row for row in rows if row['attempt_count']],
                created_at=time.time(),model_calls_started=0)
            boundary()
            stage_root=work/'.recovery-staging';stage_root.mkdir(exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix='.recover-'+run_id+'-',dir=stage_root))
            print(canonical({'event':'recovery_copy_started','source_run_id':source_run_id,'run_id':run_id}),flush=True)
            copy = sqlite3.connect(staging / 'jobs.sqlite3')
            try:
                db.backup(copy,pages=4096,progress=lambda *args: boundary())
                copy.execute('PRAGMA journal_mode=DELETE')
                with copy:
                    if repair in {'provider','batch'}:
                        copy.execute("UPDATE jobs SET status='pending' WHERE status!='done'")
                        copy.executemany("UPDATE requests SET state='failed' WHERE request_id=?",[(ident,) for ident in confirmed_ids])
                    elif repair!='empty':
                        copy.execute("UPDATE jobs SET status='pending',attempt_count=0,error=NULL WHERE status!='done'")
                    copy.executemany('INSERT OR REPLACE INTO meta VALUES(?,?)',[(key,canonical(value)) for key,value in
                        dict(identity=identity,state='ready',phase='normalize',error=None,pause_requested=False,
                            updated_at=time.time(),recovery=receipt,recovery_source_identity=previous,
                            recovery_history=meta.get('recovery_history',[])+([dict(recovery=meta['recovery'],
                                source_identity=meta.get('recovery_source_identity'))] if meta.get('recovery') else [])).items()])
            finally:
                copy.close()
            recovered=[]
            if repair=='empty':
                from .build import exclude_empty_sources
                from .jobs import Jobs
                saved=Jobs(staging)
                try:
                    receipt['excluded_sources']=exclude_empty_sources(saved)
                    receipt['jobs_pending']=len(saved.pending('normalize'))
                    saved.set('recovery',receipt)
                finally:
                    saved.close()
            if repair=='text':
                from .build import accept_response
                from .jobs import Jobs
                saved=Jobs(staging)
                try:
                    for request in reversed(requests):
                        boundary()
                        ids=[ident for ident in json.loads(request['job_ids']) if saved.db.execute(
                            "SELECT status FROM jobs WHERE job_id=?",(ident,)).fetchone()[0]!='done']
                        if not ids: continue
                        local=dict(request,job_ids=canonical(ids))
                        response=json.loads(request['response']);response.pop('usage',None)
                        invalid=accept_response(saved,local,response)
                        recovered += [dict(job_id=ident,request_id=request['request_id']) for ident in ids if ident not in invalid]
                    receipt['recovered_from_saved_responses']=recovered
                    receipt['jobs_pending']=saved.db.execute("SELECT COUNT(*) FROM jobs WHERE status!='done'").fetchone()[0]
                    saved.set('recovery',receipt)
                finally:
                    saved.close()
            if repair!='empty':
                (staging / 'recovery.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
            boundary()
            if target.exists():
                raise ValueError('recovery_target_exists_use_resume')
            staging.rename(target)
            staging = None
            return dict(event='normalization_recovered',state='ready',run_id=run_id,
                source_run_id=source_run_id,indexed_files=receipt['indexed_files'],
                indexed_rows=receipt['indexed_rows'],jobs_pending=receipt['jobs_pending'],
                jobs_kept_done=done,recovered_from_saved_responses=len(recovered),
                requests_preserved=len(requests),usage_preserved=usage,model_calls_started=0)
        finally:
            db.close()
            if staging is not None:
                shutil.rmtree(staging)
