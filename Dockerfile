FROM node:22-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CNC_DB_PATH=/data/cnc.db

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

RUN mkdir -p /data /app/storage/dxf

EXPOSE 8000

CMD ["sh", "-c", "python -m backend.init_db && uvicorn backend.main:app --host 0.0.0.0 --port 8000"]
