from pathlib import Path
import subprocess

if __name__ == "__main__":
    hook = Path(subprocess.check_output(["git", "rev-parse", "--git-path", "hooks/pre-commit"], text=True).strip())
    hook.parent.mkdir(parents=True, exist_ok=True)
    try:
        with hook.open("x") as stream:
            stream.write('#!/bin/sh\nexec uv run python scripts/check_public.py\n')
    except FileExistsError:
        raise SystemExit("Existing pre-commit hook preserved; add: uv run python scripts/check_public.py")
    hook.chmod(0o755)
    print(f"Installed {hook}")
