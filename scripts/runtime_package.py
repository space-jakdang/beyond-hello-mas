"""Build an allowlisted, immutable input directory; never copy raw survey data or DBs."""
import argparse
import atexit
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import zipfile

from backend.app.config import Settings
from backend.tools.catalog import load_catalog
from backend.tools.neighborhoods import group_analysis

FILES = ('local/segments-v3.parquet', 'local/resources-v3.csv',
         'local/seohee/card_weekly_signals.csv', 'local/seohee/import.json')
PACKAGE_FILES = (*FILES, 'manifest.json')
# shortcut: small fixed inputs fit server environment limits; use private object storage when they grow.
MAX_ENCODED_BYTES = 48 * 1024
MAX_INPUT_BYTES = 8 * 1024 * 1024


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def regular(path):
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError('regular file without symlink required')
    return path


def inspect(root):
    settings = Settings(_env_file=None, input_root=root, data_mode='local', llm_mode='fake',
                        resource_catalog='v3')
    analysis = group_analysis(settings, week='all', card_age='all')
    if analysis['coverage']['unmatched_codes']:
        raise ValueError('regional inputs do not match geographic boundaries')
    catalog = load_catalog(settings.catalog_path)
    if not catalog:
        raise ValueError('empty resource catalog')
    return {'neighborhoods': len(analysis['neighborhoods']),
            'segments': len(analysis['segments']),
            'preferred': sum(r['preferred'] for r in analysis['segments']),
            'resources': len(catalog), 'input_hash': analysis['metadata']['input_hash'],
            'geography': analysis['geography'],
            'periods': sorted({r['source_period'] for r in analysis['segments']}),
            'monthly_observations': analysis['months'],
            'groups': sorted({(r['sex'], r['age_group']) for r in analysis['segments']})}


def validate_provenance(provenance):
    if not isinstance(provenance, dict) or set(provenance) != {'purpose', 'sources', 'permission_status', 'disposal'}:
        raise ValueError('provenance fields required')
    if any(not isinstance(v, str) or not v.strip() for v in provenance.values()):
        raise ValueError('nonempty provenance required')
    # This record is an operator assertion, not an automatic license decision.
    if provenance['permission_status'] not in ('pending', 'private_contest_use_confirmed'):
        raise ValueError('unknown permission status')


def verify(root):
    root = Path(root).absolute()
    regular(root/'manifest.json')
    manifest = json.loads((root/'manifest.json').read_text())
    if manifest.get('version') != 1 or manifest.get('data_mode') != 'local' or set(manifest.get('files', {})) != set(FILES):
        raise ValueError('unexpected package contract')
    validate_provenance(manifest.get('provenance'))
    actual = set()
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError('symlink in package')
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    if actual != {*FILES, 'manifest.json'}:
        raise ValueError('unexpected or missing package files')
    for name in FILES:
        if sha(regular(root/name)) != manifest['files'][name]:
            raise ValueError('package checksum mismatch')
    summary = inspect(root)
    if json.loads(json.dumps(summary)) != manifest['summary']:
        raise ValueError('package summary or geography changed')
    return manifest


def build(source, destination, provenance):
    """source is INPUT_ROOT, destination is a new version directory, never the active one."""
    source = Path(source).absolute()
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError('destination must be new')
    if source.resolve() == destination.resolve() or source.resolve() in destination.resolve().parents:
        raise ValueError('destination must be outside source')
    validate_provenance(provenance)
    candidates = list((source/'local/seohee').rglob('card_weekly_signals.csv'))
    if len(candidates) != 1:
        raise ValueError('one weekly source required')
    weekly = regular(candidates[0])
    source_manifest = json.loads(regular(source/'local/seohee/import.json').read_text())
    relative = weekly.relative_to(source/'local/seohee').as_posix()
    if sha(weekly) != source_manifest['files'][relative]:
        raise ValueError('source weekly checksum mismatch')
    if any(p.is_symlink() for p in (destination.parent, *destination.parent.parents)):
        raise ValueError('destination parents cannot be symlinks')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.runtime-input-', dir=destination.parent) as temp:
        staging = Path(temp)
        os.chmod(staging, 0o700)
        for name in FILES[:2]:
            target = staging/name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(regular(source/name), target)
        target = staging/FILES[2]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(weekly, target)
        (staging/FILES[3]).write_text(json.dumps({'files': {'card_weekly_signals.csv': sha(target)}}))
        manifest = {'version': 1, 'data_mode': 'local', 'provenance': provenance,
                    'files': {name: sha(staging/name) for name in FILES}, 'summary': inspect(staging)}
        (staging/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
        verify(staging)
        # mkdir exclusively reserves a version; an existing release is never replaced.
        destination.mkdir(mode=0o700)
        try:
            for path in staging.iterdir():
                shutil.move(str(path), str(destination/path.name))
            verify(destination)
        except Exception:
            shutil.rmtree(destination)
            raise
    return manifest


def encode(root):
    root = Path(root)
    manifest = verify(root)
    if manifest['provenance']['permission_status'] != 'private_contest_use_confirmed':
        raise ValueError('private contest use confirmation required before export')
    if sum((root/name).stat().st_size for name in PACKAGE_FILES) > MAX_INPUT_BYTES:
        raise ValueError('input package exceeds expanded size budget')
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in PACKAGE_FILES:
            archive.write(regular(root/name), name)
    value = base64.b64encode(stream.getvalue()).decode('ascii')
    if len(value) > MAX_ENCODED_BYTES:
        raise ValueError('input package exceeds server environment budget')
    return value


def restore(value):
    root = Path(tempfile.mkdtemp(prefix='beyond-regional-inputs-')).resolve()
    try:
        if len(value) > MAX_ENCODED_BYTES:
            raise ValueError('package too large')
        raw = base64.b64decode(value, validate=True)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = archive.namelist()
            if len(names) != len(PACKAGE_FILES) or set(names) != set(PACKAGE_FILES):
                raise ValueError('unexpected package entries')
            if sum(info.file_size for info in archive.infolist()) > MAX_INPUT_BYTES:
                raise ValueError('package too large')
            for name in PACKAGE_FILES:
                target = root/name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(name))
        manifest = verify(root)
        if manifest['provenance']['permission_status'] != 'private_contest_use_confirmed':
            raise ValueError('private contest use not confirmed')
    except Exception:
        shutil.rmtree(root)
        raise ValueError('invalid RUNTIME_INPUT_PACKAGE or private contest use not confirmed') from None
    atexit.register(shutil.rmtree, root, ignore_errors=True)
    return root


def deployment_settings():
    package = os.getenv('RUNTIME_INPUT_PACKAGE')
    if package is not None:
        return Settings(data_mode='local', resource_catalog='v3', input_root=restore(package))
    if os.getenv('VERCEL_ENV') == 'production':
        raise ValueError('production requires RUNTIME_INPUT_PACKAGE; synthetic fallback is disabled')
    return Settings()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('build')
    create.add_argument('--source', type=Path, required=True)
    create.add_argument('--destination', type=Path, required=True)
    create.add_argument('--provenance', type=Path, required=True)
    check = sub.add_parser('verify')
    check.add_argument('root', type=Path)
    export = sub.add_parser('encode', help='export confirmed inputs to a private server environment file')
    export.add_argument('root', type=Path)
    export.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'encode':
        value = encode(args.root)
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(value)
        print(json.dumps({'encoded_bytes': len(value)}))
        return
    result = (build(args.source, args.destination, json.loads(args.provenance.read_text()))
              if args.command == 'build' else verify(args.root))
    print(json.dumps({'version': result['version'], 'summary': result['summary'],
                      'permission_status': result['provenance']['permission_status']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
