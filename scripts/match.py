import argparse
import json
from pathlib import Path

from backend.app.config import ROOT
from backend.tools.catalog import load_catalog
from backend.tools.matching import MatchRequest, match

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('request', type=Path, help='JSON MatchRequest; output may contain private data')
    parser.add_argument('--catalog', type=Path, default=ROOT / 'data/sample/resources.csv')
    args = parser.parse_args()
    print(json.dumps(match(load_catalog(args.catalog), MatchRequest.model_validate_json(args.request.read_text())),
                     ensure_ascii=False, indent=2))
