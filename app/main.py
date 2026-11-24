"""BacheScan AI API: builds the FastAPI application from its services and controllers."""
import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from uuid import UUID
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from . import schema as s
from .admin import AdminController, AdminService
from .ai import AIService, FrameValidator
from .auth import AuditLog, AuthController, DemoAccounts, PasswordHasher, SessionGuard, Vault
from .community import CommunityController
from .config import Settings
from .contracts import Analysis, Position
from .geocode import Geocoder
from .graph_api import GraphController
from .migration_api import MigrationController
from .pipeline import ScanPipeline
from .pothole_detector import MODEL_UNAVAILABLE, ModelUnavailable, PhotoValidator
from .profile import DashboardService, ProfileController, ProfileService
from .report_trees import ReportRiskIndex
from .repository import Repository
from .structures import CircularDoublyLinkedList, HashSet, SinglyLinkedList
from .tree_api import TreeController
from .trips import TripController, TripService
from .web import StaticFrontend

logger = logging.getLogger(__name__)
SCHEMA_VERSION = '0004'


class PriorityPatrol:
    """Walks the reports by priority on a circular doubly linked list (previous / next)."""

    def __init__(self, reports):
        self.ring = CircularDoublyLinkedList[dict]()
        for report in reports:
            self.ring.append(report)

    def step(self, current, direction):
        if not self.ring.size:
            return None
        if not current:
            return self.ring.advance()
        for _ in range(self.ring.size):
            if self.ring.cursor.value['id'] == current:
                break
            self.ring.advance()
        if direction == 'previous':
            return self.ring.retreat()
        self.ring.advance()
        return self.ring.advance()


class ScanController:
    """Live frame scanning (/api/scan) and still-photo detection (/api/detect/potholes)."""
    MAX_FRAME_READ = 850_001

    def register(self, app: FastAPI):
        app.add_api_route('/api/sessions', self.anonymous_session, methods=['POST'], status_code=201)
        app.add_api_route('/api/scan', self.scan, methods=['POST'])
        app.add_api_route('/api/detect/potholes', self.detect_potholes, methods=['POST'])

    @staticmethod
    def anonymous_session():
        # Anonymous scanning sessions were removed: every scan needs an account.
        raise HTTPException(401, 'Inicia sesión para continuar.')

    @staticmethod
    def _next_scan_ms(settings, provider):
        if provider == 'gemini':
            return max(round(settings.scan_interval_seconds * 1000), 6000)
        return max(round(settings.local_scan_interval_seconds * 1000), 250)

    async def scan(self, request: Request, frame: UploadFile = File(), lat: str | None = Form(None),
                   lng: str | None = Form(None), accuracy: str | None = Form(None),
                   tripId: str | None = Form(None, max_length=36), mode: str = Form('live', pattern='^(live|still)$'),
                   owner: str = Depends(SessionGuard.session_id)):
        state, settings = request.app.state, request.app.state.settings
        if not state.detector.ready:
            raise HTTPException(503, MODEL_UNAVAILABLE)
        if tripId:
            try:
                tripId = str(UUID(tripId))
            except ValueError:
                raise HTTPException(422, 'No se pudo completar la operación.') from None
            await asyncio.to_thread(state.trips.validate_for_scan, tripId, owner)
        data = await frame.read(self.MAX_FRAME_READ)
        await frame.close()
        try:
            image = await asyncio.to_thread(FrameValidator.validate, data)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        position = None
        try:
            if lat is not None and lng is not None and accuracy is not None:
                position = Position(lat=float(lat), lng=float(lng), accuracy=float(accuracy))
        except (ValueError, ValidationError):
            pass
        if state.pipeline.pending >= settings.max_pending_scans:
            raise HTTPException(429, 'Cola llena. Reintenta en unos segundos.', headers={'Retry-After': '5'})
        usage_id = await asyncio.to_thread(state.repo.reserve_usage, owner)

        async def operation():
            started = time.monotonic()
            provider = 'unknown'
            try:
                analysis, provider, model, fallback = await state.ai.analyze(data, image, live=mode == 'live')
                zone = await state.geocoder.resolve(position) if analysis.isPothole and position else None
                duration = round((time.monotonic() - started) * 1000)
                observations = SinglyLinkedList[Analysis]()
                if analysis.detections:
                    for detection in analysis.detections:
                        observations.append(Analysis(isPothole=True, **detection.model_dump()))
                else:
                    observations.append(analysis)
                saved_reports, detections, excluded = SinglyLinkedList[dict](), SinglyLinkedList[dict](), HashSet[str]()
                principal = None
                for observation in observations:
                    report, existing, analysis_id = await asyncio.to_thread(state.repo.save_scan, owner, data, image,
                        observation, provider, model, fallback, duration, position, zone, list(excluded))
                    if report:
                        excluded.add(report['id'])
                        saved_reports.append(report)
                    detections.append({**observation.result(), 'report': report, 'existing': existing})
                    if principal is None or observation.hazardScore > principal[0].hazardScore:
                        principal = (observation, report, existing, analysis_id)
                _, report, existing, analysis_id = principal
                if tripId and saved_reports:
                    await asyncio.to_thread(state.trips.link_reports, tripId, owner, list(saved_reports))
                await asyncio.to_thread(state.repo.finish_usage, usage_id, provider)
                state.pipeline.remember({'sessionId': owner, 'analysisId': analysis_id, 'provider': provider,
                                         'isPothole': analysis.isPothole, 'reportId': report['id'] if report else None,
                                         'timestamp': s.Clock.now()}, duration)
                if analysis.isPothole:
                    await asyncio.to_thread(self._log_detection, state.engine, owner, observations.size, provider)
                note = None
                if analysis.isPothole and not position:
                    note = 'Falta GPS válido con precisión de hasta ±100 m. El daño se analizó, pero no se ubicó en el mapa.'
                return {'result': analysis.result(), 'provider': provider, 'fallback': fallback,
                        'detections': list(detections) if analysis.isPothole else [], 'reports': list(saved_reports),
                        'report': report, 'existing': existing, 'locationNote': note, 'durationMs': duration,
                        'nextScanMs': self._next_scan_ms(settings, provider)}
            except Exception:
                await asyncio.to_thread(state.repo.finish_usage, usage_id, provider, True)
                raise
            finally:
                image.close()
        try:
            return await state.pipeline.submit(operation)
        except OverflowError as exc:
            await asyncio.to_thread(state.repo.finish_usage, usage_id, 'not-run', True)
            image.close()
            raise HTTPException(429, str(exc)) from exc
        except (HTTPException, SQLAlchemyError):
            raise
        except Exception as exc:
            logger.error('scan_failed: %s', type(exc).__name__)
            raise HTTPException(502, 'No se pudo analizar este fotograma. Reintenta.') from exc

    @staticmethod
    def _log_detection(engine, session_id, detections, provider):
        """Audit trail entry for frames with findings; empty frames are already counted in api_usage."""
        with engine.begin() as conn:
            AuditLog.record(conn, session_id, 'scan.detected', details={'detections': detections, 'provider': provider})

    async def detect_potholes(self, request: Request, image: UploadFile = File(),
                              owner: str = Depends(SessionGuard.session_id)):
        state, settings = request.app.state, request.app.state.settings
        try:
            if image.content_type not in PhotoValidator.TYPES:
                raise HTTPException(415, 'Selecciona una imagen JPEG, PNG o WebP.')
            data = await image.read(PhotoValidator.MAX_BYTES + 1)
            content_type = image.content_type
        finally:
            await image.close()
        if len(data) > PhotoValidator.MAX_BYTES:
            raise HTTPException(413, 'La imagen excede el límite de 4 MB.')
        if not state.detector.ready:
            raise HTTPException(503, MODEL_UNAVAILABLE)
        if state.pipeline.pending >= settings.max_pending_scans:
            raise HTTPException(429, 'La cola de análisis está llena. Reintenta en unos segundos.', headers={'Retry-After': '5'})
        usage_id = await asyncio.to_thread(state.repo.reserve_usage, owner)

        async def operation():
            decoded = None
            try:
                try:
                    decoded = await asyncio.to_thread(PhotoValidator.validate, data, content_type)
                except ValueError as exc:
                    raise HTTPException(400, str(exc)) from None
                result = await asyncio.to_thread(state.detector.detect, decoded)
                await asyncio.to_thread(state.repo.finish_usage, usage_id, 'custom-yolov8')

                def remember_photo():
                    with state.engine.begin() as conn:
                        AuditLog.record(conn, owner, 'photo.analyzed', details={'detections': result['count']})
                await asyncio.to_thread(remember_photo)
                return result
            except Exception:
                await asyncio.to_thread(state.repo.finish_usage, usage_id, 'custom-yolov8', True)
                raise
            finally:
                if decoded is not None:
                    decoded.close()
        try:
            return await state.pipeline.submit(operation)
        except OverflowError:
            await asyncio.to_thread(state.repo.finish_usage, usage_id, 'not-run', True)
            raise HTTPException(429, 'La cola de análisis está llena. Reintenta en unos segundos.') from None
        except ModelUnavailable:
            raise HTTPException(503, MODEL_UNAVAILABLE) from None
        except (HTTPException, SQLAlchemyError):
            raise
        except Exception:
            logger.error('pothole_photo_inference_failed')
            raise HTTPException(502, 'No se pudo analizar la imagen. Inténtalo de nuevo.') from None


class ReportController:
    """Report listings, the priority patrol, scan history, structure stats and the health check."""

    def register(self, app: FastAPI):
        guarded = [Depends(SessionGuard.current)]
        app.add_api_route('/api/health', self.health, methods=['GET'])
        app.add_api_route('/api/reports', self.reports, methods=['GET'], dependencies=guarded)
        app.add_api_route('/api/reports/priority', self.priority, methods=['GET'], dependencies=guarded)
        app.add_api_route('/api/reports/nearby', self.nearby, methods=['GET'], dependencies=guarded)
        app.add_api_route('/api/reports/patrol', self.patrol, methods=['GET'], dependencies=guarded)
        app.add_api_route('/api/scans/history', self.history, methods=['GET'])
        app.add_api_route('/api/data-structures/stats', self.stats, methods=['GET'], dependencies=guarded)

    def health(self, request: Request):
        # Real check: if PostgreSQL does not answer, the service reports 503 and 'down'.
        try:
            with request.app.state.engine.connect() as conn:
                conn.execute(text('SELECT 1'))
        except SQLAlchemyError as exc:
            logger.error('health_database_down: %s', type(exc).__name__)
            return JSONResponse({'status': 'degraded', 'database': 'down'}, status_code=503)
        return {'status': 'ok', 'database': 'up', 'model': 'ready' if request.app.state.detector.ready else 'unavailable'}

    def reports(self, request: Request, limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
        items, total = request.app.state.repo.list_reports(limit, offset)
        return {'reports': items, 'total': total, 'hasMore': offset + len(items) < total}

    def priority(self, request: Request, limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
        items, total = request.app.state.repo.list_reports(limit, offset, priority=True)
        items = ReportRiskIndex(items).ordered('descending')
        return {'reports': items, 'total': total, 'hasMore': offset + len(items) < total}

    def nearby(self, request: Request, lat: float = Query(ge=-90, le=90), lng: float = Query(ge=-180, le=180),
               radiusKm: float = Query(5, gt=0, le=50), limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
        Position(lat=lat, lng=lng, accuracy=0)
        items, total = request.app.state.repo.list_reports(limit, offset, position={'lat': lat, 'lng': lng}, radius=radiusKm * 1000)
        return {'reports': items, 'total': total, 'hasMore': offset + len(items) < total}

    def patrol(self, request: Request, current: str | None = None,
               direction: str = Query('next', pattern='^(next|previous)$')):
        items, _ = request.app.state.repo.list_reports(200, priority=True)
        patrol = PriorityPatrol(items)
        return {'report': patrol.step(current, direction), 'size': patrol.ring.size}

    def history(self, request: Request, reverse: bool = True, owner: str = Depends(SessionGuard.session_id)):
        pipeline = request.app.state.pipeline
        events = pipeline.history.reverse() if reverse else iter(pipeline.history)
        return {'events': [{key: value for key, value in event.items() if key != 'sessionId'}
                           for event in events if event['sessionId'] == owner]}

    def stats(self, request: Request):
        return {**request.app.state.pipeline.stats(),
                'modelLatencyMs': request.app.state.ai.latency_summary(),
                'array': {'use': 'Tensor NumPy NCHW de imagen y arreglo dinámico del montículo'},
                'circularDoublyLinkedList': {'use': 'Recorrido circular de baches prioritarios: anterior y siguiente'},
                'stack': {'use': 'Historial LIFO de navegación y recorridos en profundidad (DFS)'},
                'hashMap': {'use': 'Tabla hash con encadenamiento: vértices del grafo y reportes por id'},
                'minHeap': {'use': 'Montículo mínimo de Dijkstra para el camino más corto'},
                'binarySearchTree': {'use': 'Orden y rangos de riesgo; búsqueda y recorridos de reportes reales'},
                'generalTree': {'use': 'Exploración jerárquica: ciudad, barrio, vía y bache'},
                'graph': {'use': 'Red de cercanía entre baches: listas de adyacencia, BFS, DFS y Dijkstra'},
                'persistence': 'PostgreSQL; las estructuras de ejecución son temporales por proceso'}


class SecurityMiddleware:
    """Origin check on POST, upload size limits and no-store caching for /api responses."""
    SMALL_JSON_PREFIXES = ('/api/auth/', '/api/trips', '/api/community/', '/api/passes', '/api/admin/')
    MIGRATION_PATHS = ('/api/migration/import', '/api/migration/export')

    def __init__(self, settings):
        self.origins = HashSet(origin.strip() for origin in settings.cors_origins.split(',') if origin.strip())

    @staticmethod
    def _length(request):
        value = request.headers.get('content-length', '')
        return int(value) if value.isdigit() else None

    async def __call__(self, request: Request, call_next):
        path, method = request.url.path, request.method
        if path.startswith('/api/') and method == 'POST':
            if path not in self.MIGRATION_PATHS and request.headers.get('origin') not in self.origins:
                return JSONResponse({'error': 'No se pudo completar la operación.'}, status_code=403)
            length = self._length(request)
            if path.startswith(self.SMALL_JSON_PREFIXES):
                declared = request.headers.get('content-length', '0')
                if not declared.isdigit() or int(declared) > 8192:
                    return JSONResponse({'error': 'No se pudo completar la operación.'}, status_code=413)
            if path == '/api/scan':
                if length is None:
                    return JSONResponse({'error': 'Se requiere Content-Length para cargar fotogramas.'}, status_code=411)
                if length > 900_000:
                    return JSONResponse({'error': 'El fotograma excede el límite de carga.'}, status_code=413)
            if path == '/api/detect/potholes':
                if length is None:
                    return JSONResponse({'error': 'Se requiere Content-Length para cargar la imagen.'}, status_code=411)
                if length > PhotoValidator.MAX_BYTES + 64 * 1024:
                    return JSONResponse({'error': 'La imagen excede el límite de 4 MB.'}, status_code=413)
        response = await call_next(request)
        if path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
            response.headers['X-Content-Type-Options'] = 'nosniff'
        return response


class BacheScanApplication:
    """Wires settings, services, middlewares, error handlers and controllers into one FastAPI app."""

    def __init__(self, settings=None):
        self.settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(self, app: FastAPI):
        settings, state = self.settings, app.state
        state.settings = settings
        state.vault = Vault(settings.data_encryption_key)
        state.dummy_password_hash = PasswordHasher.hash('Dummy-only-password!83')
        engine = create_engine(settings.sqlalchemy_url(), pool_pre_ping=True, pool_size=5, max_overflow=5,
                               hide_parameters=True, connect_args={'connect_timeout': 5})
        with engine.connect() as conn:
            if conn.execute(text('SELECT version_num FROM alembic_version')).scalar_one() != SCHEMA_VERSION:
                raise RuntimeError('Ejecuta alembic upgrade head antes de iniciar la API.')
        state.engine = engine
        DemoAccounts.seed(engine, state.vault, settings)
        state.repo = Repository(engine, settings)
        state.ai = await asyncio.to_thread(AIService, settings)
        state.detector = state.ai.local
        state.geocoder = Geocoder(engine, settings)
        state.pipeline = ScanPipeline(settings.max_pending_scans)
        state.trips = TripService(engine, state.vault, state.repo, settings)
        state.profile = ProfileService(engine, state.vault, state.repo, settings)
        state.dashboard = DashboardService(engine, state.repo, state.pipeline, state.ai, settings)
        state.admin = AdminService(engine, state.vault, state.repo)
        state.pipeline.start()
        try:
            yield
        finally:
            await state.pipeline.close()
            await state.ai.close()
            engine.dispose()

    @staticmethod
    def _error_handlers(app: FastAPI):
        @app.exception_handler(RequestValidationError)
        async def validation_error(request, exc):
            if request.url.path == '/api/detect/potholes':
                return JSONResponse({'error': 'Selecciona una imagen JPEG, PNG o WebP para detectar baches.'}, status_code=422)
            return JSONResponse({'error': 'No se pudo completar la operación. Revisa los requisitos del formulario.'}, status_code=422)

        @app.exception_handler(Exception)
        async def unexpected_error(_, exc):
            logger.error('operation_failed: %s', type(exc).__name__)
            return JSONResponse({'error': 'No se pudo completar la operación. Inténtalo de nuevo.'}, status_code=500)

        @app.exception_handler(HTTPException)
        async def http_error(_, exc):
            return JSONResponse({'error': exc.detail}, status_code=exc.status_code, headers=exc.headers)

        @app.exception_handler(SQLAlchemyError)
        async def database_error(_, exc):
            logger.error('database_error: %s', type(exc).__name__)
            return JSONResponse({'error': 'La base de datos no está disponible. Reintenta.'}, status_code=503)

    @staticmethod
    async def _request_logging(request, call_next):
        started = time.monotonic()
        request_id = request.headers.get('X-Request-ID') or uuid.uuid4().hex
        response = await call_next(request)
        response.headers['X-Request-ID'] = request_id
        logger.info('%s %s %s -> %s in %.1fms', request_id, request.method, request.url.path, response.status_code,
                    (time.monotonic() - started) * 1000)
        return response

    def build(self) -> FastAPI:
        settings = self.settings
        app = FastAPI(title='BacheScan AI', version='3.0.0', lifespan=self.lifespan,
                      docs_url=None, redoc_url=None, openapi_url=None)
        for controller in (AuthController(), TripController(), CommunityController(), TreeController(),
                           GraphController(), MigrationController(), ProfileController(), AdminController()):
            app.include_router(controller.router)
        app.add_middleware(CORSMiddleware, allow_origins=[origin.strip() for origin in settings.cors_origins.split(',') if origin.strip()],
                           allow_credentials=True, allow_methods=['GET', 'POST'],
                           allow_headers=['Content-Type'], expose_headers=['Retry-After'])
        app.middleware('http')(self._request_logging)
        self._error_handlers(app)
        app.middleware('http')(SecurityMiddleware(settings))
        ScanController().register(app)
        ReportController().register(app)
        StaticFrontend.mount(app, settings.static_root)
        return app


def create_app(settings=None) -> FastAPI:
    return BacheScanApplication(settings).build()


app = create_app()
