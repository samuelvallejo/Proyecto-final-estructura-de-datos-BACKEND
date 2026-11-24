"""Optional serving of the compiled frontend from the same origin as the API."""
from pathlib import Path
from fastapi import FastAPI
from starlette.staticfiles import StaticFiles


class StaticFrontend:
    """Mounts the built single-page app with security headers and long-lived asset caching."""
    HEADERS = {'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
               'Referrer-Policy': 'strict-origin-when-cross-origin',
               'Permissions-Policy': 'camera=(self), geolocation=(self), microphone=()'}

    @classmethod
    async def add_headers(cls, request, call_next):
        response = await call_next(request)
        for name, value in cls.HEADERS.items():
            response.headers[name] = value
        path = request.url.path
        if not path.startswith('/api/'):
            response.headers['Cache-Control'] = 'public, max-age=31536000, immutable' if path.startswith('/assets/') else 'no-cache'
        return response

    @classmethod
    def mount(cls, app: FastAPI, directory: str):
        if not directory:
            return
        root = Path(directory).resolve()
        if not (root / 'index.html').is_file():
            raise RuntimeError('El frontend compilado no está disponible.')
        app.middleware('http')(cls.add_headers)
        # Mounted last: /api routes keep their authentication and responses.
        # StaticFiles guards against directory traversal and never serves outside files.
        app.mount('/', StaticFiles(directory=root, html=True), name='frontend')
