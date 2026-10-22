"""Compare deterministic outputs only after checking evaluation provenance."""
import json
import sys
from pathlib import Path


def compare(first, second):
    keys=('git_commit','inputs_hash','labels_hash','catalog_hash','rule_hash','prompts')
    if any(first['metadata'].get(k)!=second['metadata'].get(k) for k in keys) or any(first[k]!=second[k] for k in ('data_mode','llm_mode','model')):
        raise ValueError('evaluation provenance differs')
    fields=('scenario_id','status','path','predicted_crisis','causes','route','subscales','recommendation_count','relevant_recommendations')
    project=lambda report:[{key:r.get(key) for key in fields} for r in report['results']]
    return {'first':first['id'],'second':second['id'],'git_commit':first['metadata']['git_commit'],
            'deterministic_outputs_identical':project(first)==project(second),
            'stage_hashes_identical':first['stage_reproducibility'].get('hashes')==second['stage_reproducibility'].get('hashes'),
            'latency':[r['metrics']['latency'] for r in (first,second)],
            'cost':[r['metrics']['cost'] for r in (first,second)]}


if __name__=='__main__':
    print(json.dumps(compare(*(json.loads(Path(p).read_text()) for p in sys.argv[1:3])),ensure_ascii=False,indent=2))
