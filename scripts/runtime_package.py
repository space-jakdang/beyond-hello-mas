"""Build an allowlisted, immutable input directory; never copy raw survey data or DBs."""
import argparse
import atexit
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import zipfile

from backend.app.config import Settings
from backend.tools.catalog import load_catalog
from backend.tools.indicators import digest
from backend.tools.neighborhoods import group_analysis
from backend.tools.region_stage_v4 import METHOD_VERSION, WORKFLOW_VERSION
from backend.tools.segments_v4 import DATASET_VERSION

FILES_V1 = ('local/segments-v3.parquet', 'local/resources-v3.csv',
            'local/seohee/card_weekly_signals.csv', 'local/seohee/import.json')
FILES_V2 = ('local/segments-v4.parquet', 'local/resources-v3.csv',
            'local/seohee/card_alarm_weekly.csv', 'local/import.json')
PACKAGE_FILES_BY_VERSION = {1: (*FILES_V1, 'manifest.json'), 2: (*FILES_V2, 'manifest.json')}
# Keep these names for callers that build or inspect historical v1 packages.
FILES = FILES_V1
PACKAGE_FILES = PACKAGE_FILES_BY_VERSION[1]
# shortcut: small fixed inputs fit server environment limits; use private object storage when they grow.
MAX_ENCODED_BYTES = 48 * 1024
MAX_INPUT_BYTES = 8 * 1024 * 1024


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def regular(path):
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError('regular file without symlink required')
    return path


def inspect_v1(root):
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


def inspect_v2(root):
    from backend.tools.neighborhoods import group_analysis_v4

    settings = Settings(_env_file=None, input_root=root, data_mode='local', llm_mode='fake',
                        resource_catalog='v3', regional_workflow_version=WORKFLOW_VERSION)
    analysis = group_analysis_v4(settings)
    coverage = analysis['coverage']
    segments = analysis['segments']
    signals = analysis['weekly']['signals']
    weeks = sorted({row['week'] for row in signals})
    groups = {(row['source_region'], row['sex'], row['source_age_band']) for row in signals}
    catalog = load_catalog(settings.catalog_path)
    source = analysis['metadata']['source']
    import_manifest = json.loads((settings.data_dir/'import.json').read_text())
    source_hashes = import_manifest.get('source_hashes')
    expected_sources = {
        '1_탐지/dong_stage_age.csv', '1_탐지/structural_risk_seoul.csv',
        '1_탐지/card_alarm_weekly.csv', 'data/geography/boundaries.geojson',
        'data/geography/manifest.json',
    }
    if (import_manifest.get('manifest_version') != '1'
            or import_manifest.get('generator') != 'scripts.export_seohee_v4:1'
            or import_manifest.get('local_only') is not True
            or import_manifest.get('observation_year') != 2025
            or import_manifest.get('geography_version') != analysis['geography']['version']
            or import_manifest.get('geography_hash') != analysis['geography']['subset_sha256']
            or import_manifest.get('segment_input_hash') != source.get('input_hash')
            or source.get('synthetic') is not False
            or not isinstance(source_hashes, dict) or set(source_hashes) != expected_sources
            or source_hashes != source.get('source_hashes')
            or import_manifest.get('input_hash') != digest(source_hashes)
            or not all(isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value)
                       for value in source_hashes.values())):
        raise ValueError('v2 source, geography, or provenance metadata mismatch')
    if (coverage['matched'] != 47 or coverage['total'] != 47 or coverage['unmatched_codes']
            or len(segments) != 514 or len(groups) != 24 or len(weeks) != 22 or len(signals) != 528):
        raise ValueError('v2 inputs do not cover the expected region, age, and card scope')
    if not catalog:
        raise ValueError('empty resource catalog')
    metadata = analysis['metadata']
    return {
        'schema_version': 4,
        'dataset_version': metadata['dataset_version'],
        'methodology_version': metadata['methodology_version'],
        'workflow_version': metadata['workflow_version'],
        'observed_period': '2025',
        'neighborhood_count': coverage['total'],
        'boundary_matches': coverage['matched'],
        'segment_count': len(segments),
        'status_counts': {status: sum(row['assessment_status'] == status for row in segments)
                          for status in ('assessed', 'small_population_hold', 'insufficient_evidence')},
        'card_signal_count': len(signals),
        'card_group_count': len(groups),
        'card_week_count': len(weeks),
        'card_week_start': weeks[0],
        'card_week_end': weeks[-1],
        'resource_count': len(catalog),
        'input_hash': metadata['input_hash'],
    }


def inspect(root, version=1):
    if version == 1:
        return inspect_v1(root)
    if version == 2:
        return inspect_v2(root)
    raise ValueError('unsupported package version')


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
    version = manifest.get('version')
    if type(version) is not int:
        raise ValueError('unexpected package contract')
    files = {1: FILES_V1, 2: FILES_V2}.get(version)
    if not files or manifest.get('data_mode') != 'local' or set(manifest.get('files', {})) != set(files):
        raise ValueError('unexpected package contract')
    validate_provenance(manifest.get('provenance'))
    actual = set()
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError('symlink in package')
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    if actual != set(PACKAGE_FILES_BY_VERSION[version]):
        raise ValueError('unexpected or missing package files')
    if version == 2 and sum((root/name).stat().st_size for name in PACKAGE_FILES_BY_VERSION[version]) > MAX_INPUT_BYTES:
        raise ValueError('v2 package exceeds expanded size budget')
    for name in files:
        if sha(regular(root/name)) != manifest['files'][name]:
            raise ValueError('package checksum mismatch')
    if version == 2 and (manifest.get('workflow_version') != WORKFLOW_VERSION
                         or manifest.get('methodology_version') != METHOD_VERSION
                         or manifest.get('dataset_version') != DATASET_VERSION
                         or manifest.get('schema_version') != 4):
        raise ValueError('v2 method or data version mismatch')
    if version == 2 and manifest.get('package_id') != hashlib.sha256(
        json.dumps({'version': version, 'files': manifest['files']}, sort_keys=True, separators=(',', ':')).encode()
    ).hexdigest():
        raise ValueError('v2 package identity mismatch')
    summary = inspect(root, version)
    if json.loads(json.dumps(summary)) != manifest['summary']:
        raise ValueError('package summary or geography changed')
    return manifest


def build(source, destination, provenance, package_version=1, catalog_from_package=None):
    """source is INPUT_ROOT, destination is a new version directory, never the active one."""
    source = Path(source).absolute()
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError('destination must be new')
    if source.resolve() == destination.resolve() or source.resolve() in destination.resolve().parents:
        raise ValueError('destination must be outside source')
    validate_provenance(provenance)
    package_provenance = provenance
    if type(package_version) is not int or package_version not in (1, 2):
        raise ValueError('unsupported package version')
    files = FILES_V1 if package_version == 1 else FILES_V2
    catalog_root = None
    catalog_manifest = None
    if package_version == 1:
        candidates = list((source/'local/seohee').rglob('card_weekly_signals.csv'))
        if len(candidates) != 1:
            raise ValueError('one weekly source required')
        weekly = regular(candidates[0])
        source_manifest = json.loads(regular(source/'local/seohee/import.json').read_text())
        relative = weekly.relative_to(source/'local/seohee').as_posix()
        if sha(weekly) != source_manifest['files'][relative]:
            raise ValueError('source weekly checksum mismatch')
    else:
        if catalog_from_package is None:
            raise ValueError('v2 requires a verified v1 catalog package')
        catalog_root = Path(catalog_from_package).absolute()
        if catalog_root.resolve() in destination.resolve().parents:
            raise ValueError('destination must be outside catalog package')
        catalog_manifest = verify(catalog_root)
        if catalog_manifest['version'] != 1:
            raise ValueError('v2 catalog source must be package v1')
        if catalog_manifest['provenance']['permission_status'] != 'private_contest_use_confirmed':
            package_provenance = {**provenance, 'permission_status': 'pending'}
    if any(p.is_symlink() for p in (destination.parent, *destination.parent.parents)):
        raise ValueError('destination parents cannot be symlinks')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.runtime-input-', dir=destination.parent) as temp:
        staging = Path(temp)
        os.chmod(staging, 0o700)
        if package_version == 1:
            for name in FILES_V1[:2]:
                target = staging/name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(regular(source/name), target)
            target = staging/FILES_V1[2]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(weekly, target)
            (staging/FILES_V1[3]).write_text(json.dumps({'files': {'card_weekly_signals.csv': sha(target)}}))
        else:
            for name in FILES_V2:
                target = staging/name
                target.parent.mkdir(parents=True, exist_ok=True)
                source_file = catalog_root/name if name == 'local/resources-v3.csv' else source/name
                shutil.copyfile(regular(source_file), target)
            if sha(staging/'local/resources-v3.csv') != catalog_manifest['files']['local/resources-v3.csv']:
                raise ValueError('v1 resource catalog changed during build')
        file_hashes = {name: sha(staging/name) for name in files}
        if package_version == 1:
            manifest = {'version': 1, 'data_mode': 'local', 'provenance': package_provenance,
                        'files': file_hashes, 'summary': inspect(staging, 1)}
        else:
            manifest = {'version': 2, 'data_mode': 'local', 'workflow_version': WORKFLOW_VERSION,
                        'methodology_version': METHOD_VERSION, 'schema_version': 4,
                        'dataset_version': DATASET_VERSION,
                        'package_id': hashlib.sha256(json.dumps(
                            {'version': 2, 'files': file_hashes}, sort_keys=True, separators=(',', ':')
                        ).encode()).hexdigest(),
                        'provenance': package_provenance, 'files': file_hashes,
                        'summary': inspect(staging, 2)}
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
    package_files = PACKAGE_FILES_BY_VERSION[manifest['version']]
    if sum((root/name).stat().st_size for name in package_files) > MAX_INPUT_BYTES:
        raise ValueError('input package exceeds expanded size budget')
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in package_files:
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
            if len(names) != len(set(names)) or 'manifest.json' not in names:
                raise ValueError('duplicate or missing package manifest')
            if sum(info.file_size for info in archive.infolist()) > MAX_INPUT_BYTES:
                raise ValueError('package too large')
            version = json.loads(archive.read('manifest.json')).get('version')
            package_files = PACKAGE_FILES_BY_VERSION.get(version)
            if not package_files or len(names) != len(package_files) or set(names) != set(package_files):
                raise ValueError('unexpected package entries')
            for name in package_files:
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
        return settings_from_package(restore(package))
    if os.getenv('VERCEL_ENV') == 'production':
        raise ValueError('production requires RUNTIME_INPUT_PACKAGE; synthetic fallback is disabled')
    return Settings()


def settings_from_package(root, settings=None):
    manifest = verify(root)
    if manifest['provenance']['permission_status'] != 'private_contest_use_confirmed':
        raise ValueError('private contest use confirmation required before serving')
    workflow = 'regional-workflow-2' if manifest['version'] == 2 else 'regional-workflow-1'
    settings = settings or Settings(_env_file=None)
    return settings.model_copy(update={'data_mode': 'local', 'resource_catalog': 'v3', 'input_root': root,
                                       'regional_workflow_version': workflow})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('build')
    create.add_argument('--source', type=Path, required=True)
    create.add_argument('--destination', type=Path, required=True)
    create.add_argument('--provenance', type=Path, required=True)
    create.add_argument('--package-version', type=int, choices=(1, 2), default=1)
    create.add_argument('--catalog-from-package', type=Path)
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
    result = (build(args.source, args.destination, json.loads(args.provenance.read_text()),
                    args.package_version, args.catalog_from_package)
              if args.command == 'build' else verify(args.root))
    print(json.dumps({'version': result['version'], 'summary': result['summary'],
                      'permission_status': result['provenance']['permission_status']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
