FROM node:22-bookworm-slim AS web-build
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
ENV NEXT_TELEMETRY_DISABLED=1
ENV API_INTERNAL_URL=http://127.0.0.1:8000
RUN npm run build

FROM python:3.12-slim-bookworm
WORKDIR /app
COPY --from=web-build /usr/local/bin/node /usr/local/bin/node
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home lab
COPY --chown=lab:lab backend/ /app/api/
COPY --from=web-build --chown=lab:lab /build/.next/standalone /app/web/
COPY --from=web-build --chown=lab:lab /build/.next/static /app/web/.next/static/
COPY --chown=lab:lab deploy/start_free.py /app/start_free.py
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER lab
EXPOSE 10000
CMD ["python", "/app/start_free.py"]
