"""Join the immutable local bundle to existing statistical dong identities."""
import csv
import json
import unicodedata
from statistics import mean, stdev
from backend.app.config import ROOT, Settings
from backend.app.contracts import SegmentV3
from backend.tools.segments import load_segments
from backend.tools.segments_v3 import age_bands, write_segments
from backend.tools.region_stage import rank_stage
from scripts.import_seohee import inventory

GROUPS={'청년':'youth','중년':'midlife','장년':'prime','노년':'elderly'}
SEX={'남':'M','여':'F'}


def export(settings):
    if settings.data_mode!='local':raise ValueError('source import requires local mode')
    root=settings.data_dir/'seohee';manifest=json.loads((root/'import.json').read_text())
    original=inventory(root);hashes=dict(original);hashes.pop('import.json',None)
    if hashes!=manifest['files']:raise ValueError('source bundle checksum mismatch')
    files={unicodedata.normalize('NFC',p.name):p for p in root.rglob('*.csv')}
    def read(name):
        with files[name].open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
        keys=[tuple(r.get(k,'') for k in ('자치구','행정동','읍면동','성','4집단')) for r in rows]
        if len(keys)!=len(set(keys)):raise ValueError('duplicate source group')
        return rows
    legacy,_=load_segments(settings)
    locations={(r.sgg,r.dong_nm):r for r in legacy}
    seoul={(r['행정동'],SEX[r['성']],GROUPS[r['4집단']]):r for r in read('group_dong_index_seoul.csv') if r['자치구']=='강남구'}
    ranks={(r['행정동'],SEX[r['성']],GROUPS[r['4집단']]):r for r in read('gangnam_within_rank.csv')}
    s1={r['행정동']:r for r in read('gangnam_S1.csv')}
    youth={r['읍면동']:r for r in read('chuncheon_youth_risk_v3.csv')}
    cc={(r['읍면동'],SEX[r['성']],GROUPS[r['4집단']]):r for r in read('group_dong_index_chuncheon.csv')}
    # Source standardizes each branch and the weighted sum within each sex/age cohort.
    for sex in SEX.values():
        for group in GROUPS.values():
            cohort=[r for (_,sx,g),r in cc.items() if sx==sex and g==group]
            def z(values):
                center,spread=mean(values),stdev(values)
                return [(v-center)/spread for v in values]
            structure=z([float(r['구조_위험']) for r in cohort]);visibility=z([float(r['가시성_위험']) for r in cohort])
            expected=z([.7*a+.3*b for a,b in zip(structure,visibility)])
            if any(abs(v-float(r['지수']))>.001 for v,r in zip(expected,cohort)):
                raise ValueError('Chuncheon source weighting mismatch')
    revised={group:{(r['행정동'],SEX[r['성']]):r for r in read(name) if r['자치구']=='강남구'} for group,name in (
        ('prime','장년_dong_index_seoul_v2.csv'),('elderly','elderly_dong_index_seoul_v2.csv'))}
    output=[]
    for (sgg,name),location in sorted(locations.items()):
        display_name=name
        if location.dong_cd=='11230511':name='일원2동'  # Existing verified legacy code mapping in export_segments.
        for sex in ('M','F'):
            for group in GROUPS.values():
                flags=['regions_not_comparable','period_aggregate'];components={};stage=None;rank=None
                if sgg=='11230':
                    base=seoul.get((name,sex,group),{})
                    pop=float(base['월평균인구']) if base else None
                    if base.get('인구적음')=='1':flags.append('small_population')
                    if group=='youth':
                        source='gangnam_S1.csv';record=s1.get(name,{})
                        value=float(record['S1_주거지청년가시성']) if record else None
                        index='S1';bands={k:age_bands(k,group) for k in ('sk_gangnam_s1','seoul_telecom')}
                        flags.append('index_not_sex_specific')
                        if name.startswith('대치'):flags.append('academy_area')
                    else:
                        source={'prime':'장년_dong_index_seoul_v2.csv','elderly':'elderly_dong_index_seoul_v2.csv'}.get(group,'group_dong_index_seoul.csv')
                        record=revised[group].get((name,sex),{}) if group in revised else base
                        value=float(record.get('지수v2',record.get('지수'))) if record else None
                        stage=int(record.get('단계v2',record.get('단계'))) if record else None
                        index='G_seoul';bands={'seoul_telecom':age_bands('seoul_telecom',group)}
                else:
                    record=cc.get((name,sex,group),{})
                    pop=float(record['주민']) if record else None
                    if record.get('인구적음')=='1':flags.append('small_population')
                    if record.get('두갈래일치')=='1':flags.append('two_branches_agree')
                    if group=='youth':
                        source='chuncheon_youth_risk_v3.csv';record=youth.get(name,{});pop=None
                        value=float(record['위험조건점수_v3']) if record else None
                        components={'youth_population_both_sexes':float(record['청년_20_34_수'])} if record else {}
                        if components.get('youth_population_both_sexes',1000)<100:flags.append('small_population')
                        flags+=['index_not_sex_specific','welfare_rate_2017']
                        index='v3';bands={'kosis':age_bands('kosis',group)}
                    else:
                        source='group_dong_index_chuncheon.csv';index='G_chuncheon'
                        bands={k:age_bands(k,group) for k in ('kosis','sk_chuncheon')}
                        value=float(record['지수']) if record else None
                        stage=int(record['단계']) if record else None
                        components={k:float(record[col]) for k,col in [('structure','구조_위험'),('visibility_risk','가시성_위험')]} if record else {}
                if value is None:flags+=['missing','blind']
                row=SegmentV3(ym=None,sgg=sgg,dong_cd=location.dong_cd,dong_nm=display_name,source_dong_nm=name,sex=sex,age_group=group,
                    source_bands=bands,index_name=index,risk_direction='low_is_risk' if index=='S1' else 'high_is_risk',
                    value=value,residents=pop,flags=sorted(set(flags)),source_stage=stage,components=components,
                    preferred=not(sgg=='11230' and group!='youth'),
                    source_period='2026-10-18 전달 집계 · 월별 관측 아님',source_file=source,
                    x=location.x,y=location.y,crs=location.crs,coordinate_source=location.coordinate_source)
                output.append(row)
                if sgg=='11230' and group!='youth':
                    rr=ranks.get((name,sex,group),{})
                    rank=int(rr['강남내순위']) if rr else None
                    if rr and rank_stage(rank)!=int(rr['강남내단계']):raise ValueError('Gangnam rank rule mismatch')
                    output.append(row.model_copy(update={'index_name':'G_gangnam_rank','value':float(rr['지수']) if rr else None,
                        'source_stage':rank_stage(rank) if rank else None,'within_rank':rank,'preferred':True,
                        'source_file':'gangnam_within_rank.csv','components':{},'flags':sorted(set(flags+([] if rr else ['missing','blind'])))}))
    if len({r.dong_cd for r in output})!=47 or sum(r.preferred for r in output)!=376:raise ValueError('expected 47 × 8 primary groups')
    if inventory(root)!=original:raise ValueError('source changed during export')
    write_segments(settings.data_dir/'segments-v3.parquet',output,'local')
    return output


if __name__=='__main__':
    rows=export(Settings(data_mode='local'))
    print(f'Exported {len(rows)} rows, including comparison indices, to local v3 input')
