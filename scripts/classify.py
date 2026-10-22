import argparse
import json
from backend.app.config import Settings
from backend.tools.indicators import Rules
from backend.tools.segments import load_segments
from backend.tools.staging import classify

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--legacy',action='store_true',help='use the preserved v1 analysis')
    parser.add_argument('--rules', type=argparse.FileType('r'))
    args = parser.parse_args()
    settings = Settings()
    if args.legacy:
        rows, source = load_segments(settings)
        result = classify(rows, Rules.model_validate_json(args.rules.read()) if args.rules else None)
        result['metadata']['analysis_version']='legacy-v1'
    else:
        if args.rules:parser.error('--rules applies only to --legacy')
        from backend.tools.segments_v3 import load_segments as load_groups
        from backend.tools.region_stage import classify as classify_groups
        rows,source=load_groups(settings)
        result=classify_groups(rows)
    result['metadata']['source'] = source
    target = settings.runtime_dir / 'classification.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"Classified {len(rows)} rows → {target.relative_to(settings.runtime_dir.parent.parent)} (provisional)")
