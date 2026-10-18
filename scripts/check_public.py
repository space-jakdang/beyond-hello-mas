"""Inspect index blobs (hook) or HEAD blobs (CI), never working-tree substitutes."""
import argparse
import hashlib
import json
import unicodedata
from pathlib import PurePosixPath
import re
import subprocess

SECRET = re.compile(rb"(?:sk-(?:proj-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)")
ASSIGNMENT = re.compile(rb"(?im)^\s*(?:OPENAI_API_KEY|ANTHROPIC_API_KEY|GITHUB_TOKEN|GOV24_SERVICE_KEY)[ \t]*=[ \t]*[^\s#]+")


def violations(path: str, content: bytes, permissions=()) -> list[str]:
    p = PurePosixPath(path)
    private = (path.startswith((".local-plans/", "data/local/", "runtime/", "eval/local/"))
               or any(part.startswith('.env') and part != '.env.example' for part in p.parts)
               or re.search(r"\.(?:db|sqlite|sqlite3)(?:-.*)?$", path))
    errors = ["private path"] if private else []
    if SECRET.search(content) or ASSIGNMENT.search(content):
        errors.append("possible credential")
    fingerprint=hashlib.sha256(content).hexdigest()
    normalized=unicodedata.normalize('NFC',path)
    for row in permissions:
        if row['permission'] not in ('공개 가능','공개 가능 (출처 표기)') and (
            row['sha256']==fingerprint or ('/' in row['path'] and (normalized==row['path'] or normalized.endswith('/'+row['path'])))):
            errors.append('source manifest prohibits publication')
            break
    return errors


def git(*args):
    return subprocess.check_output(["git", *args])


def scan(tracked=False):
    args = ("ls-tree", "-r", "--name-only", "-z", "HEAD") if tracked else (
        "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
    problems = []
    prefix='HEAD:' if tracked else ':'
    try:
        permissions=json.loads(git('show',prefix+'rules/source_permissions.json'))['files']
    except (subprocess.CalledProcessError,KeyError,ValueError):
        permissions=[]
        problems.append('source permission registry missing or invalid')
    for raw in git(*args).split(b"\0"):
        if not raw:
            continue
        path = raw.decode()
        content = git("show", ("HEAD:" if tracked else ":") + path)
        problems.extend(f"{path}: {error}" for error in violations(path, content, permissions))
    return problems


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracked", action="store_true", help="scan committed HEAD for CI/release")
    args = parser.parse_args()
    problems = scan(args.tracked)
    print("\n".join(problems) if problems else "Public-file check passed")
    raise SystemExit(bool(problems))
