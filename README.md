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
