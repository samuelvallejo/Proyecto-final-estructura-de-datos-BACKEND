FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=3001 POTHOLE_MODEL_PATH=/srv/models/best.pt YOLO_DEVICE=cpu YOLO_OFFLINE=true YOLO_AUTOINSTALL=false YOLO_VERBOSE=false
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
COPY MODELO_LOCAL.md ./MODELO_LOCAL.md
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --no-access-log --log-level warning"]
