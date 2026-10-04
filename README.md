# BacheScan AI — Backend

API FastAPI para escaneo, análisis y reportes geolocalizados de baches. Requiere PostgreSQL; Railway ejecuta las migraciones de Alembic al iniciar.

## Railway

Configura el servicio desde la raíz de este repositorio con el Dockerfile incluido y agrega una base PostgreSQL. Variables del servicio:

- `DATABASE_URL`: referencia a la variable `DATABASE_URL` del servicio PostgreSQL de Railway.
- `CORS_ORIGINS`: URL pública exacta del frontend de Vercel, sin `/` final.
- `AI_PROVIDER=auto`: intenta Gemini cuando hay una clave; usa el modelo local si no hay cuota o configuración.
- `GEMINI_API_KEY` (opcional): guardar únicamente en Variables de Railway.
- `GEMINI_MODEL=gemini-3.5-flash-lite`
- `NOMINATIM_USER_AGENT`: identificador de esta aplicación y contacto del operador.

Railway proporciona `PORT`; el contenedor escucha en `0.0.0.0:$PORT`. El healthcheck es `/api/health`.

El archivo `.env.example` documenta las variables. No subas `.env` ni claves al repositorio.

## Desarrollo local y pruebas

Instala Python 3.12 y PostgreSQL. Desde esta carpeta, prepara un entorno e instala las dependencias de desarrollo:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Configura `DATABASE_URL` en `.env` para una base PostgreSQL local, ejecuta `alembic upgrade head` y luego inicia la API:

```powershell
alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 3001
```

El frontend Vite usa un proxy local de `/api` a `http://127.0.0.1:3001`; permite `http://localhost:5173` en `CORS_ORIGINS` si lo abres desde ese origen.

Las pruebas requieren una base PostgreSQL **exclusiva para pruebas**. Configura `TEST_DATABASE_URL` y ejecuta:

```powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://usuario:clave@localhost:5432/bachescan_test"
pytest -q
```

La integración crea y elimina esquemas `test_*` dentro de esa base. No uses una base de producción. Las imágenes de prueba y sus atribuciones se guardan en `tests/fixtures/`.
