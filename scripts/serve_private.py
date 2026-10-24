"""Fail-closed single-process entrypoint for the private, persistent regional service."""
import argparse
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path

from backend.app.config import Settings


@contextmanager
def prepare(settings):
    if os.getenv('VERCEL') == '1':
        raise ValueError('private service requires a persistent host, not Vercel functions')
    if settings.data_mode != 'local' or settings.resource_catalog != 'v3':
        raise ValueError('private service requires local data and v3 catalog')
    if settings.input_root is None or settings.runtime_storage_root is None:
        raise ValueError('explicit INPUT_ROOT and RUNTIME_STORAGE_ROOT required')
    inputs = settings.input_root.resolve()
    runtime = settings.runtime_storage_root.resolve()
    if inputs == runtime or inputs in runtime.parents or runtime in inputs.parents:
        raise ValueError('input and runtime directories must be separate')
    from scripts.runtime_package import verify
    manifest = verify(settings.input_root)
    if manifest['provenance']['permission_status'] != 'private_contest_use_confirmed':
        raise ValueError('private contest use confirmation required before serving')
    runtime.mkdir(parents=True, exist_ok=True)
    # Keep the file: unlinking a held lock would allow a second process to own a new inode.
    with (runtime/'service.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('another private service owns this runtime directory') from exc
        try:
            yield manifest
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('port must be between 1 and 65535')
    with prepare(Settings()) as _manifest:
        import uvicorn
        from backend.app.main import create_app
        uvicorn.run(create_app(), host='127.0.0.1', port=args.port, workers=1)


if __name__ == '__main__':
    main()
