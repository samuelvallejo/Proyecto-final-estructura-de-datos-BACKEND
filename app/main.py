import asyncio
import hashlib
import logging
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, File, Form, UploadFile, HTTPException, Query, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import create_engine, select, text, func
from sqlalchemy.exc import SQLAlchemyError
from .config import Settings
from .contracts import Position
from .ai import AIService, validate_image
from .geocode import Geocoder
from .pipeline import ScanPipeline
from .repository import Repository
from .structures import CircularDoublyLinkedList
from . import schema as s

logger = logging.getLogger(__name__)
security = HTTPBearer(auto_error=False)


def create_app(settings=None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        engine = create_engine(settings.sqlalchemy_url(), pool_pre_ping=True, pool_size=5, max_overflow=5,
                               connect_args={'connect_timeout': 5})
        with engine.connect() as conn:
            version = conn.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
            if version != '0001':
                raise RuntimeError('Ejecuta alembic upgrade head antes de iniciar la API.')
        app.state.engine = engine
        app.state.repo = Repository(engine, settings)
        app.state.ai = AIService(settings)
        app.state.geocoder = Geocoder(engine, settings)
        app.state.pipeline = ScanPipeline(settings.max_pending_scans)
        app.state.pipeline.start()
        try:
            yield
        finally:
            await app.state.pipeline.close()
            await app.state.ai.close()
            engine.dispose()

    app = FastAPI(title='BacheScan AI', version='2.0.0', lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=[origin.strip() for origin in settings.cors_origins.split(',') if origin.strip()],
                       allow_methods=['GET', 'POST'], allow_headers=['Authorization', 'Content-Type'], expose_headers=['Retry-After'])

    @app.exception_handler(HTTPException)
    async def http_error(_, exc):
        return JSONResponse({'error': exc.detail}, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(SQLAlchemyError)
    async def db_error(_, exc):
        logger.error('Error PostgreSQL: %s', type(exc).__name__)
        return JSONResponse({'error': 'La base de datos no está disponible. Reintenta.'}, status_code=503)

    @app.middleware('http')
    async def upload_limit(request, call_next):
        if request.url.path == '/api/scan' and request.method == 'POST':
            length = request.headers.get('content-length', '')
            if not length.isdigit():
                return JSONResponse({'error': 'Se requiere Content-Length para cargar fotogramas.'}, status_code=411)
            if int(length) > 900_000:
                return JSONResponse({'error': 'El fotograma excede el límite de carga.'}, status_code=413)
        response = await call_next(request)
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    def session_id(credentials: HTTPAuthorizationCredentials | None = Depends(security)):
        return app.state.repo.session(credentials.credentials if credentials else None)

    @app.get('/api/health')
    def health():
        with app.state.engine.connect() as conn:
            conn.execute(text('SELECT 1'))
            count = conn.execute(select(func.count()).select_from(s.reports)).scalar_one()
        return {'status': 'ok', 'storage': 'postgresql', 'tables': len(s.metadata.tables), 'reports': count,
                'geminiConfigured': bool(settings.gemini_api_key),
                'aiProvider': 'gemini' if settings.gemini_api_key and settings.ai_provider != 'local' else 'local-yolo',
                'localModelReady': True}

    @app.post('/api/sessions', status_code=201)
    def new_session():
        with app.state.engine.begin() as conn:
            conn.execute(text('SELECT pg_advisory_xact_lock(771013)'))
            count = conn.execute(select(func.count()).select_from(s.sessions).where(s.sessions.c.created_at > s.now() - 3600_000)).scalar_one()
            if count >= 1000:
                raise HTTPException(429, 'Límite temporal de sesiones alcanzado.')
            # Bloqueo hasta insertar: evita exceder el límite con peticiones concurrentes.
            return app.state.repo.new_session()

    @app.post('/api/scan')
    async def scan(frame: UploadFile = File(), lat: str | None = Form(None), lng: str | None = Form(None),
                   accuracy: str | None = Form(None), owner: str = Depends(session_id)):
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
                report, existing, analysis_id = await asyncio.to_thread(app.state.repo.save_scan, owner, data, image,
                    analysis, provider, model, fallback, duration, position, zone)
                await asyncio.to_thread(app.state.repo.finish_usage, usage_id, provider)
                event = {'sessionId': owner, 'analysisId': analysis_id, 'provider': provider,
                         'isPothole': analysis.isPothole, 'reportId': report['id'] if report else None, 'timestamp': s.now()}
                app.state.pipeline.remember(event, duration)
                note = None
                if analysis.isPothole and not position:
                    note = 'Falta GPS válido con precisión de hasta ±100 m. El daño se analizó, pero no se ubicó en el mapa.'
                return {'result': analysis.result(), 'provider': provider, 'fallback': fallback,
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

    @app.get('/api/reports')
    def reports(limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
        items, total = app.state.repo.list_reports(limit, offset)
        return {'reports': items, 'total': total, 'hasMore': offset + len(items) < total}

    @app.get('/api/reports/priority')
    def priority(limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
        items, total = app.state.repo.list_reports(limit, offset, priority=True)
        return {'reports': items, 'total': total, 'hasMore': offset + len(items) < total}

    @app.get('/api/reports/nearby')
    def nearby(lat: float = Query(ge=-90, le=90), lng: float = Query(ge=-180, le=180),
               radiusKm: float = Query(5, gt=0, le=50), limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
        Position(lat=lat, lng=lng, accuracy=0)
        items, total = app.state.repo.list_reports(limit, offset, position={'lat': lat, 'lng': lng}, radius=radiusKm * 1000)
        return {'reports': items, 'total': total, 'hasMore': offset + len(items) < total}

    @app.get('/api/reports/patrol')
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

    @app.get('/api/data-structures/stats')
    def stats():
        return {**app.state.pipeline.stats(),
                'array': {'use': 'Tensor NumPy NCHW de imagen y arrays de reportes paginados'},
                'circularDoublyLinkedList': {'use': 'Recorrido circular de baches prioritarios: anterior y siguiente'},
                'stack': {'use': 'Historial LIFO de navegación en el frontend'},
                'persistence': 'PostgreSQL; las estructuras de ejecución son temporales por proceso'}

    return app


app = create_app()
