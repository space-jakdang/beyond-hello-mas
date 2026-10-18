"""Version 3 group inputs; legacy segment files remain readable by their v1 pipeline."""
import json
from itertools import product
from typing import get_args
import pyarrow as pa
import pyarrow.parquet as pq
from backend.app import config
from backend.app.contracts import AgeGroup, SegmentV3
from backend.tools.indicators import digest
from backend.tools.segments import MONTHS


def age_bands(source,group):
    return json.loads((config.ROOT/'rules/age_crosswalk.json').read_text())[source][group]


def validate(rows,complete=False):
    keys=[(r.ym,r.dong_cd,r.sex,r.age_group,r.index_name) for r in rows]
    if not rows or len(set(keys))!=len(keys):raise ValueError('empty or duplicate v3 segments')
    if complete:
        actual={(r.ym,r.dong_cd,r.sex,r.age_group) for r in rows}
        dongs={r.dong_cd for r in rows}
        expected=set(product(MONTHS,dongs,('M','F'),get_args(AgeGroup)))
        if len(dongs)!=47 or actual!=expected or len(rows)!=2256:
            raise ValueError('sample requires 47 dongs × 8 groups × 6 months')
    return rows


def write_segments(path,rows,data_mode):
    rows=validate(rows,complete=data_mode=='sample')
    values=[r.model_dump(mode='json') for r in rows]
    metadata={'schema_version':'3','data_mode':data_mode,'input_hash':digest(values),'synthetic':data_mode=='sample'}
    table=pa.Table.from_pylist(values)
    table=table.replace_schema_metadata({b'beyond_hello':json.dumps(metadata).encode()})
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp');pq.write_table(table,tmp);tmp.replace(path)
    return metadata


def load_segments(settings):
    table=pq.read_table(settings.data_dir/'segments-v3.parquet')
    metadata=json.loads(table.schema.metadata[b'beyond_hello'])
    if metadata['schema_version']!='3' or metadata['data_mode']!=settings.data_mode:raise ValueError('v3 mode/version mismatch')
    values=table.to_pylist()
    for row in values:
        # Arrow structs fill absent source keys with null across heterogeneous rows.
        row['source_bands']={k:v for k,v in row['source_bands'].items() if v is not None}
    rows=validate([SegmentV3.model_validate(r) for r in values],settings.data_mode=='sample')
    if digest([r.model_dump(mode='json') for r in rows])!=metadata['input_hash']:raise ValueError('v3 checksum mismatch')
    return rows,metadata
