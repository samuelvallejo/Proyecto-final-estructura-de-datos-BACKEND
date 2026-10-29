# El frontend conserva exactamente el commit elegido de su repositorio independiente.
FROM node:24-bookworm-slim AS frontend
ARG FRONTEND_COMMIT=fcb5e0f3d3ca97ca319ce19857f56b808b721bcb
ADD https://github.com/samuelvallejo/proyecto-final-estructura-de-datos-FRONTEND/archive/${FRONTEND_COMMIT}.tar.gz /tmp/frontend.tar.gz
RUN mkdir /frontend && tar -xzf /tmp/frontend.tar.gz -C /frontend --strip-components=1
WORKDIR /frontend
RUN npm ci --no-audit --no-fund && npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=3001 \
    POTHOLE_MODEL_PATH=/srv/models/best.pt YOLO_DEVICE=cpu YOLO_OFFLINE=true \
    YOLO_AUTOINSTALL=false YOLO_VERBOSE=false STATIC_ROOT=/srv/www SECURE_COOKIES=true
WORKDIR /srv
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements.lock.txt ./
RUN pip install --no-cache-dir torch==2.14.1 torchvision==0.29.1 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.lock.txt -r requirements.txt
COPY app ./app
COPY migrations ./migrations
COPY scripts ./scripts
COPY alembic.ini ./alembic.ini
COPY models/best.pt ./models/best.pt
COPY --from=frontend /frontend/dist ./www
# El código, pesos y frontend son de solo lectura para el proceso de la aplicación.
RUN useradd --create-home --uid 10001 bachescan
USER 10001
EXPOSE 3001
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --no-access-log --log-level warning"]
