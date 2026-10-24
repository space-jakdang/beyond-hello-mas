"""Build an allowlisted, immutable input directory; never copy raw survey data or DBs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from backend.app.config import Settings
from backend.tools.catalog import load_catalog
from backend.tools.neighborhoods import group_analysis

FILES = ('local/segments-v3.parquet', 'local/resources-v3.csv',
         'local/seohee/card_weekly_signals.csv', 'local/seohee/import.json')


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('build')
    create.add_argument('--source', type=Path, required=True)
    create.add_argument('--destination', type=Path, required=True)
    create.add_argument('--provenance', type=Path, required=True)
    check = sub.add_parser('verify')
    check.add_argument('root', type=Path)
    args = parser.parse_args()
    result = (build(args.source, args.destination, json.loads(args.provenance.read_text()))
              if args.command == 'build' else verify(args.root))
    print(json.dumps({'version': result['version'], 'summary': result['summary'],
                      'permission_status': result['provenance']['permission_status']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
