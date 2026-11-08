"""Validate the runtime inputs against the supplied, immutable S6 archive."""
from __future__ import annotations
from functools import cache
import hashlib
from pathlib import PurePosixPath
import zipfile
import zlib
from .table import ROOT,GAME

ARCHIVE=ROOT/'麦版S6本体+ct+修改器.zip'
ARCHIVE_SHA256='d3107c98113ab1c1af2f1fd36813782f290e09b4520bffc3810638146a690ab9'
RUNTIME_DIRS={'data','properties','particles','reanim','sounds','fonts','compiled','images','newimages'}
RUNTIME_FILES={'PlantsVsZombies.exe','gdi42.dll','DllMain.dll','bass.dll','S6正赛(bug寒).CT'}


@cache
def verified_assets():
    archive_digest=hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
    if archive_digest!=ARCHIVE_SHA256:
        raise RuntimeError('The supplied original S6 archive differs from the supported package')
    expected={}
    with zipfile.ZipFile(ARCHIVE) as archive:
        for entry in archive.infolist():
            path=PurePosixPath(entry.filename)
            if entry.is_dir() or len(path.parts)<2:continue
            if path.parts[0]!=GAME.name:raise RuntimeError('Unexpected archive root')
            relative=PurePosixPath(*path.parts[1:]).as_posix()
            if path.parts[1] in RUNTIME_DIRS or relative in RUNTIME_FILES:
                expected[relative]=entry
    actual={p.relative_to(GAME).as_posix() for directory in RUNTIME_DIRS
            for p in (GAME/directory).rglob('*') if p.is_file()}
    extras=actual-set(expected)
    if extras:raise RuntimeError(f'Unexpected files in original runtime directories: {sorted(extras)[:8]}')
    digest=hashlib.sha256()
    for relative,entry in sorted(expected.items()):
        try:data=(GAME/relative).read_bytes()
        except OSError as exc:raise RuntimeError(f'Missing original runtime asset: {relative}') from exc
        if len(data)!=entry.file_size or zlib.crc32(data)!=entry.CRC:
            raise RuntimeError(f'Original runtime asset differs from archive: {relative}')
        digest.update(relative.encode('utf-8')+b'\0'+hashlib.sha256(data).digest())
    return {'archive_sha256':archive_digest,'runtime_assets_sha256':digest.hexdigest(),
            'runtime_asset_count':len(expected)}
