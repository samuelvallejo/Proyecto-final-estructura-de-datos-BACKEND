"""Community reports contain road information, never the reporter's identity."""
import asyncio
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from . import schema as s
from .auth import SessionGuard
from .contracts import Position


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
            raise ValueError('Invalid description')
        return value


class CommunityController:
    """POST /api/community/reports: a user marks a pothole at their current GPS position."""
    MAX_POSITION_AGE_MS, MAX_CLOCK_SKEW_MS = 30_000, 5_000

    def __init__(self):
        self.router = APIRouter(prefix='/api/community')
        self.router.add_api_route('/reports', self.publish, methods=['POST'], status_code=201)

    async def publish(self, payload: CommunityReport, request: Request, session=Depends(SessionGuard.current)):
        age = s.Clock.now() - payload.capturedAt
        if not -self.MAX_CLOCK_SKEW_MS <= age <= self.MAX_POSITION_AGE_MS:
            raise HTTPException(400, 'Actualiza tu ubicación GPS antes de publicar el aviso.')
        zone = await request.app.state.geocoder.resolve(payload.position)
        report, existing = await asyncio.to_thread(request.app.state.repo.save_community_report, session, payload, zone)
        return {'report': report, 'existing': existing,
                'message': 'Este lugar ya tenía un aviso.' if existing else 'Aviso publicado correctamente.'}
