import random
from backend.app.config import ROOT
from backend.app.contracts import Segment
from backend.tools.segments import MONTHS, AGES, write_segments


def generate(seed=42):
    rng = random.Random(seed)
    rows = []
    for month in MONTHS:
        for i in range(47):
            district = '11230' if i < 22 else '32010'
            night_share = round(rng.uniform(0.05, 0.5), 6)
            shares = [rng.uniform(0.05, 0.4) for _ in AGES]
            for age, share in zip(AGES, shares):
                rows.append(Segment(ym=month, sgg=district, dong_cd=f'{district}{i+1:03}',
                    dong_nm=f'합성동{i+1:02}', age_band=age, x=float(i % 8), y=float(i // 8),
                    crs='synthetic-cartesian', coordinate_source='generated grid; not geographic',
                    indicators={'age_share': share / sum(shares),
                                'semester_ratio': round(rng.uniform(0.3, 1.6), 6),
                                'night_share': night_share},
                    indicator_version='provisional-1', residents=rng.randint(50, 5000), blind_flag=False))
    return rows


if __name__ == '__main__':
    metadata = write_segments(ROOT / 'data/sample/segments.parquet', generate(),
                              {'data_mode': 'sample', 'seed': 42, 'generator_version': '1',
                               'synthetic': True, 'code_note': 'synthetic codes, not official dong identities'})
    print(f"Generated {metadata['row_count']} synthetic segments")
