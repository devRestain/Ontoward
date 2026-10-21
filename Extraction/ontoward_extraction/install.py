import hashlib
import fcntl
import json
import os
import shutil
from pathlib import Path
from .models import canonical
from .verify import verify


def install(manifest_path, target, boundary=lambda: None, after_replace=lambda: None, *, preserve_build_ids=(),
            cleanup=True, expected_parent_manifest_sha256=None):
    """Serialize every installer at the target, including fresh and maintenance."""
    target = Path(target).resolve()
    target.mkdir(parents=True, exist_ok=True)
    with (target / '.install.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError('target_install_already_running') from error
        return _install(manifest_path, target, boundary, after_replace,
            preserve_build_ids=preserve_build_ids, cleanup=cleanup,
            expected_parent_manifest_sha256=expected_parent_manifest_sha256)


def _install(manifest_path, target, boundary, after_replace, *, preserve_build_ids,
             cleanup, expected_parent_manifest_sha256):
    manifest_path=Path(manifest_path).resolve();target=Path(target).resolve()
    verify(manifest_path)
    manifest=json.loads(manifest_path.read_text())
    build_id=manifest['build_id']
    if not build_id or any(char not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for char in build_id):
        raise ValueError('unsafe_build_id')
    for preserved in preserve_build_ids:
        path=target/'builds'/preserved
        if (not preserved or any(char not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for char in preserved)
                or path.is_symlink() or not path.is_dir()):
            raise ValueError('invalid_preserved_build')
    destination=target/'builds'/build_id
    target.mkdir(parents=True,exist_ok=True);destination.mkdir(parents=True,exist_ok=True)
    original=json.loads(canonical(manifest))
    for role in ('schema','vocabulary','clinical','questions','guidelines'):
        original[role]['path']=Path(original[role]['path']).name
    if (destination/'manifest.json').is_file() and (destination/'manifest.json').read_bytes()!=canonical(original).encode():
        raise ValueError('build_id_collision')
    for role in ('schema','vocabulary','clinical','questions','guidelines'):
        path=destination/Path(manifest[role]['path']).name
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()!=manifest[role]['sha256']:
            raise ValueError('build_id_collision')
    for role in ('schema','vocabulary','clinical','questions','guidelines'):
        boundary()
        entry=manifest[role]
        source=(manifest_path.parent/entry['path']).resolve()
        path=destination/Path(entry['path']).name
        temporary=path.with_suffix(path.suffix+'.tmp')
        with temporary.open('wb') as output:
            output.write(source.read_bytes());output.flush();os.fsync(output.fileno())
        if hashlib.sha256(temporary.read_bytes()).hexdigest()!=entry['sha256']:
            raise ValueError('install_digest_mismatch')
        os.replace(temporary,path)
        original[role]['path']=path.name
        entry['path']=path.relative_to(target).as_posix()
    with (destination/'manifest.json').open('w') as output:
        output.write(canonical(original));output.flush();os.fsync(output.fileno())
    directory_fd=os.open(destination,os.O_RDONLY)
    try: os.fsync(directory_fd)
    finally: os.close(directory_fd)
    staged=target/('manifest-'+build_id+'.tmp')
    staged.write_text(canonical(manifest))
    try:
        verify(staged)
        boundary()
        if expected_parent_manifest_sha256 is not None:
            active = target / 'manifest.json'
            if not active.is_file() or hashlib.sha256(active.read_bytes()).hexdigest() != expected_parent_manifest_sha256:
                raise ValueError('active_parent_changed_child_preserved_not_activated')
        with staged.open('rb') as source: os.fsync(source.fileno())
        os.replace(staged,target/'manifest.json')
    finally:
        staged.unlink(missing_ok=True)
    directory_fd=os.open(target,os.O_RDONLY)
    try: os.fsync(directory_fd)
    finally: os.close(directory_fd)
    after_replace()
    if not cleanup:
        return {'status':'installed','build_id':build_id,'manifest':str(target/'manifest.json'), 'cleanup':False}
    for path in target.iterdir():
        if path.suffix in {'.json','.ttl'} and path.name not in {'manifest.json','schema.ttl'}:
            path.unlink()
    for path in (target/'builds').iterdir():
        if path.name in preserve_build_ids:
            continue
        if path!=destination and path.is_dir() and not path.is_symlink() and (path/'manifest.json').is_file():
            previous=json.loads((path/'manifest.json').read_text())
            owned={Path(previous[role]['path']).name for role in ('schema','vocabulary','clinical','questions','guidelines')}|{'manifest.json'}
            if previous.get('knowledge_contract')=='v5-enum-1' and {item.name for item in path.iterdir()}==owned:
                verify(path/'manifest.json');shutil.rmtree(path)
    return {'status':'installed','build_id':build_id,'manifest':str(target/'manifest.json')}
