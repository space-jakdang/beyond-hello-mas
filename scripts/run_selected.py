"""Run pregate's mixed Python/Playwright selection with the repository runners."""
from pathlib import Path
import subprocess
import sys


def main():
    files=sys.argv[1:]
    if not files or any(not Path(f).is_file() or not (f.startswith('tests/') and f.endswith('.py') or f.startswith('frontend/e2e/') and f.endswith('.spec.ts')) for f in files):
        raise SystemExit('expected existing Python or Playwright test paths')
    python=[f for f in files if f.endswith('.py')]
    browser=[f.removeprefix('frontend/') for f in files if f.endswith('.spec.ts')]
    sys.argv=sys.argv[:1]  # Application runpy tests must not receive pytest selection arguments.
    if python:
        import pytest
        result=pytest.main(python)
        if result:raise SystemExit(result)
    if browser:
        subprocess.run(['npm','run','test:e2e','--',*browser,'--workers=2'],cwd='frontend',check=True)


if __name__=='__main__':main()
