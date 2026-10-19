import fcntl
import json
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path

from .models import Result, canonical, digest


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
