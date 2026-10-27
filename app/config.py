from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Literal


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    database_url: str = ''
    gemini_api_key: str = ''
    gemini_model: str = 'gemini-3.5-flash-lite'
    ai_provider: str = 'local'
    pothole_model_path: str = 'models/best.pt'
    yolo_model_sha256: str = 'af2ac6ce7bfec72e71643659ac946caf80ced84869e526a60135c457abfbb200'
    yolo_pothole_class_id: int = Field(default=0, ge=0)
    yolo_confidence: float = Field(default=.25, gt=0, le=1, allow_inf_nan=False)
    yolo_device: Literal['auto', 'cpu', 'cuda'] = 'auto'
    yolo_image_size: int = Field(default=640, ge=320, le=1280, multiple_of=32)
    yolo_cpu_threads: int = Field(default=2, ge=1, le=8)
    local_model_path: str = '../backend/models/pothole-seg-640.onnx'
    local_confidence_threshold: float = .55
    cors_origins: str = 'http://localhost:5173,http://127.0.0.1:5173'
    nominatim_url: str = 'https://nominatim.openstreetmap.org'
    nominatim_user_agent: str = ''
    max_scans_per_hour: int = 120
    max_global_scans_per_hour: int = 300
    scan_interval_seconds: float = 5
    max_pending_scans: int = 8
    local_max_scans_per_hour: int = 2400
    local_max_global_scans_per_hour: int = 6000
    local_scan_interval_seconds: float = 1.5
    session_hours: int = 24
    data_encryption_key: str = ''
    secure_cookies: bool = True

    def sqlalchemy_url(self) -> str:
        if not self.database_url:
            raise ValueError('Configura DATABASE_URL con PostgreSQL.')
        for prefix in ('postgres://', 'postgresql://'):
            if self.database_url.startswith(prefix):
                return self.database_url.replace(prefix, 'postgresql+psycopg://', 1)
        if not self.database_url.startswith('postgresql+psycopg://'):
            raise ValueError('DATABASE_URL debe usar PostgreSQL.')
        return self.database_url
