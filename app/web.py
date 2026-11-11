"""Publicación opcional del frontend compilado en el mismo origen de la API."""
from pathlib import Path
from fastapi import FastAPI
from starlette.staticfiles import StaticFiles


def mount_frontend(app: FastAPI, directory: str):
    if not directory:
        return
    root = Path(directory).resolve()
    if not (root / 'index.html').is_file():
        raise RuntimeError('El frontend compilado no está disponible.')

    @app.middleware('http')
    async def web_headers(request, call_next):
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'camera=(self), geolocation=(self), microphone=()'
        if not request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = ('public, max-age=31536000, immutable'
                if request.url.path.startswith('/assets/') else 'no-cache')
        return response

    # Registrar al final: las rutas /api mantienen su autenticación y sus respuestas.
    # StaticFiles protege contra recorridos de directorio y no sirve archivos externos.
    app.mount('/', StaticFiles(directory=root, html=True), name='frontend')
