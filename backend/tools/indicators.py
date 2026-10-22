"""Provisional, deterministic aggregate signals; never a personal diagnosis."""
import hashlib
import json
import math
from typing import Literal

from pydantic import Field, model_validator
from backend.app.contracts import Contract, Nonempty


class Indicator(Contract):
    name: Nonempty
    direction: Literal['higher', 'lower']
    minimum: float
    maximum: float
    spatial_unit: Literal['dong_age', 'dong_all_ages', 'district_age']

    @model_validator(mode='after')
    def bounds(self):
        if self.minimum >= self.maximum:
            raise ValueError('indicator minimum must be below maximum')
        return self


class Rules(Contract):
    version: Nonempty = 'provisional-1'
    indicators: list[Indicator] = Field(min_length=3, max_length=4)
    change_threshold: float = Field(default=0.2, gt=0)

    @model_validator(mode='after')
    def unique(self):
        if len({i.name for i in self.indicators}) != len(self.indicators):
            raise ValueError('duplicate indicator names')
        return self


def default_rules():
    return Rules(indicators=[
        Indicator(name='age_share', direction='lower', minimum=0, maximum=1, spatial_unit='dong_age'),
        Indicator(name='semester_ratio', direction='lower', minimum=0, maximum=5, spatial_unit='dong_age'),
        Indicator(name='night_share', direction='higher', minimum=0, maximum=1, spatial_unit='dong_all_ages'),
    ])


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def ratio(numerator, denominator):
    if numerator is None or denominator is None or denominator <= 0:
        return None
    if not math.isfinite(numerator) or not math.isfinite(denominator):
        return None
    return numerator / denominator
