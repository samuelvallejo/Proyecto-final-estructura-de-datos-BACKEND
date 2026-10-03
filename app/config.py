from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    database_url: str = ''
    gemini_api_key: str = ''
    gemini_model: str = 'gemini-3.5-flash-lite'
    ai_provider: str = 'auto'
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

    def sqlalchemy_url(self) -> str:
        if not self.database_url:
            raise ValueError('Configura DATABASE_URL con PostgreSQL.')
        for prefix in ('postgres://', 'postgresql://'):
            if self.database_url.startswith(prefix):
                return self.database_url.replace(prefix, 'postgresql+psycopg://', 1)
        if not self.database_url.startswith('postgresql+psycopg://'):
            raise ValueError('DATABASE_URL debe usar PostgreSQL.')
        return self.database_url
