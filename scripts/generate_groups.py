"""Independent synthetic v3 data; no source statistics or real neighborhood identities."""
import random
from backend.app.config import ROOT
from backend.app.contracts import SegmentV3
from backend.tools.segments import MONTHS
from backend.tools.segments_v3 import age_bands, write_segments


def generate(seed=42):
    rng=random.Random(seed);rows=[]
    for month in MONTHS:
        for i in range(47):
            sgg='11230' if i<22 else '32010'
            for sex in ('M','F'):
                for group in ('youth','midlife','prime','elderly'):
                    index=('S1' if group=='youth' else 'G_seoul') if i<22 else ('v3' if group=='youth' else 'G_chuncheon')
                    source='sk_gangnam_s1' if index=='S1' else 'seoul_telecom' if i<22 else 'kosis'
                    rows.append(SegmentV3(ym=month,sgg=sgg,dong_cd=f'{sgg}{i+1:03}',dong_nm=f'합성동{i+1:02}',
                        sex=sex,age_group=group,source_bands={source:age_bands(source,group)},index_name=index,
                        risk_direction='low_is_risk' if index=='S1' else 'high_is_risk',value=round(rng.uniform(.1,.4) if index=='S1' else rng.uniform(-1,1),6),
                        source_stage=None if group=='youth' else rng.randint(1,5),
                        residents=rng.randint(50,5000),source_period=month,source_file='synthetic-generator-3',
                        x=i%8,y=i//8,crs='synthetic-cartesian',coordinate_source='generated grid; not geographic'))
    return rows


if __name__=='__main__':
    rows=generate();write_segments(ROOT/'data/sample/segments-v3.parquet',rows,'sample')
    print(f'Generated {len(rows)} synthetic group segments')
