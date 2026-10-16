from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil

from .database import SourceDatabase, file_hash
from .v5 import ROOT, workspace_path, write


def verify_archive(path, expected_sha, expected_bytes):
    checksum, size = hashlib.sha256(), 0
    with gzip.open(path, 'rb') as stream:
        while chunk := stream.read(1024 * 1024):
            checksum.update(chunk)
            size += len(chunk)
    if checksum.hexdigest() != expected_sha or size != expected_bytes:
        raise ValueError('Lossless archive differs from original bytes: '+str(path))


def archive_file(path, archive_directory):
    sha, size = file_hash(path), path.stat().st_size
    archive_directory.mkdir(exist_ok=True)
    target = archive_directory/(sha+'.json.gz')
    if not target.exists():
        temporary = target.with_suffix('.gz.tmp')
        with path.open('rb') as source, temporary.open('wb') as raw:
            with gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0) as compressed:
                shutil.copyfileobj(source, compressed, length=1024 * 1024)
        verify_archive(temporary,sha,size)
        temporary.replace(target)
    verify_archive(target,sha,size)
    if file_hash(path) != sha:
        raise ValueError('Original changed during archival; keep it unchanged')
    return {'original_sha256':sha, 'original_bytes':size, 'archive':target.name,
            'archive_sha256':file_hash(target), 'archive_bytes':target.stat().st_size}


def compact(directory):
    directory = workspace_path(directory)
    if not directory.is_relative_to(ROOT/'data/preparation/v5'):
        raise ValueError('Compact only a completed data-owned preparation build')
    database = SourceDatabase(directory/'ontology.sqlite3', readonly=True)
    try:
        if database.meta('stage') != 'complete':
            raise ValueError('Preserve incomplete or unrecognized preparation builds')
        build_id = database.meta('build_id')
    finally:
        database.close()
    receipt_path = directory/'storage-compaction.json'
    receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {
        'build_id':build_id, 'format':'lossless-preparation-archives-v1', 'files':{},
        'raw_sources_and_sqlite':'unchanged', 'historical_identity':'original_hash_preserved_in_archive',
        'restore':'gzip -dc archives/<original_sha256>.json.gz > <original_relative_path>',
        'physical_allocated_bytes':'not_measured'}
    if receipt['build_id'] != build_id:
        raise ValueError('Storage receipt belongs to a different build')
    paths = [directory/'preview/sources.json',directory/'korean-workset.json']
    paths += sorted(directory.glob('interrupted-preview-*/sources.json'))
    for path in paths:
        if not path.is_file() or path.stat().st_size < 1024*1024:
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(directory):
            raise ValueError('Do not archive linked or external preparation files')
        key = path.relative_to(directory).as_posix()
        record = archive_file(path,directory/'archives')
        receipt['files'][key] = {**record,'state':'verified_before_original_removal'}
        write(receipt_path,receipt)
        path.unlink()
        receipt['files'][key]['state'] = 'original_removed_after_roundtrip_verification'
        write(receipt_path,receipt)
    archives = {}
    for record in receipt['files'].values():
        target = directory/'archives'/record['archive']
        if file_hash(target) != record['archive_sha256']:
            raise ValueError('Stored archive hash changed')
        verify_archive(target,record['original_sha256'],record['original_bytes'])
        archives[target.name] = record['archive_bytes']
    receipt['original_logical_bytes'] = sum(record['original_bytes'] for record in receipt['files'].values())
    receipt['archive_logical_bytes'] = sum(archives.values())
    receipt['reduced_logical_bytes'] = receipt['original_logical_bytes']-receipt['archive_logical_bytes']
    receipt['status'] = 'pass'
    write(receipt_path,receipt)
    return receipt


if __name__=='__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory',type=Path,required=True)
    print(json.dumps(compact(parser.parse_args().directory),indent=2))
