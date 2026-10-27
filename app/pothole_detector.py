"""One custom Ultralytics model per process, shared by photos and live scans."""
import hashlib
import io
import logging
import math
import os
import threading
import warnings
from pathlib import Path
from PIL import Image, ImageOps, UnidentifiedImageError
from .contracts import Analysis, BoundingBox, DamageDetection

# Ultralytics patches Image.open to auto-register HEIF on unknown input. Keep Pillow's
# decoder for our explicit format allow-list so invalid uploads never install plugins.
_open_image = Image.open

MAX_PHOTO_BYTES = 4 * 1024 * 1024
MAX_PHOTO_PIXELS = 16_000_000
PHOTO_TYPES = {'image/jpeg': 'JPEG', 'image/png': 'PNG', 'image/webp': 'WEBP'}
MODEL_UNAVAILABLE = 'No se pudo cargar el modelo de detección de baches. Contacta al administrador.'
logger = logging.getLogger(__name__)


class ModelUnavailable(RuntimeError):
    pass


def validate_photo(data: bytes, content_type: str) -> Image.Image:
    if not data or len(data) > MAX_PHOTO_BYTES:
        raise ValueError('La imagen debe pesar entre 1 byte y 4 MB.')
    if content_type not in PHOTO_TYPES:
        raise ValueError('Selecciona una imagen JPEG, PNG o WebP.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with _open_image(io.BytesIO(data), formats=['JPEG', 'PNG', 'WEBP']) as image:
                if image.format != PHOTO_TYPES[content_type] or getattr(image, 'n_frames', 1) != 1:
                    raise ValueError('El contenido no corresponde a una imagen JPEG, PNG o WebP estática válida.')
                if min(image.size) < 32 or max(image.size) > 8192 or image.width * image.height > MAX_PHOTO_PIXELS:
                    raise ValueError('La imagen debe tener lados de 32 a 8192 píxeles y como máximo 16 megapíxeles.')
                image.load()
                return ImageOps.exif_transpose(image).convert('RGB')
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning, SyntaxError) as exc:
        raise ValueError('No se pudo leer la imagen. Selecciona un archivo válido.') from exc


class PotholeDetector:
    def __init__(self, settings, model_factory=None):
        self.model = None
        self.model_name = 'best.pt'
        self.device = 'cpu'
        self.names = {}
        self.class_id = settings.yolo_pothole_class_id
        self.confidence = settings.yolo_confidence
        self.image_size = settings.yolo_image_size
        self.lock = threading.Lock()
        try:
            path = Path(settings.pothole_model_path)
            if not path.is_absolute():
                path = Path(__file__).resolve().parents[1] / path
            # Check before calling YOLO: absent files must never trigger a weights download.
            if not path.is_file() or path.suffix.lower() != '.pt':
                raise ValueError('missing_custom_weights')
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != settings.yolo_model_sha256.lower():
                raise ValueError('custom_weights_checksum_mismatch')
            os.environ.setdefault('YOLO_OFFLINE', 'true')
            os.environ.setdefault('YOLO_AUTOINSTALL', 'false')
            os.environ.setdefault('YOLO_VERBOSE', 'false')
            import torch
            from ultralytics import YOLO, settings as yolo_settings
            from ultralytics.utils import LOGGER
            LOGGER.setLevel(logging.ERROR)
            yolo_settings.update({'sync': False})
            torch.set_num_threads(settings.yolo_cpu_threads)
            requested = settings.yolo_device
            if requested == 'cuda' and not torch.cuda.is_available():
                raise ValueError('cuda_unavailable')
            self.device = 'cuda:0' if requested != 'cpu' and torch.cuda.is_available() else 'cpu'
            self.model = (model_factory or YOLO)(str(path), task='detect')
            self.names = {int(key): str(value) for key, value in self.model.names.items()}
            if self.class_id not in self.names or self.model.task != 'detect':
                raise ValueError('pothole_class_missing')
            # The provided single-class checkpoint names class 0 "0". Mapping is explicit in config.
            label = self.names[self.class_id].strip().lower()
            if label not in ('pothole', 'potholes', 'bache', 'baches', str(self.class_id)):
                raise ValueError('unexpected_class_label')
            if model_factory is None:
                with Image.new('RGB', (640, 640), '#888888') as blank:
                    self.detect(blank)  # Initialize predictor once, before serving concurrent requests.
        except Exception:
            self.model = None
            logger.error('custom_pothole_model_unavailable')

    @property
    def ready(self):
        return self.model is not None

    def detect(self, image: Image.Image):
        if not self.ready:
            raise ModelUnavailable(MODEL_UNAVAILABLE)
        # Ultralytics mutates its predictor; serialize all photo/live calls on this shared instance.
        with self.lock:
            predictions = self.model.predict(source=image, conf=self.confidence, device=self.device,
                classes=[self.class_id], imgsz=self.image_size, max_det=100, iou=.45,
                save=False, save_txt=False, show=False, verbose=False)
            result = predictions[0]
            detections = []
            if result.boxes is not None:
                coordinates = result.boxes.xyxy.detach().cpu().tolist()
                confidences = result.boxes.conf.detach().cpu().tolist()
                classes = result.boxes.cls.detach().cpu().tolist()
                for bbox, confidence, class_id in zip(coordinates, confidences, classes):
                    if int(class_id) != self.class_id or confidence < self.confidence or not all(math.isfinite(v) for v in [*bbox, confidence]):
                        continue
                    xmin, ymin = max(0., min(float(bbox[0]), image.width)), max(0., min(float(bbox[1]), image.height))
                    xmax, ymax = max(0., min(float(bbox[2]), image.width)), max(0., min(float(bbox[3]), image.height))
                    if xmax <= xmin or ymax <= ymin:
                        continue
                    detections.append({'clase': 'pothole', 'confianza': round(float(confidence), 6),
                                       'bbox': [round(v, 3) for v in (xmin, ymin, xmax, ymax)]})
            return {'total_baches': len(detections), 'ancho': image.width, 'alto': image.height, 'detecciones': detections}

    def analyze(self, image: Image.Image) -> Analysis:
        result = self.detect(image)
        hits = []
        for item in result['detecciones'][:20]:
            xmin, ymin, xmax, ymax = item['bbox']
            box = BoundingBox(xmin=xmin/image.width*1000, ymin=ymin/image.height*1000,
                              xmax=xmax/image.width*1000, ymax=ymax/image.height*1000)
            area = (xmax-xmin)*(ymax-ymin)/(image.width*image.height)
            hits.append(DamageDetection(boundingBox=box, confidence=item['confianza'],
                hazardScore=85 if area >= .35 else 70 if area >= .18 else 50 if area >= .06 else 35,
                aiDescription=f"Posible bache; confianza de YOLO personalizado {round(item['confianza']*100)}%. Requiere verificación.",
                riskFactors=['Daño visible en la calzada', f'El recuadro ocupa aproximadamente {round(area*100)}% del encuadre', 'Profundidad y dimensiones físicas sin medir']))
        if not hits:
            return Analysis(isPothole=False, potholeType=None, hazardScore=0,
                            aiDescription='No se detectaron baches por encima del umbral de confianza.', riskFactors=[])
        principal = max(hits, key=lambda hit: hit.hazardScore)
        return Analysis(isPothole=True, **principal.model_dump(), detections=hits)
