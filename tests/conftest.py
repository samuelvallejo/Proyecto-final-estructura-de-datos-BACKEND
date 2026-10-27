import pytest
from app.config import Settings
from app.pothole_detector import PotholeDetector

@pytest.fixture(scope='session')
def custom_detector():
    detector = PotholeDetector(Settings(_env_file=None))
    assert detector.ready, 'The provided custom best.pt must load before integration tests.'
    return detector
