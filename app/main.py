import asyncio
import logging
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, File, Form, UploadFile, HTTPException, Query, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import create_engine, select, text, func
from sqlalchemy.exc import SQLAlchemyError
from .config import Settings
from .contracts import Position, Analysis
from .ai import AIService, validate_image
from .pothole_detector import validate_photo, MAX_PHOTO_BYTES, PHOTO_TYPES, ModelUnavailable, MODEL_UNAVAILABLE
from .geocode import Geocoder
from .pipeline import ScanPipeline
from .repository import Repository
from .structures import CircularDoublyLinkedList
from . import schema as s
from .auth import router as auth_router, Vault, password_hash, scan_owner, current_session
from .trips import router as trip_router, validate_scan_trip, link_reports
from .community import router as community_router
from .tree_api import router as tree_router

logger = logging.getLogger(__name__)


def create_app(settings=None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        app.state.settings = settings
        app.state.vault = Vault(settings.data_encryption_key)
        app.state.dummy_password_hash = password_hash('Dummy-only-password!83')
        engine = create_engine(settings.sqlalchemy_url(), pool_pre_ping=True, pool_size=5, max_overflow=5,
                               hide_parameters=True, connect_args={'connect_timeout': 5})
        with engine.connect() as conn:
            version = conn.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
            if version not in ('0002', '0003'):
                raise RuntimeError('Ejecuta alembic upgrade head antes de iniciar la API.')
        app.state.engine = engine
        app.state.repo = Repository(engine, settings)
        app.state.ai = await asyncio.to_thread(AIService, settings)
        app.state.detector = app.state.ai.local
        app.state.geocoder = Geocoder(engine, settings)
        app.state.pipeline = ScanPipeline(settings.max_pending_scans)
        app.state.pipeline.start()
        try:
            yield
        finally:
            await app.state.pipeline.close()
            await app.state.ai.close()
            engine.dispose()

    app = FastAPI(title='BacheScan AI', version='3.0.0', lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(auth_router)
    app.include_router(trip_router)
    app.include_router(community_router)
    app.include_router(tree_router)
    app.add_middleware(CORSMiddleware, allow_origins=[origin.strip() for origin in settings.cors_origins.split(',') if origin.strip()],
                       allow_credentials=True, allow_methods=['GET', 'POST'],
                       allow_headers=['Content-Type'], expose_headers=['Retry-After'])

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        if request.url.path == '/api/detect/potholes':
            return JSONResponse({'error': 'Selecciona una imagen JPEG, PNG o WebP para detectar baches.'}, status_code=422)
        return JSONResponse({'error': 'No se pudo completar la operación. Revisa los requisitos del formulario.'}, status_code=422)

    @app.exception_handler(Exception)
    async def unexpected_error(_, exc):
        logger.error('operation_failed')
        return JSONResponse({'error': 'No se pudo completar la operación. Inténtalo de nuevo.'}, status_code=500)

    @app.exception_handler(HTTPException)
    async def http_error(_, exc):
        return JSONResponse({'error': exc.detail}, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(SQLAlchemyError)
    async def db_error(_, exc):
        logger.error('Error PostgreSQL: %s', type(exc).__name__)
        return JSONResponse({'error': 'La base de datos no está disponible. Reintenta.'}, status_code=503)

    @app.middleware('http')
    async def upload_limit(request, call_next):
        if request.url.path.startswith('/api/') and request.method == 'POST':
            origins = {origin.strip() for origin in settings.cors_origins.split(',') if origin.strip()}
            if request.headers.get('origin') not in origins:
                return JSONResponse({'error': 'No se pudo completar la operación.'}, status_code=403)
        if (request.url.path.startswith('/api/auth/') or request.url.path.startswith('/api/trips') or request.url.path.startswith('/api/community/')) and request.method == 'POST':
            length = request.headers.get('content-length', '0')
            if not length.isdigit() or int(length) > 8192:
                return JSONResponse({'error': 'No se pudo completar la operación.'}, status_code=413)
        if request.url.path == '/api/scan' and request.method == 'POST':
            length = request.headers.get('content-length', '')
            if not length.isdigit():
                return JSONResponse({'error': 'Se requiere Content-Length para cargar fotogramas.'}, status_code=411)
            if int(length) > 900_000:
                return JSONResponse({'error': 'El fotograma excede el límite de carga.'}, status_code=413)
        if request.url.path == '/api/detect/potholes' and request.method == 'POST':
            length = request.headers.get('content-length', '')
            if not length.isdigit():
                return JSONResponse({'error': 'Se requiere Content-Length para cargar la imagen.'}, status_code=411)
            if int(length) > MAX_PHOTO_BYTES + 64 * 1024:
                return JSONResponse({'error': 'La imagen excede el límite de 4 MB.'}, status_code=413)
        response = await call_next(request)
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
            response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    session_id = scan_owner

    @app.get('/api/health')
    def health():
        with app.state.engine.connect() as conn:
            conn.execute(text('SELECT 1'))
            count = conn.execute(select(func.count()).select_from(s.reports)).scalar_one()
        return {'status': 'ok'}

    @app.post('/api/sessions', status_code=201)
    def new_session():
        raise HTTPException(401, 'Inicia sesión para continuar.')

    @app.post('/api/scan')
    async def scan(frame: UploadFile = File(), lat: str | None = Form(None), lng: str | None = Form(None),
                   accuracy: str | None = Form(None), tripId: str | None = Form(None, max_length=36), owner: str = Depends(session_id)):
        if not app.state.detector.ready:
            raise HTTPException(503, MODEL_UNAVAILABLE)
        if tripId:
            from uuid import UUID
            try:
                tripId = str(UUID(tripId))
            except ValueError:
                raise HTTPException(422, 'No se pudo completar la operación.') from None
            await asyncio.to_thread(validate_scan_trip, app.state.engine, tripId, owner)
        data = await frame.read(850_001)
        await frame.close()
        try:
            image = await asyncio.to_thread(validate_image, data)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        position = None
        try:
            if lat is not None and lng is not None and accuracy is not None:
                position = Position(lat=float(lat), lng=float(lng), accuracy=float(accuracy))
        except (ValueError, ValidationError):
            pass
        if app.state.pipeline.pending >= settings.max_pending_scans:
            raise HTTPException(429, 'Cola llena. Reintenta en unos segundos.', headers={'Retry-After': '5'})
        usage_id = await asyncio.to_thread(app.state.repo.reserve_usage, owner)

        async def operation():
            started = time.monotonic()
            provider = 'unknown'
            try:
                analysis, provider, model, fallback = await app.state.ai.analyze(data, image)
                zone = await app.state.geocoder.resolve(position) if analysis.isPothole and position else None
                duration = round((time.monotonic() - started) * 1000)
                observations = [Analysis(isPothole=True, **detection.model_dump()) for detection in analysis.detections] if analysis.detections else [analysis]
                saved_reports, detections, excluded = [], [], []
                principal = None
                for observation in observations:
                    report, existing, analysis_id = await asyncio.to_thread(app.state.repo.save_scan, owner, data, image,
                        observation, provider, model, fallback, duration, position, zone, excluded)
                    if report:
                        excluded.append(report['id'])
                        saved_reports.append(report)
                    detections.append({**observation.result(), 'report': report, 'existing': existing})
                    if principal is None or observation.hazardScore > principal[0].hazardScore:
                        principal = (observation, report, existing, analysis_id)
                observation, report, existing, analysis_id = principal
                if tripId and saved_reports:
                    await asyncio.to_thread(link_reports, app.state.engine, tripId, owner, saved_reports)
                await asyncio.to_thread(app.state.repo.finish_usage, usage_id, provider)
                event = {'sessionId': owner, 'analysisId': analysis_id, 'provider': provider,
                         'isPothole': analysis.isPothole, 'reportId': report['id'] if report else None, 'timestamp': s.now()}
                app.state.pipeline.remember(event, duration)
                note = None
                if analysis.isPothole and not position:
                    note = 'Falta GPS válido con precisión de hasta ±100 m. El daño se analizó, pero no se ubicó en el mapa.'
                return {'result': analysis.result(), 'provider': provider, 'fallback': fallback,
                        'detections': detections if analysis.isPothole else [], 'reports': saved_reports,
                        'report': report, 'existing': existing, 'locationNote': note,
                        'nextScanMs': max(round((settings.scan_interval_seconds if provider == 'gemini' else settings.local_scan_interval_seconds) * 1000), 6000 if provider == 'gemini' else 1500)}
            except Exception:
                await asyncio.to_thread(app.state.repo.finish_usage, usage_id, provider, True)
                raise
            finally:
                image.close()
        try:
            return await app.state.pipeline.submit(operation)
        except OverflowError as exc:
            await asyncio.to_thread(app.state.repo.finish_usage, usage_id, 'not-run', True)
            image.close()
            raise HTTPException(429, str(exc)) from exc
        except HTTPException:
            raise
        except SQLAlchemyError:
            raise
        except Exception as exc:
            logger.error('Falló el escaneo: %s', type(exc).__name__)
            raise HTTPException(502, 'No se pudo analizar este fotograma. Reintenta.') from exc

    @app.post('/api/detect/potholes')
    async def detect_potholes(image: UploadFile = File(), owner: str = Depends(session_id)):
        try:
            if image.content_type not in PHOTO_TYPES:
                raise HTTPException(415, 'Selecciona una imagen JPEG, PNG o WebP.')
            data = await image.read(MAX_PHOTO_BYTES + 1)
            content_type = image.content_type
        finally:
            await image.close()
        if len(data) > MAX_PHOTO_BYTES:
            raise HTTPException(413, 'La imagen excede el límite de 4 MB.')
        if not app.state.detector.ready:
            raise HTTPException(503, MODEL_UNAVAILABLE)
        if app.state.pipeline.pending >= settings.max_pending_scans:
            raise HTTPException(429, 'La cola de análisis está llena. Reintenta en unos segundos.', headers={'Retry-After': '5'})
        usage_id = await asyncio.to_thread(app.state.repo.reserve_usage, owner)

        async def operation():
            decoded = None
            try:
                try:
                    decoded = await asyncio.to_thread(validate_photo, data, content_type)
                except ValueError as exc:
                    raise HTTPException(400, str(exc)) from None
                result = await asyncio.to_thread(app.state.detector.detect, decoded)
                await asyncio.to_thread(app.state.repo.finish_usage, usage_id, 'custom-yolov8')
                return result
            except Exception:
                await asyncio.to_thread(app.state.repo.finish_usage, usage_id, 'custom-yolov8', True)
                raise
            finally:
                if decoded is not None:
                    decoded.close()
        try:
            return await app.state.pipeline.submit(operation)
        except OverflowError:
            await asyncio.to_thread(app.state.repo.finish_usage, usage_id, 'not-run', True)
            raise HTTPException(429, 'La cola de análisis está llena. Reintenta en unos segundos.') from None
        except ModelUnavailable:
            raise HTTPException(503, MODEL_UNAVAILABLE) from None
        except (HTTPException, SQLAlchemyError):
            raise
        except Exception:
            logger.error('pothole_photo_inference_failed')
            raise HTTPException(502, 'No se pudo analizar la imagen. Inténtalo de nuevo.') from None

    @app.get('/api/reports', dependencies=[Depends(current_session)])
    def reports(limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
        items, total = app.state.repo.list_reports(limit, offset)
        return {'reports': items, 'total': total, 'hasMore': offset + len(items) < total}

    @app.get('/api/reports/priority', dependencies=[Depends(current_session)])
    def priority(limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
        items, total = app.state.repo.list_reports(limit, offset, priority=True)
        return {'reports': items, 'total': total, 'hasMore': offset + len(items) < total}

    @app.get('/api/reports/nearby', dependencies=[Depends(current_session)])
    def nearby(lat: float = Query(ge=-90, le=90), lng: float = Query(ge=-180, le=180),
               radiusKm: float = Query(5, gt=0, le=50), limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
        Position(lat=lat, lng=lng, accuracy=0)
        items, total = app.state.repo.list_reports(limit, offset, position={'lat': lat, 'lng': lng}, radius=radiusKm * 1000)
        return {'reports': items, 'total': total, 'hasMore': offset + len(items) < total}

    @app.get('/api/reports/patrol', dependencies=[Depends(current_session)])
    def patrol(current: str | None = None, direction: str = Query('next', pattern='^(next|previous)$')):
        items, _ = app.state.repo.list_reports(200, priority=True)
        ring = CircularDoublyLinkedList[dict]()
        for item in items:
            ring.append(item)
        if not items:
            return {'report': None, 'size': 0}
        if current:
            for _ in range(ring.size):
                if ring.cursor.value['id'] == current:
                    break
                ring.advance()
            if direction == 'previous':
                selected = ring.retreat()
            else:
                ring.advance()
                selected = ring.advance()
        else:
            selected = ring.advance()
        return {'report': selected, 'size': ring.size}

    @app.get('/api/scans/history')
    def history(reverse: bool = True, owner: str = Depends(session_id)):
        events = app.state.pipeline.history.reverse() if reverse else iter(app.state.pipeline.history)
        return {'events': [{k: v for k, v in event.items() if k != 'sessionId'} for event in events if event['sessionId'] == owner]}

    @app.get('/api/data-structures/stats', dependencies=[Depends(current_session)])
    def stats():
        return {**app.state.pipeline.stats(),
                'array': {'use': 'Tensor NumPy NCHW de imagen y arrays de reportes paginados'},
                'circularDoublyLinkedList': {'use': 'Recorrido circular de baches prioritarios: anterior y siguiente'},
                'stack': {'use': 'Historial LIFO de navegación en el frontend'},
                'persistence': 'PostgreSQL; las estructuras de ejecución son temporales por proceso'}

    return app


app = create_app()
