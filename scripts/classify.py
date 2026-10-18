import argparse
import json
from backend.app.config import Settings
from backend.tools.indicators import Rules
from backend.tools.segments import load_segments
from backend.tools.staging import classify

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--rules', type=argparse.FileType('r'))
    args = parser.parse_args()
    settings = Settings()
    rows, source = load_segments(settings)
    result = classify(rows, Rules.model_validate_json(args.rules.read()) if args.rules else None)
    result['metadata']['source'] = source
    target = settings.runtime_dir / 'classification.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"Classified {len(rows)} rows → {target.relative_to(settings.runtime_dir.parent.parent)} (provisional)")
