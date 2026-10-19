"""Verify the qualitative viewer and withdrawn-bundle state without old clinical data."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'submission'),str(ROOT/'Extraction'),str(ROOT/'Extraction/tests')]
from ontoward_extraction.compile import compile_bundle
from support import nodes, relation
spec=importlib.util.spec_from_file_location('knowledge_viewer',ROOT/'Test/knowledge.py')
viewer=importlib.util.module_from_spec(spec);spec.loader.exec_module(viewer)


def main():
    checks=[]
    with tempfile.TemporaryDirectory() as temporary:
        root=Path(temporary);folder=root/'submission/knowledge';folder.mkdir(parents=True)
        pending=viewer.Knowledge(root)
        assert pending.overview()['status']=='knowledge_bundle_not_installed';checks.append('withdrawn_state')
        compile_bundle(folder,'fixture',nodes(),[relation(),relation('against',target='context',status='absent')])
        knowledge=viewer.Knowledge(root);overview=knowledge.overview()
        assert overview['status']=='installed' and len(overview['pins'])==5;checks.append('new_manifest_pins')
        server=viewer.ViewerServer(('127.0.0.1',0),knowledge)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        address=f'http://127.0.0.1:{server.server_port}'
        def get(route,**params):
            with urlopen(address+route+('?' +urlencode(params) if params else ''),timeout=3) as response:
                raw=response.read()
                return json.loads(raw) if 'application/json' in response.headers['Content-Type'] else raw
        try:
            assert all(get(path) for path in ('/','/app.js','/style.css'));checks.append('local_assets_http')
            diseases=get('/api/search',type='Disease');assert diseases['total']==1
            disease=get('/api/node',id=diseases['items'][0]['id'])
            association=next(item['node']['id'] for item in disease['items'] if item['predicate']==str(viewer.ONTO.hasAssociation))
            detail=get('/api/node',id=association)
            assert any(row['predicate']==str(viewer.ONTO.diagnosticEffect) for row in detail['literals'])
            assert any(row['predicate']==str(viewer.ONTO.targetScope) for row in detail['literals']);checks.append('effect_scope_traversal')
            graph=get('/api/graph',id=disease['id']);assert graph['nodes'] and graph['edges'];checks.append('directed_graph')
            assert not get('/api/search',q='missing-zzzz')['items'];checks.append('empty_search')
            try: get('/api/search',offset=-1)
            except HTTPError as error: assert error.code==400
            else: raise AssertionError('negative_offset')
            checks.append('request_boundaries')
            for name,(_,relative) in viewer.DATABASES.items():
                path=root/relative;path.parent.mkdir(parents=True,exist_ok=True)
                with sqlite3.connect(path) as db:
                    db.execute('CREATE TABLE metadata(key TEXT,value TEXT)')
                    db.execute('CREATE TABLE registry(uri TEXT)');db.execute("INSERT INTO registry VALUES('fixture')")
                before=path.read_bytes()
                assert get('/api/rows',db=name,table='registry',column='uri',q='fixture')['rows']==[{'uri':'fixture'}]
                assert not get('/api/rows',db=name,table='registry',column='uri',q="' OR 1=1 --")['rows']
                with knowledge.database(name) as db:
                    try: db.execute('DELETE FROM registry')
                    except sqlite3.OperationalError: pass
                    else: raise AssertionError('writable_database')
                assert before==path.read_bytes()
            checks.append('read_only_historical_tables')
        finally: server.shutdown();server.server_close()
    report={'status':'pass','checks':checks,'browser_rendering':'not_run','actual_models':'not_run'}
    output=ROOT/'Tmp/d49-2026-10-19/viewer';output.mkdir(parents=True,exist_ok=True)
    (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))


if __name__=='__main__': main()
