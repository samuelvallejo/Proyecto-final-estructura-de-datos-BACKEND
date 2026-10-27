"""Community reports contain road information, never the reporter's identity."""
import asyncio
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .auth import current_session
from .contracts import Position
from . import schema as s

router = APIRouter(prefix='/api/community')


class CommunityReport(BaseModel):
    model_config = ConfigDict(extra='forbid')
    position: Position
    capturedAt: int = Field(gt=0)
    risk: Literal['MEDIUM', 'HIGH', 'CRITICAL']
    description: str = Field(min_length=10, max_length=280)

    @field_validator('description')
    @classmethod
    def description_text(cls, value):
        value = value.strip()
        if len(value) < 10 or any(ord(char) < 32 and char not in '\n\t' for char in value):
            raise ValueError('Descripción inválida')
        return value


@router.post('/reports', status_code=201)
async def publish(payload: CommunityReport, request: Request, session=Depends(current_session)):
    if not -5000 <= s.now() - payload.capturedAt <= 30000:
        raise HTTPException(400, 'Actualiza tu ubicación GPS antes de publicar el aviso.')
    zone = await request.app.state.geocoder.resolve(payload.position)
    report, existing = await asyncio.to_thread(request.app.state.repo.save_community_report,
                                              session, payload, zone)
    return {'report': report, 'existing': existing,
            'message': 'Este lugar ya tenía un aviso.' if existing else 'Aviso publicado correctamente.'}
