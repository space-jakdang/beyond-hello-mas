"""Regional context is source-specific aggregate evidence, never a welfare denominator."""
from datetime import date
from typing import Literal

from pydantic import Field, HttpUrl, field_validator, model_validator

from backend.app.contracts import Code, Contract, Nonempty, WallTime
from backend.tools.indicators import digest
from backend.tools.neighborhoods import boundaries

METRICS = {
    'total_population': ('총인구', 'persons'),
    'total_households': ('총가구', 'households'),
    'general_households': ('일반가구', 'households'),
    'one_person_households': ('1인가구', 'households'),
    'senior_population': ('65세 이상 인구', 'persons'),
    'youth_population': ('19–34세 인구', 'persons'),
    'total_housing': ('총주택', 'houses'),
    'population_density': ('인구밀도', 'persons_per_km2'),
    'average_age': ('평균연령', 'years'),
}


class ContextRequest(Contract):
    sgg: Literal['11230', '32010']
    dong_cd: Code
    reference_year: int = Field(ge=2000, le=2100, strict=True)
    as_of: date

    @model_validator(mode='after')
    def scope(self):
        if not self.dong_cd.startswith(self.sgg):raise ValueError('region differs from request')
        if self.reference_year > self.as_of.year:raise ValueError('reference year follows analysis date')
        return self


class RegionIdentity(Contract):
    sgg: Literal['11230', '32010']
    dong_cd: Code
    dong_nm: Nonempty
    provider_code: str = Field(pattern=r'^\d{7,8}$')
    boundary_version: Nonempty
    alignment: Literal['parent_and_name_only'] = 'parent_and_name_only'


class ContextFact(Contract):
    metric: str
    value: float | None = Field(ge=0, strict=True)
    unit: Literal['persons', 'households', 'houses', 'persons_per_km2', 'years']
    geography_level: Literal['dong', 'district']
    geography_code: str = Field(pattern=r'^(\d{5}|\d{7,8})$')
    geography_version: Nonempty
    reference_year: int = Field(ge=2000, le=2100, strict=True)
    population: Nonempty
    age_definition: Nonempty = 'all_ages'
    sex: Literal['all', 'M', 'F'] = 'all'
    source: Literal['kosis', 'synthetic_fixture']
    source_table: str | None = None
    source_items: list[str] = Field(default_factory=list,max_length=8)
    source_dimensions: list[str] = Field(default_factory=list,max_length=8)
    source_url: HttpUrl
    source_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    fetched_at: WallTime
    published_at: WallTime | None = None
    status: Literal['observed', 'missing', 'suppressed']
    reason: str | None = None

    @field_validator('metric')
    @classmethod
    def known_metric(cls, value):
        if value not in METRICS:raise ValueError('unknown regional metric')
        return value

    @model_validator(mode='after')
    def definition(self):
        if self.unit != METRICS[self.metric][1]:raise ValueError('metric unit mismatch')
        if len(self.geography_code) not in ((5,) if self.geography_level=='district' else (7,8)):
            raise ValueError('geography level differs from code')
        if (self.value is not None) != (self.status == 'observed'):
            raise ValueError('observation status differs from value')
        if self.value is None and not self.reason:raise ValueError('missing value needs a reason')
        if self.published_at is not None and self.published_at > self.fetched_at:
            raise ValueError('publication follows retrieval')
        if self.value is not None and self.unit in ('persons','households','houses') and not self.value.is_integer():
            raise ValueError('aggregate count must be an integer')
        if self.metric == 'youth_population' and self.age_definition != '19-34':
            raise ValueError('requested youth definition is 19-34')
        if self.metric == 'senior_population' and self.age_definition != '65+':
            raise ValueError('senior definition is 65+')
        return self

    @property
    def fact_id(self):
        # Publication metadata changes the time-bound claim; only retrieval time is identity-neutral.
        content=self.model_dump(mode='json', exclude={'fetched_at'})
        return 'region-'+digest(content)


def resolve_region(request, provider_regions):
    """Use the provider address inventory; truncating our eight-digit IDs is ambiguous."""
    request=ContextRequest.model_validate(request)
    geo, metadata=boundaries()
    local=next((f['properties'] for f in geo['features']
                if f['properties']['dong_cd']==request.dong_cd and f['properties']['sgg']==request.sgg),None)
    if local is None:raise ValueError('unknown administrative neighborhood')
    if sum(f['properties']['dong_nm']==local['dong_nm'] and f['properties']['sgg']==request.sgg for f in geo['features'])!=1:
        raise ValueError('ambiguous local geography')
    codes=[str(r.get('cd','')) for r in provider_regions]
    if len(codes)!=len(set(codes)):raise ValueError('duplicate provider geography')
    matches=[r for r in provider_regions if r.get('addr_name')==local['dong_nm']
             and str(r.get('cd','')).startswith(request.sgg)]
    if len(matches)!=1:raise ValueError('missing or ambiguous provider geography')
    return RegionIdentity(sgg=request.sgg,dong_cd=request.dong_cd,dong_nm=local['dong_nm'],
                          provider_code=matches[0]['cd'],boundary_version=metadata['version'])


def fact_dict(fact):
    fact=ContextFact.model_validate(fact)
    return {**fact.model_dump(mode='json'),'fact_id':fact.fact_id}


def comparable(first: dict, second: dict):
    fields=('metric','unit','geography_level','geography_version','reference_year','population','age_definition','sex','source')
    return all(first[k]==second[k] for k in fields) and all(r['status']=='observed' for r in (first,second))
