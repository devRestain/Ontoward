import argparse
import json
import os
import signal
import sys
import time
import math
from pathlib import Path

from .models import CONTRACT, digest, canonical
from .inputs import discover
from .jobs import Jobs, PauseRequested
from .build import run_pipeline
from .verify import verify
from .install import install
from .progress import display
from .recovery import recover_normalization


def configuration(path, provider=None):
    config=json.loads(Path(path).read_text())
    if provider: config['provider']=provider
    if config['provider'] not in {'nova_dev','codex_subscription','openai_api'}:
        raise ValueError('unsupported_provider')
    if config['provider']=='nova_dev':
        config['api_base']=os.environ.get('NOVA_API_BASE','https://nova.snubhai.org')
    if config['effort'] not in {'low','medium','high','xhigh'}:
        raise ValueError('invalid_effort')
    for key in ('timeout_seconds','batch_size','index_chunk_size'):
        if type(config[key]) is not int or config[key]<1: raise ValueError('invalid_'+key)
    if not 1<=config['nova_daily_calls']['draft']<=1000 or not 1<=config['nova_daily_calls']['final']<=100:
        raise ValueError('invalid_nova_ceiling')
    config['prompt_directory']=str(Path(__file__).parents[1]/'prompts')
    return config


def build_identity(entries, config, assets):
    identity={'contract':CONTRACT,'config':config,'inputs':[
        {key:value for key,value in entry.items() if key!='path'} for entry in entries],
        'prompts':{path.name:digest(path.read_text()) for path in sorted(Path(config['prompt_directory']).glob('*.txt'))}}
    from knowledge import graph as graph_module
    identity['schema']=digest(Path(graph_module.__file__).with_name('schema.ttl').read_text())
    identity['runtime_contract']={path.name:digest(path.read_text()) for path in sorted(Path(graph_module.__file__).parent.glob('*.py'))}
    identity['generator']={path.name:digest(path.read_text()) for path in sorted(Path(__file__).parent.glob('*.py'))}
    catalog=Path(assets)/'guidelines/catalog.csv'
    identity['guideline_catalog']=digest(catalog.read_text()) if catalog.is_file() else None
    return identity


def main(argv=None):
    parser=argparse.ArgumentParser(description='Build qualitative clinical knowledge with explicit provider and durable checkpoints')
    parser.add_argument('command',choices=['run','status','pause','verify','install','recover-normalize','recover-normalize-text','recover-normalize-provider','recover-normalize-batch'])
    parser.add_argument('--config',default=os.environ.get('EXTRACTION_CONFIG','/app/config.json'))
    parser.add_argument('--assets',default='/assets')
    parser.add_argument('--work',default='/work')
    parser.add_argument('--output',default='/output')
    parser.add_argument('--target',default='/target')
    parser.add_argument('--run-id')
    parser.add_argument('--manifest')
    parser.add_argument('--provider',choices=['nova_dev','codex_subscription','openai_api'])
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--install',action='store_true')
    parser.add_argument('--retry-unknown',action='store_true')
    parser.add_argument('--human',action='store_true',help='Render readable status or pause output')
    parser.add_argument('--watch',action='store_true',help='Refresh read-only status until Ctrl+C')
    parser.add_argument('--interval',type=float,default=3,help='Status refresh interval in seconds')
    args=parser.parse_args(argv)
    if args.run_id and (not args.run_id.isalnum() or len(args.run_id)>64):
        parser.error('Invalid run ID')
    if args.command.startswith('recover-normalize') and (not args.run_id or args.resume or args.install or args.retry_unknown):
        parser.error('recover-normalize requires --run-id and does not run or install model results')
    work=Path(args.work).resolve()
    if args.watch and args.command!='status': parser.error('--watch is available only for status')
    if not math.isfinite(args.interval) or not 0.1<=args.interval<=60: parser.error('Use an interval between 0.1 and 60 seconds')
    if args.command in {'status','pause'}:
        try:
            while True:
                runs=[work/args.run_id] if args.run_id else sorted(work.glob('*'))
                results=[]
                for directory in runs:
                    if directory.name.startswith('.'): continue
                    if not (directory/'jobs.sqlite3').is_file(): continue
                    jobs=Jobs(directory,readonly=args.command=='status')
                    try: results.append(jobs.status() if args.command=='status' else jobs.pause())
                    finally: jobs.close()
                print(display(results) if args.human or args.watch else canonical(results or {'state':'not_started'}),flush=True)
                if not args.watch: return 0
                time.sleep(args.interval)
        except KeyboardInterrupt:
            return 0
    if args.command in {'verify','install'}:
        manifest=Path(args.manifest) if args.manifest else Path(args.output)/args.run_id/'manifest.json' if args.run_id else Path(args.target)/'manifest.json'
        print(canonical(verify(manifest) if args.command=='verify' else install(manifest,args.target)));return 0
    config=configuration(args.config,args.provider)
    interrupted=[False]
    jobs=None
    def stop(signum,frame):
        interrupted[0]=True
        if jobs is not None: jobs.interrupted=True
    def boundary():
        if interrupted[0]: raise PauseRequested()
    previous={value:signal.signal(value,stop) for value in (signal.SIGINT,signal.SIGTERM)}
    try:
        entries=discover(args.assets,config.get('inputs'),boundary)
        identity=build_identity(entries,config,args.assets)
        if args.command.startswith('recover-normalize'):
            print(canonical(recover_normalization(work,args.run_id,identity,boundary,
                repair={'recover-normalize':'schema','recover-normalize-text':'text',
                    'recover-normalize-provider':'provider','recover-normalize-batch':'batch'}[args.command])),flush=True)
            return 0
        run_id=digest(identity)[:32]
        if args.run_id and args.run_id!=run_id: raise ValueError('checkpoint_fingerprint_mismatch')
        if (work/run_id/'jobs.sqlite3').is_file() and not args.resume:
            raise ValueError('checkpoint_exists_use_resume')
        jobs=Jobs(work/run_id,identity)
        jobs.set('assets_directory',str(Path(args.assets).resolve()))
        if jobs.get('state')=='complete':
            print(canonical(jobs.status()));return 0
        with jobs.worker():
            try:
                run_pipeline(jobs,entries,config,args.output,args.target if args.install else None,args.retry_unknown)
            except PauseRequested:
                raise
            except Exception as error:
                jobs.set('error',str(error));raise
        print(canonical(jobs.status()));return 0
    except PauseRequested:
        print(canonical({'state':'paused','phase':'input_discovery','checkpoint':'not_started'}));return 0
    finally:
        if jobs is not None: jobs.close()
        for value,handler in previous.items(): signal.signal(value,handler)


if __name__=='__main__':
    try:
        raise SystemExit(main())
    except (OSError,ValueError,RuntimeError) as error:
        print(canonical({'status':'failed','error':str(error)}),file=sys.stderr)
        raise SystemExit(2)
