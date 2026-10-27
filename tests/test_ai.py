import asyncio
import io
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from PIL import Image
from pydantic import ValidationError
from app.ai import LocalDetector, AIService, validate_image
from app.config import Settings
from app.contracts import Analysis, Position

FIXTURE = Path(__file__).parents[2] / 'backend/tests/fixtures/pothole.jpg'


def test_detector_on_real_pothole_and_blank_frame():
    model = LocalDetector('../backend/models/pothole-seg-640.onnx')
    result = model.analyze(validate_image(FIXTURE.read_bytes()))
    assert result.isPothole and result.potholeType == 'BACHE'
    assert result.confidence > .55
    assert 0 < result.hazardScore <= 100
    assert not model.analyze(Image.new('RGB', (640, 480), '#888888')).isPothole
    assert not model.analyze(Image.new('RGB', (640, 480), '#080808')).isPothole


def test_legacy_two_class_detector_remains_compatible():
    model = LocalDetector('../backend/models/pothole2v_320.onnx')
    assert model.analyze(validate_image(FIXTURE.read_bytes())).isPothole


def test_multiple_detections_suppress_duplicate_boxes():
    import numpy as np
    detector = LocalDetector.__new__(LocalDetector)
    detector.input_width = detector.input_height = 320
    detector.class_count = 1
    detector.pothole_class = 0
    detector.threshold = .55
    detector.input = SimpleNamespace(name='image')
    output = np.array([[[100, 105, 250], [100, 105, 250], [80, 80, 50], [80, 80, 50], [.95, .90, .80]]], dtype=np.float32)
    detector.session = SimpleNamespace(run=lambda *_: [output])
    result = detector.analyze(Image.new('RGB', (320, 320)))
    assert len(result.detections) == 2
    assert [round(hit.confidence, 2) for hit in result.detections] == [.95, .80]


@pytest.mark.skipif(not os.environ.get('TEST_PHONE_FRAME_DIR'), reason='Grabación privada no incluida en el repositorio')
def test_phone_recording_regression():
    model = LocalDetector('../backend/models/pothole-seg-640.onnx')
    directory = Path(os.environ['TEST_PHONE_FRAME_DIR'])
    # Fotogramas separados, con movimiento y escalas diferentes; sin entrenar
    # ni reducir el umbral a partir de esta grabación.
    for name in ['frame-01-road.jpg', 'frame-03-road.jpg', 'frame-05-road.jpg', 'frame-08-road.jpg', 'frame-12-road.jpg']:
        result = model.analyze(validate_image((directory / name).read_bytes()))
        assert result.isPothole, name
        assert result.confidence >= .55 and result.boundingBox is not None
        assert result.hazardScore >= 60


@pytest.mark.parametrize('values', [{'lat': float('nan'), 'lng': 1, 'accuracy': 1}, {'lat': 91, 'lng': 1, 'accuracy': 1}, {'lat': 0, 'lng': 0, 'accuracy': 101}])
def test_reject_invalid_gps(values):
    with pytest.raises(ValidationError):
        Position(**values)


def test_bad_images_and_inconsistent_ai_payload():
    for data in (b'', b'x' * 850001, b'not-an-image'):
        with pytest.raises(ValueError):
            validate_image(data)
    buffer = io.BytesIO()
    Image.new('RGB', (50, 50)).save(buffer, 'PNG')
    with pytest.raises(ValueError):
        validate_image(buffer.getvalue())
    result = Analysis(isPothole=False, potholeType='BACHE', hazardScore=100,
                      aiDescription='No hay daño', riskFactors=['inventado'])
    assert result.hazardScore == 0 and result.potholeType is None and result.riskFactors == []


def test_camera_uses_exclusively_custom_weights(monkeypatch, custom_detector):
    monkeypatch.setattr('app.ai.PotholeDetector', lambda settings: custom_detector)
    async def run():
        service = AIService(Settings(_env_file=None, ai_provider='auto', gemini_api_key='unused'))
        data = FIXTURE.read_bytes()
        first = await service.analyze(data, validate_image(data))
        second = await service.analyze(data, validate_image(data))
        assert first[1] == second[1] == 'local-yolo'
        assert first[2] == 'best.pt' and first[3] is False
        assert service.local is custom_detector
        assert service.settings.ai_provider == 'local'
    asyncio.run(run())


def test_camera_missing_custom_model_never_falls_back(monkeypatch):
    from app.pothole_detector import ModelUnavailable
    class Missing:
        def analyze(self, image):
            raise ModelUnavailable('model unavailable')
    monkeypatch.setattr('app.ai.PotholeDetector', lambda settings: Missing())
    async def run():
        service = AIService(Settings(_env_file=None))
        data = FIXTURE.read_bytes()
        with pytest.raises(ModelUnavailable):
            await service.analyze(data, validate_image(data))
    asyncio.run(run())
