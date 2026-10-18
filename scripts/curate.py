import argparse
import json
from pathlib import Path
from backend.tools.curation import export

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Export reviewed manual entries; use a new directory for a new version.')
    parser.add_argument('--input', type=Path, default=Path('data/catalog/reviewed.json'))
    parser.add_argument('--output', type=Path, default=Path('data/catalog/curated-20261018-1'))
    args = parser.parse_args()
    report = export(json.loads(args.input.read_text()), args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(1 if report['rejected'] or report['target_shortfall'] else 0)
