"""AI service: the custom YOLO detector plus the legacy ONNX detector kept for compatibility."""
import asyncio
import ast
import io
import threading
import time
from pathlib import Path
import numpy as np
from PIL import Image, ImageOps
from .contracts import Analysis, BoundingBox, DamageDetection
from .structures import SinglyLinkedList
from .pipeline import LatencyWindow
from .pothole_detector import PotholeDetector
_open_image = Image.open


class FrameValidator:
    """Validates live camera frames: JPEG only, 32–4096 px per side, at most 850 KB."""
    MAX_BYTES = 850_000

    @classmethod
    def validate(cls, data: bytes) -> Image.Image:
        if not data or len(data) > cls.MAX_BYTES:
            raise ValueError('El fotograma debe pesar entre 1 byte y 850 KB.')
        try:
            with _open_image(io.BytesIO(data), formats=['JPEG']) as image:
                if image.format != 'JPEG' or max(image.size) > 4096 or min(image.size) < 32:
                    raise ValueError('Se requiere JPEG de entre 32 y 4096 píxeles por lado.')
                image.load()
                return ImageOps.exif_transpose(image).convert('RGB')
        except (OSError, Image.DecompressionBombError) as exc:
            raise ValueError('El fotograma JPEG está dañado.') from exc


class LocalDetector:
    def __init__(self, model_path: str, threshold: float = .55):
        import onnxruntime as ort  # Legacy ONNX compatibility; not loaded by the deployed detector.
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        self.session = ort.InferenceSession(str(Path(model_path).resolve()), options,
                                            providers=['CPUExecutionProvider'])
        self.model_name = Path(model_path).stem
        self.threshold = threshold
        self.input = self.session.get_inputs()[0]
        self.input_height, self.input_width = self.input.shape[-2:]
        if not isinstance(self.input_height, int) or not isinstance(self.input_width, int):
            raise RuntimeError('El detector requiere un modelo ONNX de resolución fija.')
        names = ast.literal_eval(self.session.get_modelmeta().custom_metadata_map.get('names', "{0: 'pothole'}"))
        self.class_count = len(names)
        self.pothole_class = next((int(i) for i, name in names.items() if str(name).lower() == 'pothole'), None)
        if self.pothole_class is None:
            raise RuntimeError('El modelo no declara una clase pothole.')

    @staticmethod
    def iou(a: BoundingBox, b: BoundingBox) -> float:
        """Intersection over union of two boxes in 0–1000 coordinates."""
        intersection = max(0, min(a.xmax, b.xmax) - max(a.xmin, b.xmin)) * max(0, min(a.ymax, b.ymax) - max(a.ymin, b.ymin))
        union = (a.xmax - a.xmin) * (a.ymax - a.ymin) + (b.xmax - b.xmin) * (b.ymax - b.ymin) - intersection
        return intersection / union if union else 0

    def analyze(self, image: Image.Image) -> Analysis:
        width, height = image.size
        scale = min(self.input_width / width, self.input_height / height)
        resized_width, resized_height = round(width * scale), round(height * scale)
        offset_x, offset_y = (self.input_width - resized_width) // 2, (self.input_height - resized_height) // 2
        canvas = Image.new('RGB', (self.input_width, self.input_height), (114, 114, 114))
        canvas.paste(image.resize((resized_width, resized_height), Image.Resampling.BILINEAR), (offset_x, offset_y))
        # Contiguous NumPy array in NCHW layout, normalized to [0, 1].
        tensor = np.asarray(canvas, dtype=np.float32).transpose(2, 0, 1)[None] / 255.0
        output = self.session.run(None, {self.input.name: tensor})[0]
        if output.ndim != 3 or output.shape[0] != 1 or output.shape[1] < 4 + self.class_count:
            raise RuntimeError('Salida del modelo local incompatible')
        candidates = output[0]
        # YOLO segmentation appends mask coefficients after the class scores;
        # they must not be mistaken for the confidence of another class.
        scores = candidates[4 + self.pothole_class]
        classes = candidates[4:4 + self.class_count]
        indexes = np.where((scores >= self.threshold) & (np.argmax(classes, axis=0) == self.pothole_class))[0]
        if not len(indexes):
            return Analysis(isPothole=False, potholeType=None, hazardScore=0,
                            aiDescription='No se detectó un bache con suficiente confianza.', riskFactors=[])
        hits = SinglyLinkedList[Analysis]()
        for index in indexes[np.argsort(scores[indexes])[::-1]]:
            cx, cy, box_width, box_height = candidates[:4, index]
            score = scores[index]
            coords = dict(
                xmin=float(np.clip((cx - box_width / 2 - offset_x) / scale / width * 1000, 0, 1000)),
                xmax=float(np.clip((cx + box_width / 2 - offset_x) / scale / width * 1000, 0, 1000)),
                ymin=float(np.clip((cy - box_height / 2 - offset_y) / scale / height * 1000, 0, 1000)),
                ymax=float(np.clip((cy + box_height / 2 - offset_y) / scale / height * 1000, 0, 1000)),
            )
            if coords['xmax'] <= coords['xmin'] or coords['ymax'] <= coords['ymin']:
                continue
            box = BoundingBox(**coords)
            # Non-maximum suppression: retain separate holes, suppress overlapping proposals.
            if any(self.iou(box, hit.boundingBox) > .45 for hit in hits):
                continue
            area = (box.xmax - box.xmin) * (box.ymax - box.ymin) / 1_000_000
            # Priority comes from the relative size of the visible damage, not from the
            # model confidence. It does not measure depth or physical size.
            risk = 85 if area >= .35 else 70 if area >= .18 else 50 if area >= .06 else 35
            hits.append(Analysis(isPothole=True, potholeType='BACHE', hazardScore=risk,
                            aiDescription=f'Posible bache; confianza del detector local {round(float(score) * 100)}%. Requiere verificación.',
                            riskFactors=['Daño visible en la calzada', f'El recuadro ocupa aproximadamente {round(area * 100)}% del encuadre',
                                         'Profundidad y dimensiones físicas sin medir'],
                            boundingBox=box, confidence=float(score)))
            if hits.size >= 20:
                break
        if hits:
            principal = max(hits, key=lambda hit: hit.hazardScore)
            principal.detections = [DamageDetection.model_validate(hit.model_dump(exclude={'detections'})) for hit in hits]
            return principal
        return Analysis(isPothole=False, potholeType=None, hazardScore=0,
                        aiDescription='No se detectó un bache con suficiente confianza.', riskFactors=[])


class AIService:
    """Runs the custom YOLO detector off the event loop and tracks its latency."""

    def __init__(self, settings):
        self.settings = settings
        settings.ai_provider = 'local'
        self.local = PotholeDetector(settings)
        self.model_latencies = LatencyWindow(100)
        self.metrics_lock = threading.Lock()

    async def analyze(self, data: bytes, image: Image.Image, live: bool = False):
        started = time.perf_counter()
        size = self.settings.yolo_live_image_size if live else None
        stretch = live and getattr(self.settings, 'yolo_live_stretch', False)
        result = await asyncio.to_thread(self.local.analyze, image, size, stretch)
        latency = round((time.perf_counter() - started) * 1000)
        with self.metrics_lock:
            self.model_latencies.add(latency)
        return result, 'local-yolo', self.local.model_name, False

    def latency_summary(self) -> dict:
        with self.metrics_lock:
            return self.model_latencies.summary()

    async def close(self):
        pass
