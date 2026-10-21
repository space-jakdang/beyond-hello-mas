"""Validate saved judge results without importing optional RAGAS dependencies."""
import json
from typing import Literal
from pydantic import Field, model_validator
from eval.quality_contracts import Contract
from eval.quality_metrics import validate_predictions
from backend.tools.indicators import digest


class Metric(Contract):
    value: float | None = Field(ge=0,le=1,allow_inf_nan=False)
    state: Literal['evaluated','not_evaluated','failed']
    reason: str | None = None
    error_type: str | None = None

    @model_validator(mode='after')
    def consistent(self):
        if (self.state=='evaluated') != (self.value is not None):raise ValueError('invalid judge metric state')
        return self


class JudgeRow(Contract):
    case_id: str
    source_run_id: str
    source_call_key: str
    source_hash: str
    role: str
    metrics: dict[Literal['faithfulness','context_precision','context_recall'],Metric]


class Cost(Contract):
    calls: int = Field(ge=0)
    reserved_usd: float = Field(ge=0,allow_inf_nan=False)
    known_usd: float = Field(ge=0,allow_inf_nan=False)
    unknown_cost_calls: int = Field(ge=0)


class Grounding(Contract):
    schema_version: Literal['6']
    dataset_hash: str
    prediction_hash: str
    reference_hash: str
    references: dict[str,str]
    judge_run_id: str
    judge_model: str
    ragas_version: Literal['0.4.3']
    state: Literal['partial','evaluated']
    rows: list[JudgeRow]
    human_judge_alignment: None
    cost: Cost
    limitations: list[str]


def load_grounding(folder,frozen,predictions,case_ids):
    files=list(folder.glob('grounding-*.json'))
    if not files:return None
    path=max(files,key=lambda p:p.stat().st_mtime)
    if path.is_symlink():raise ValueError('judge symlink not allowed')
    data=Grounding.model_validate(json.loads(path.read_text()))
    outputs=validate_predictions(frozen,predictions)
    if data.dataset_hash!=frozen['dataset_hash'] or data.prediction_hash!=digest(outputs.model_dump()) or data.reference_hash!=digest(data.references):
        raise ValueError('judge result input versions differ')
    runs={p.case_id:p.run_id for p in outputs.predictions};seen=set()
    for row in data.rows:
        key=(row.case_id,row.source_call_key)
        if row.case_id not in runs or runs[row.case_id]!=row.source_run_id or key in seen:
            raise ValueError('judge source mapping differs')
        seen.add(key)
    body=data.model_dump();body.pop('references')
    body['rows']=[r for r in body['rows'] if r['case_id'] in case_ids]
    body['cost_scope']='whole_judge_run_before_filters'
    return body
