"""Exercise the built image with a protocol double and durable temporary artifacts."""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

from ontoward_extraction.__main__ import main
from ontoward_extraction.jobs import Jobs
from support import inputs, ScriptedProvider


def command(*arguments):
    environment={key:value for key,value in os.environ.items() if key not in {'NOVA_DEV_KEY','OPENAI_API_KEY','CODEX_API_KEY'}}
    process=subprocess.run([sys.executable,'-B','-m','ontoward_extraction',*arguments],env=environment,
        capture_output=True,text=True,timeout=30)
    if process.returncode: raise AssertionError(process.stderr)
    return json.loads(process.stdout)


def accept(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    assets=inputs(root/'assets');work=root/'work';output=root/'output';target=root/'target'
    def pause():
        run=next(work.iterdir())
        status=command('pause','--work',str(work),'--run-id',run.name)
        assert status[0]['state']=='pausing',status
    provider=ScriptedProvider(pause)
    args=['run','--config','/app/config.json','--assets',str(assets),'--work',str(work),
        '--output',str(output),'--target',str(target),'--install']
    with patch('ontoward_extraction.build.Provider',return_value=provider),contextlib.redirect_stdout(io.StringIO()):
        assert main(args)==0
    paused=command('status','--work',str(work));assert paused[0]['state']=='paused'
    run=work/paused[0]['run_id'];jobs=Jobs(run,readonly=True)
    done={row[0] for row in jobs.db.execute("SELECT job_id FROM jobs WHERE status='done'")};jobs.close()
    provider.after_send=None;provider.calls.clear()
    with patch('ontoward_extraction.build.Provider',return_value=provider),contextlib.redirect_stdout(io.StringIO()):
        assert main(args+['--resume'])==0
    status=command('status','--work',str(work),'--run-id',run.name)
    assert status[0]['state']=='complete';assert not done.intersection(provider.calls)
    verified=command('verify','--manifest',str(target/'manifest.json'))
    assert verified['status']=='pass'
    report={'status':'pass','image_pipeline':'synthetic_protocol_only','provider':'stub',
        'pause':'keyless_cli_between_request_and_acceptance','resume':'done_jobs_not_recalled',
        'verification':verified,'checkpoint':status[0],'actual_models':'not_run','real_installation':'not_run'}
    (root/'verification.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path);accept(parser.parse_args().output)
