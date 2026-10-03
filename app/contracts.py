from typing import Literal
from pydantic import BaseModel, Field, model_validator


class BoundingBox(BaseModel):
    ymin: float = Field(ge=0, le=1000)
    xmin: float = Field(ge=0, le=1000)
    ymax: float = Field(ge=0, le=1000)
    xmax: float = Field(ge=0, le=1000)

    @model_validator(mode='after')
    def ordered(self):
        if self.xmax <= self.xmin or self.ymax <= self.ymin:
            raise ValueError('Bounding box inválido')
        return self


class Analysis(BaseModel):
    isPothole: bool
    potholeType: Literal['BACHE', 'HUNDIMIENTO', 'GRIETA', 'OTRO_DANO'] | None
    hazardScore: int = Field(ge=0, le=100)
    aiDescription: str = Field(min_length=1, max_length=500)
    riskFactors: list[str] = Field(max_length=5)
    boundingBox: BoundingBox | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode='after')
    def coherent(self):
        self.riskFactors = list(dict.fromkeys(f.strip()[:200] for f in self.riskFactors if f.strip()))
        if not self.isPothole:
            self.potholeType = None
            self.hazardScore = 0
            self.riskFactors = []
            self.boundingBox = None
        elif self.potholeType is None:
            raise ValueError('Falta tipo de daño')
        return self

    def result(self):
        score = self.hazardScore
        return {**self.model_dump(), 'hazardLevel':
                'CRITICAL' if score >= 80 else 'HIGH' if score >= 60 else 'MEDIUM' if score >= 35 else 'LOW'}


class Position(BaseModel):
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lng: float = Field(ge=-180, le=180, allow_inf_nan=False)
    accuracy: float = Field(ge=0, le=100, allow_inf_nan=False)
