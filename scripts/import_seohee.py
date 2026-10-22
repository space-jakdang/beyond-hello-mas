"""Copy the supplied MAS bundle into ignored local storage without altering sources."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from backend.app.config import ROOT


def inventory(root):
    files={}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():raise ValueError('symlinks are not bundle inputs')
        if path.is_file():
            files[path.relative_to(root).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    if not files:raise ValueError('empty bundle')
    return files


def import_bundle(source, destination=None):
    source=Path(source)
    if source.is_symlink():raise ValueError('symlink source')
    source=source.resolve()
    destination=Path(destination) if destination else ROOT/'data/local/seohee'
    if destination.is_symlink():raise ValueError('symlink destination')
    if destination.resolve().is_relative_to(source):raise ValueError('destination must be outside source')
    hashes=inventory(source)
    if 'import.json' in hashes:raise ValueError('reserved manifest name')
    if destination.exists():
        actual=inventory(destination);actual.pop('import.json',None)
        if actual!=hashes:raise ValueError('destination differs; existing input was preserved')
        if not (destination/'import.json').exists() or json.loads((destination/'import.json').read_text()).get('files')!=hashes:
            raise ValueError('import manifest missing or inconsistent')
        return hashes
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as staging:
        target=Path(staging)/'bundle'
        shutil.copytree(source,target,symlinks=True)
        if inventory(target)!=hashes or inventory(source)!=hashes:
            raise ValueError('source changed during copy')
        (target/'import.json').write_text(json.dumps({'schema_version':'1','local_only':True,'files':hashes},ensure_ascii=False,indent=2)+'\n')
        target.rename(destination)
    return hashes


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    args=parser.parse_args()
    print(f'Imported/verified {len(import_bundle(args.source))} files in data/local/seohee')
