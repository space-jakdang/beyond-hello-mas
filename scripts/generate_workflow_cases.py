"""AI-assisted synthetic contract fixtures. Labels never enter runtime inputs."""
import argparse
import json
import random
from pathlib import Path
from backend.tools.indicators import digest

VERSION='regional-workflow-cases-1'


def generate(seed=20261021):
    rng=random.Random(seed);inputs=[];labels=[]
    # Manually specified examples of the provisional rule, not external ground truth.
    examples={'11230':[('S1',.20,3),('S1',.25,2),('S1',.31,1),('S1',None,None),('G_gangnam_rank',2,5),('G_gangnam_rank',4,4)],
              '32010':[('v3',.60,3),('v3',.10,2),('v3',-.10,1),('v3',None,None),('G_chuncheon',.9,5),('G_chuncheon',.8,4)]}
    for sgg,months,split in [('11230',['2025-07','2025-08','2025-09'],'development'),('32010',['2025-10','2025-11','2025-12'],'test')]:
        for ym in months:
            for n,(index,value,stage) in enumerate(examples[sgg]):
                case_id=f'{sgg}-{ym}-{n}'
                observed=None if value is None else round(value+rng.uniform(-.001,.001),6)
                row={'ym':ym,'sgg':sgg,'dong_cd':sgg+f'{n+1:03}','dong_nm':f'합성동{n+1}',
                     'sex':'M','age_group':'youth' if index in ('S1','v3') else 'prime','source_bands':{'synthetic':['20s','30s'] if index in ('S1','v3') else ['50s','60s']},
                     'index_name':index,'risk_direction':'low_is_risk' if index=='S1' else 'high_is_risk','value':observed,'source_stage':stage if index.startswith('G_') else None,
                     'source_period':ym,'source_file':'synthetic-generator','x':0,'y':0,'crs':'synthetic',
                     'coordinate_source':'synthetic','components':{}}
                inputs.append({'id':case_id,'split':split,'family':f'{sgg}-{n}','segment':row})
                labels.append({'id':case_id,'stage':stage,'basis':'provided_stage_preservation' if index.startswith('G_') else 'hand_rule_example'})
    return {'version':VERSION,'seed':seed,'inputs':inputs,'labels':labels,
            'input_hash':digest(inputs),'label_hash':digest(labels),'external_ground_truth':False}


def write_dataset(directory,seed=20261021):
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=False)
    data=generate(seed)
    for name in ('inputs','labels'):
        (directory/f'{name}.json').write_text(json.dumps(data[name],ensure_ascii=False,indent=2)+'\n')
    manifest={k:v for k,v in data.items() if k not in ('inputs','labels')}
    (directory/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path);parser.add_argument('--seed',type=int,default=20261021)
    args=parser.parse_args();print(json.dumps(write_dataset(args.output,args.seed)))
