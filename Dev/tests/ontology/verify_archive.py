import argparse
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from Dev.ontology.v5 import workspace_path,write,digest


def verify(directory,archive,output=None):
    directory,archive=workspace_path(directory),workspace_path(archive)
    with ZipFile(archive) as zipped:
        names=zipped.namelist()
        if any(name.startswith('/') or '..' in Path(name).parts for name in names):
            raise ValueError('Unsafe archive member')
        expanded=sum(info.file_size for info in zipped.infolist())
        if len(names)>5000 or expanded>500_000_000 or archive.stat().st_size>50_000_000 or zipped.testzip():
            raise ValueError('Archive integrity or resource limit failure')
        if any(Path(name).name in {'AGENTS.md','README.md','PROJECT_STATE.md'} or name.startswith(('Dev/','data/','assets/')) or name.endswith(('.sqlite3','.pyc')) for name in names):
            raise ValueError('Preparation files leaked into runtime archive')
        for name in names:
            source=ROOT/'submission'/name
            if source.is_file() and zipped.read(name)!=source.read_bytes():
                raise ValueError('Runtime bytes differ from source: '+name)
        if zipped.read('nova_sdk.py')!=(ROOT/'assets/nova-starter/nova_sdk.py').read_bytes():
            raise ValueError('SDK source digest changed')
        manifest=json.loads(zipped.read('knowledge/manifest.json'))
        status=manifest['preparation_status']
        if status not in {'preview_only','admitted'}:
            raise ValueError('Archive has an unknown knowledge status')
        receipt=json.loads((directory/'review-approved.json').read_text()) if status=='admitted' else None
        if receipt and (receipt.get('approved') is not True or digest(receipt)!=manifest['review_receipt_sha256']
                        or receipt['build_id']!=manifest['build_id']):
            raise ValueError('Archive differs from the approved receipt')
        assets=[manifest['schema'],manifest['vocabulary'],*manifest['bundles'],manifest['scoring_policy']]
        assets.extend(manifest[key] for key in ('labels','questions','plans') if manifest.get(key))
        for asset in assets:
            payload=zipped.read(asset['path'])
            name=Path(asset['path']).name
            if receipt and name.startswith(manifest['review_receipt_sha256'][:16]+'-'):
                name=name[17:]
            text=next((value for value in (receipt or {}).get('text_assets',{}).values() if Path(value['path']).name==name),None)
            source=ROOT/text['path'] if text else directory/'preview'/name
            if hashlib.sha256(payload).hexdigest()!=asset['sha256'] or payload!=source.read_bytes():
                raise ValueError('Pinned knowledge asset bytes differ')
    result={'status':'pass','file_count':len(names),'expanded_bytes':expanded,'compressed_bytes':archive.stat().st_size,
            'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'sdk_sha256':hashlib.sha256((ROOT/'submission/nova_sdk.py').read_bytes()).hexdigest(),
            'knowledge_status':status,'production_admission':'pass' if receipt else 'not_run',
            'production_prepare':'not_run','authenticated_sdk':'not_run','network':'none'}
    write(output or directory/'artifact-verification.json',result)
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('directory',type=Path)
    parser.add_argument('archive',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    print(json.dumps(verify(args.directory,args.archive,args.output),indent=2))
