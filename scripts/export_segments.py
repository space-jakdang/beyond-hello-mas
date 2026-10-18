"""Read analysis inputs without executing its scripts; output only to data/local."""
import argparse
import hashlib
import math
from pathlib import Path
import unicodedata

import pandas as pd

from backend.app.config import ROOT
from backend.app.contracts import Segment
from backend.tools.indicators import ratio
from backend.tools.segments import AGES, MONTHS, write_segments

LEGACY_CODES = {'11230740': '11230511'}


def fingerprint(path):
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'name': path.name, 'sha256': digest, 'mtime_ns': path.stat().st_mtime_ns}


def load_flow(files):
    frame = pd.concat([pd.read_csv(path, sep='|', encoding='utf-8-sig',
                                  dtype={'BLOCK_CD': str, 'STD_YM': str}) for path in files])
    # Source H9 confirms December time/wkdy contain exact duplicate records.
    frame = frame.drop_duplicates()
    frame = frame[frame.BLOCK_CD.str[:5].isin(['11230', '32010'])].copy()
    numeric = frame.drop(columns=['BLOCK_CD', 'STD_YM'])
    if numeric.isna().any().any() or not numeric.map(lambda v: isinstance(v, (int, float)) and math.isfinite(v) and v >= 0).all().all():
        raise ValueError('missing or invalid numeric source cells; no implicit zero filling')
    frame['dong'] = frame.BLOCK_CD.str[:8].replace(LEGACY_CODES)
    frame['ym'] = frame.STD_YM.str[:4] + '-' + frame.STD_YM.str[4:]
    if not frame.ym.isin(MONTHS).all():
        raise ValueError('source contains months outside the contract')
    if frame.duplicated(['BLOCK_CD', 'STD_YM', 'X_COORD', 'Y_COORD']).any():
        raise ValueError('conflicting records for one block/coordinate/month')
    return frame


def export(source: Path):
    sk_dirs = [p for p in source.iterdir() if p.is_dir() and
               unicodedata.normalize('NFC', p.name).startswith('2026빅콘테스트_sk')]
    if len(sk_dirs) != 1:
        raise ValueError('expected one SK source directory')
    age_files = sorted(sk_dirs[0].glob('flow_age_pop_*.csv'))
    time_files = sorted(sk_dirs[0].glob('flow_time_pop_*.csv'))
    if not age_files or not time_files:
        raise ValueError('missing SK age/time files')
    mapping_path = source / 'data/external/kostat_한국행정구역분류_2025.10.1.기준.xlsx'
    population_path = source / 'data/external/mois_주민등록_행정동_연령별인구_202507_202512.csv'
    paths = age_files + time_files + [mapping_path, population_path]
    before = [fingerprint(p) for p in paths]
    age, time = load_flow(age_files), load_flow(time_files)
    mapping = pd.read_excel(mapping_path, sheet_name='2-2. 연계표_행정동 및 법정동(기준시점)', header=1, dtype=str)
    mapping.columns = [c.replace('\n', '') for c in mapping.columns]
    mapping = mapping[mapping['행정구역분류'].str.len() == 8][['행정구역분류', '행정동(행정기관명)', '행정기관코드']].drop_duplicates()
    if mapping['행정구역분류'].duplicated().any():
        raise ValueError('ambiguous statistical-to-MOIS code mapping')
    mapping = mapping.set_index('행정구역분류')
    population = pd.read_csv(population_path, encoding='cp949', dtype=str)
    population['mcode'] = population['행정구역'].str.extract(r'\((\d{10})\)')[0]
    population = population.set_index('mcode')
    columns = []
    for band in (10, 20, 30, 40, 50, 60):
        suffix = f'{band}G' if band < 60 else '60GU'
        column = f'P{band}'
        age[column] = age[f'MAN_FLOW_POP_CNT_{suffix}'] + age[f'WMAN_FLOW_POP_CNT_{suffix}']
        columns.append(column)
    totals = age.groupby(['dong', 'ym'])[columns].sum(min_count=1)
    semester = totals.reset_index()
    semester = semester[semester.ym.isin(['2025-09', '2025-10', '2025-11'])].groupby('dong')[columns].agg(['mean', 'count'])
    time['night'] = time[[f'TMST_{h:02}' for h in range(6)]].sum(axis=1, min_count=6)
    time['all'] = time[[f'TMST_{h:02}' for h in range(24)]].sum(axis=1, min_count=24)
    activity = time.groupby(['dong', 'ym'])[['night', 'all']].sum(min_count=1)
    centers = age.drop_duplicates(['BLOCK_CD', 'X_COORD', 'Y_COORD']).groupby('dong')[['X_COORD', 'Y_COORD']].mean()
    rows = []
    for (dong, month), values in totals.iterrows():
        link = mapping.loc[dong]
        resident_row = population.loc[link['행정기관코드']]
        for index, band in enumerate(AGES):
            low = 10 + index * 10
            labels = [f'{low}~{low+9}세'] if low < 60 else [f'{v}~{v+9}세' for v in range(60, 100, 10)] + ['100세 이상']
            prefix = month[:4] + '년' + month[-2:] + '월_계_'
            raw_residents = pd.to_numeric(resident_row[[prefix + label for label in labels]].str.replace(',', ''), errors='coerce')
            residents = int(raw_residents.sum()) if raw_residents.notna().all() else None
            baseline = semester.loc[dong, (columns[index], 'mean')] if (dong in semester.index and semester.loc[dong, (columns[index], 'count')] == 3) else None
            night = ratio(activity.loc[(dong, month), 'night'], activity.loc[(dong, month), 'all']) if (dong, month) in activity.index else None
            indicators = {'age_share': ratio(values[columns[index]], values.sum()),
                          'semester_ratio': ratio(values[columns[index]], baseline), 'night_share': night}
            rows.append(Segment(ym=month, sgg=dong[:5], dong_cd=dong, dong_nm=link['행정동(행정기관명)'],
                age_band=band, x=centers.loc[dong, 'X_COORD'], y=centers.loc[dong, 'Y_COORD'],
                crs='EPSG:5179', coordinate_source='SK UTM-K block centroid mean; no transform',
                indicators=indicators, indicator_version='provisional-1', residents=residents,
                blind_flag=residents is None or residents == 0 or any(v is None for v in indicators.values())))
    if before != [fingerprint(p) for p in paths]:
        raise ValueError('source changed during export; refusing output')
    return write_segments(ROOT / 'data/local/segments.parquet', rows,
        {'data_mode': 'local', 'synthetic': False, 'sources': before, 'mapping_version': 'kostat-2025-10-01+legacy-1',
         'legacy_codes': LEGACY_CODES, 'card_included': False,
         'card_note': 'card not selected pending indicator confirmation; future card inputs exclude AGE_CCD/SEX_CCD=법인 and remain district×age',
         'night_note': 'dong total across all ages, repeated by age; not age-specific',
         'coordinate_note': 'table definition UTM-K; existing analysis uses EPSG:5179; no geographic conversion'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path, help='analysis project root (read only)')
    args = parser.parse_args()
    result = export(args.source.resolve())
    print(f"Exported {result['row_count']} local rows; {len(result['missing_keys'])} missing keys")
