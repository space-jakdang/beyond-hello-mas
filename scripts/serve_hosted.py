"""Authenticated single-process service for a host with a persistent disk and HTTPS ingress."""
import base64
import os
from pathlib import Path
import secrets

import uvicorn
from starlette.responses import Response

from backend.app.config import Settings
from backend.app.main import create_app
from scripts.runtime_package import restore
from scripts.serve_private import prepare


def main():
    username = os.environ.get('PRIVATE_HTTP_USER', '')
    password = os.environ.get('PRIVATE_HTTP_PASSWORD', '')
    if not username.strip() or ':' in username or len(password) < 24:
        raise ValueError('PRIVATE_HTTP_USER and a PRIVATE_HTTP_PASSWORD of at least 24 characters required')
    runtime = os.environ.get('RUNTIME_STORAGE_ROOT')
    if not runtime or not Path(runtime).is_absolute():
        raise ValueError('absolute RUNTIME_STORAGE_ROOT required')
    if os.getenv('RENDER') == 'true' and not Path(runtime).is_mount():
        raise ValueError('RUNTIME_STORAGE_ROOT must be the mounted persistent disk')
    port = int(os.environ.get('PORT', '10000'))
    if not 1 <= port <= 65535:
        raise ValueError('PORT must be between 1 and 65535')
    package = os.environ.get('RUNTIME_INPUT_PACKAGE')
    if not package:
        raise ValueError('RUNTIME_INPUT_PACKAGE required')
    settings = Settings(_env_file=None, data_mode='local', resource_catalog='v3', input_root=restore(package))
    if settings.evaluation_id is not None:
        raise ValueError('hosted service requires the existing runtime ledger; clear EVALUATION_ID')
    expected = b'Basic ' + base64.b64encode(f'{username}:{password}'.encode())
    with prepare(settings):
        app = create_app(settings)

        @app.middleware('http')
        async def authenticate(request, call_next):
            if request.url.path == '/healthz' and request.method in ('GET', 'HEAD'):
                return Response(status_code=200, headers={'Cache-Control':'no-store'})
            if not secrets.compare_digest(request.headers.get('authorization', '').encode(), expected):
                return Response('Authentication required', status_code=401,
                                headers={'WWW-Authenticate': 'Basic realm="Beyond Hello", charset="UTF-8"',
                                         'Cache-Control': 'no-store'})
            return await call_next(request)

        uvicorn.run(app, host='0.0.0.0', port=port, workers=1, timeout_graceful_shutdown=120)


if __name__ == '__main__':
    main()
