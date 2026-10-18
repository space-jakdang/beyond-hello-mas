import json
from pathlib import Path
from typing import get_args

import pyarrow as pa
import pyarrow.parquet as pq

from backend.app.config import Settings
from backend.app.contracts import AgeBand, Segment
from backend.tools.indicators import digest

MONTHS = tuple(f'2025-{m:02}' for m in range(7, 13))
AGES = get_args(AgeBand)


def key(row):
    return row.ym, row.dong_cd, row.age_band


def validate(rows, complete=False):
    rows = sorted(rows, key=key)
    keys = [key(r) for r in rows]
    if len(set(keys)) != len(keys):
        raise ValueError('duplicate segment key')
    dongs = sorted({r.dong_cd for r in rows})
    present = set(keys)
    missing = [(month, dong, age) for month in MONTHS for dong in dongs for age in AGES
               if (month, dong, age) not in present]
    if complete and (len(dongs) != 47 or missing or len(rows) != 1692):
        raise ValueError('complete sample requires 47 dongs × 6 ages × 6 months')
    if not rows:
        raise ValueError('empty segment dataset')
    return rows, {'missing_keys': missing, 'dong_count': len(dongs), 'row_count': len(rows),
                  'missing_months': sorted(set(MONTHS) - {r.ym for r in rows})}


def write_segments(path: Path, rows, metadata):
    rows, coverage = validate(rows, complete=metadata['data_mode'] == 'sample')
    values = [r.model_dump(mode='json') for r in rows]
    metadata = {**metadata, **coverage, 'schema_version': '2', 'input_hash': digest(values)}
    table = pa.Table.from_pylist(values)
    table = table.replace_schema_metadata({b'beyond_hello': json.dumps(metadata, ensure_ascii=False).encode()})
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    pq.write_table(table, temporary)
    temporary.replace(path)
    return metadata


def load_segments(settings: Settings):
    path = settings.data_dir / 'segments.parquet'
    table = pq.read_table(path)  # Missing local input is an error, never a sample fallback.
    metadata = json.loads((table.schema.metadata or {})[b'beyond_hello'])
    if metadata.get('data_mode') != settings.data_mode:
        raise ValueError('dataset mode differs from selected DATA_MODE')
    rows, coverage = validate([Segment.model_validate(r) for r in table.to_pylist()],
                              complete=settings.data_mode == 'sample')
    if digest([r.model_dump(mode='json') for r in rows]) != metadata['input_hash']:
        raise ValueError('dataset checksum mismatch')
    return rows, {**metadata, **coverage}
