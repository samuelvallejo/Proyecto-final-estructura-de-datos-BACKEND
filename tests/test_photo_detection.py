import hashlib
import io
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
import pytest
import torch
from PIL import Image
from app.config import Settings
from app.pothole_detector import PotholeDetector, ModelUnavailable, validate_photo, MAX_PHOTO_BYTES
from test_postgres_api import client, token

FIXTURE = Path(__file__).parent / 'fixtures' / 'pothole.jpg'

def photo(client, data=None, content_type='image/jpeg'):
    return client.post('/api/detect/potholes', files={'image': ('road.jpg', FIXTURE.read_bytes() if data is None else data, content_type)})

def image_bytes(format='JPEG', size=(320, 200), exif=None):
    buffer = io.BytesIO()
    Image.new('RGB', size, '#888888').save(buffer, format, **({'exif': exif} if exif else {}))
    return buffer.getvalue()

def test_provided_model_checksum_class_mapping_and_actual_inference(custom_detector):
    assert hashlib.sha256((FIXTURE.parents[2] / 'models' / 'best.pt').read_bytes()).hexdigest() == Settings(_env_file=None).yolo_model_sha256
    assert custom_detector.names == {0: '0'}  # Actual metadata; never pretend the checkpoint says pothole.
    assert custom_detector.class_id == 0 and custom_detector.device == 'cpu'
    with Image.open(FIXTURE) as image:
        result = custom_detector.detect(image)
    assert result['ancho'] == 960 and result['alto'] == 640 and result['total_baches'] >= 1
    assert all(item['clase'] == 'pothole' and .25 <= item['confianza'] <= 1 for item in result['detecciones'])
    assert custom_detector.detect(Image.new('RGB', (320, 200), '#888888'))['total_baches'] == 0

def test_upload_authenticated_contract_and_pixels(client):
    assert photo(client).status_code == 401
    token(client)
    reply = photo(client)
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert set(body) == {'total_baches', 'ancho', 'alto', 'detecciones'}
    assert body['total_baches'] == len(body['detecciones']) >= 1
    for detection in body['detecciones']:
        x1, y1, x2, y2 = detection['bbox']
        assert 0 <= x1 < x2 <= body['ancho'] and 0 <= y1 < y2 <= body['alto']
        assert detection['clase'] == 'pothole' and .25 <= detection['confianza'] <= 1
    assert client.get('/api/reports').json()['total'] == 0  # A photo does not invent geographic reports.

@pytest.mark.parametrize(('format', 'mime'), [('JPEG', 'image/jpeg'), ('PNG', 'image/png'), ('WEBP', 'image/webp')])
def test_empty_detections_all_supported_formats(client, format, mime):
    token(client)
    reply = photo(client, image_bytes(format), mime)
    assert reply.status_code == 200
    assert reply.json() == {'total_baches': 0, 'ancho': 320, 'alto': 200, 'detecciones': []}

def test_upload_validation_and_model_error_are_safe(client, monkeypatch):
    token(client)
    assert photo(client, b'not-an-image').status_code == 400
    assert photo(client, b'', 'image/jpeg').status_code == 400
    assert photo(client, b'<svg/>', 'image/svg+xml').status_code == 415
    assert photo(client, b'x' * (MAX_PHOTO_BYTES + 1)).status_code == 413
    assert photo(client, image_bytes(size=(16, 32))).status_code == 400
    assert photo(client, image_bytes('PNG'), 'image/jpeg').status_code == 400
    assert client.post('/api/detect/potholes').status_code == 422
    monkeypatch.setattr(client.app.state.detector, 'model', None)
    reply = photo(client)
    assert reply.status_code == 503 and 'modelo' in reply.json()['error']
    assert 'Traceback' not in reply.text and 'models/' not in reply.text

def test_oriented_original_dimensions():
    exif = Image.Exif(); exif[274] = 6
    with validate_photo(image_bytes(size=(80, 160), exif=exif), 'image/jpeg') as image:
        assert image.size == (160, 80)

def test_valid_photo_larger_than_one_megabyte(client):
    import numpy as np
    token(client)
    pixels = np.random.default_rng(42).integers(0, 256, size=(1080, 1920, 3), dtype=np.uint8)
    buffer = io.BytesIO()
    Image.fromarray(pixels).save(buffer, 'JPEG', quality=95)
    data = buffer.getvalue()
    assert 1024 * 1024 < len(data) <= MAX_PHOTO_BYTES
    reply = photo(client, data)
    assert reply.status_code == 200, reply.text
    assert (reply.json()['ancho'], reply.json()['alto']) == (1920, 1080)

def test_missing_or_wrong_weights_do_not_download(tmp_path):
    missing = PotholeDetector(Settings(_env_file=None, pothole_model_path=str(tmp_path/'best.pt')))
    assert not missing.ready
    with pytest.raises(ModelUnavailable):
        missing.detect(Image.new('RGB', (64, 64)))
    wrong = PotholeDetector(Settings(_env_file=None, yolo_model_sha256='0' * 64))
    assert not wrong.ready

def test_single_load_reused_predictor_and_clipped_pixels():
    state = {'loads': 0, 'active': 0, 'peak': 0}
    def predict(**kwargs):
        assert kwargs['conf'] == .25 and kwargs['save'] is False and kwargs['classes'] == [0]
        state['active'] += 1; state['peak'] = max(state['peak'], state['active'])
        time.sleep(.02); state['active'] -= 1
        return [SimpleNamespace(boxes=SimpleNamespace(xyxy=torch.tensor([[-1., -2., 500., 500.]]), conf=torch.tensor([.9]), cls=torch.tensor([0.])))]
    def factory(path, task):
        state['loads'] += 1
        return SimpleNamespace(names={0: '0'}, task=task, predict=predict)
    detector = PotholeDetector(Settings(_env_file=None), model_factory=factory)
    with ThreadPoolExecutor(2) as executor:
        results = list(executor.map(lambda _: detector.detect(Image.new('RGB', (320, 200))), range(2)))
    assert state['loads'] == state['peak'] == 1
    assert results[0]['detecciones'][0]['bbox'] == [0., 0., 320., 200.]

def test_photo_inference_does_not_block_api_event_loop(client, monkeypatch):
    token(client)
    started, finish = threading.Event(), threading.Event()
    def slow(image):
        started.set(); finish.wait(5)
        return {'total_baches': 0, 'ancho': image.width, 'alto': image.height, 'detecciones': []}
    monkeypatch.setattr(client.app.state.detector, 'detect', slow)
    with ThreadPoolExecutor(1) as executor:
        job = executor.submit(photo, client)
        assert started.wait(3)
        try:
            before = time.monotonic()
            assert client.get('/api/health').status_code == 200
            assert time.monotonic() - before < 1
        finally:
            finish.set()
        assert job.result().status_code == 200
