"""Read provided youth card observations; audit alerts without modifying source values."""
import csv
from collections import defaultdict
from datetime import date, timedelta
import hashlib
import json
from math import isfinite
from statistics import median
from backend.app import config

INDICATORS=('T1b','R1')
ROUNDING=.00005  # Each provided value, baseline and ratio was independently rounded to four decimals.


def alarm(ratios,weak_threshold=.95):
    if not ratios or ratios[-1] is None:return 'none'
    def streak(threshold,n):
        return len(ratios)>=n and all(v is not None and v<threshold for v in ratios[-n:])
    if streak(.90,2) or streak(.95,4):return 'strong'
    return 'weak' if streak(weak_threshold,2) else 'none'


def audit(rows):
    cohorts=defaultdict(list)
    for r in rows:
        if r['sgg'] not in ('11230','32010') or r['sex'] not in ('M','F') or r['age_band'] not in ('20s','30s'):
            raise ValueError('invalid weekly group')
        if date.fromisoformat(r['week']).weekday()!=0:raise ValueError('week must start Monday')
        if set(r['metrics'])!=set(INDICATORS):raise ValueError('expected T1b and R1')
        for metric in r['metrics'].values():
            for key in ('value','baseline','ratio'):
                v=metric[key]
                if v is not None and (type(v) not in (int,float) or not isfinite(v) or v<0):raise ValueError('invalid weekly numeric value')
            if metric['value'] is None or metric['baseline']==0:raise ValueError('weekly value/positive baseline required')
        cohorts[(r['sgg'],r['sex'],r['age_band'])].append(r)
    checked=0
    for key,group in cohorts.items():
        group.sort(key=lambda r:r['week'])
        if len({r['week'] for r in group})!=len(group):raise ValueError('duplicate weekly observation')
        weak=.90 if key==('32010','F','20s') else .95
        for ind in INDICATORS:
            history=[];ratios=[]
            for i,r in enumerate(group):
                metric=r['metrics'][ind];value=metric['value'];base=metric['baseline']
                if i<8:
                    if base is not None or metric['ratio'] is not None or metric['signal']!='none':raise ValueError('warmup cannot have a signal')
                else:
                    if base is None or abs(base-median(history[-8:]))>2*ROUNDING+1e-12:raise ValueError('baseline differs from prior eight observations')
                # Displayed ratios are rounded; source value/base preserves the strict threshold in this bundle.
                ratio=value/base if base else None
                if ratio is not None:
                    if base<=ROUNDING:raise ValueError('baseline below source precision')
                    low=max(0,value-ROUNDING)/(base+ROUNDING)-ROUNDING
                    high=(value+ROUNDING)/(base-ROUNDING)+ROUNDING
                    if metric['ratio'] is None or not low-1e-12<=metric['ratio']<=high+1e-12:raise ValueError('source ratio mismatch')
                ratios.append(ratio)
                if alarm(ratios,weak)!=metric['signal']:raise ValueError('source alarm differs from rule')
                consecutive=0
                for previous in reversed(ratios):
                    if previous is None or previous>=.95:break
                    consecutive+=1
                metric['consecutive_weeks']=consecutive
                metric['baseline_available']=base is not None
                history.append(value);checked+=1
    return {'checked_alerts':checked,'matched_alerts':checked,'rule_version':'card-8week-1',
            'baseline':'prior 8 observed weeks; excluded holidays do not become zero observations',
            'ratio_audit':'provided value / provided baseline; displayed ratio retained'}


def load(settings):
    if settings.data_mode=='sample':
        rows=json.loads((settings.data_dir/'weekly-signals.json').read_text())
        source={'synthetic':True,'source':'seeded fixture'}
    else:
        root=settings.data_dir/'seohee';paths=list(root.rglob('card_weekly_signals.csv'))
        if len(paths)!=1:raise ValueError('one weekly source required')
        path=paths[0]
        if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('symlink weekly source')
        raw=path.read_bytes()
        expected=json.loads((root/'import.json').read_text())['files'][path.relative_to(root).as_posix()]
        if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('weekly source checksum mismatch')
        def number(value):
            if value=='':return None
            value=float(value)
            if not isfinite(value) or value<0:raise ValueError('invalid weekly value')
            return value
        rows=[]
        for r in csv.DictReader(raw.decode('utf-8-sig').splitlines()):
            metrics={ind:{'value':number(r[ind]),'baseline':number(r[ind+'_기준선8주']),
                'ratio':number(r[ind+'_비율']),'signal':{'':'none','없음':'none','약':'weak','강':'strong'}[r[ind+'_경보']],
                'source_alarm':r[ind+'_경보']} for ind in INDICATORS}
            rows.append({'sgg':{'서울 강남구':'11230','강원 춘천시':'32010'}[r['시군구']],
                'sex':{'남성':'M','여성':'F'}[r['성']],'age_band':{'20대':'20s','30대':'30s'}[r['연령대']],
                'week':date.fromisoformat(r['주시작']).isoformat(),'metrics':metrics})
        source={'synthetic':False,'source':'card_weekly_signals.csv','sha256':expected}
    if len(rows)!=184 or len({r['week'] for r in rows})!=23:raise ValueError('expected 8 groups × 23 weeks')
    report=audit(rows)
    return {'rows':rows,'weeks':sorted({r['week'] for r in rows}),'metadata':{**source,**report,'youth_only':True}}


def synthetic():
    rows=[]
    for sgg in ('11230','32010'):
        for sex in ('M','F'):
            for age in ('20s','30s'):
                histories={ind:[] for ind in INDICATORS};ratios={ind:[] for ind in INDICATORS}
                for week in range(23):
                    metrics={}
                    for ind in INDICATORS:
                        value=.8 if 8<=week<=10 else 1.0
                        base=median(histories[ind][-8:]) if week>=8 else None
                        ratio=value/base if base else None;ratios[ind].append(ratio)
                        signal=alarm(ratios[ind],.90 if (sgg,sex,age)==('32010','F','20s') else .95)
                        metrics[ind]={'value':value,'baseline':base,'ratio':ratio,'signal':signal,'source_alarm':'synthetic'}
                        histories[ind].append(value)
                    rows.append({'sgg':sgg,'sex':sex,'age_band':age,'week':(date(2025,7,7)+timedelta(weeks=week)).isoformat(),'metrics':metrics})
    return rows


if __name__=='__main__':
    path=config.ROOT/'data/sample/weekly-signals.json'
    path.write_text('[\n'+',\n'.join(json.dumps(r,ensure_ascii=False) for r in synthetic())+'\n]\n')
    print('Generated 184 synthetic weekly observations')
