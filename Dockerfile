# ===== web ui: node builds the vue app (needs the backend version file and the help guide)
FROM node:22-slim AS web
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY backend/nfiforge/__init__.py /src/backend/nfiforge/__init__.py
COPY docs/HELP.md /src/docs/HELP.md
COPY frontend/ ./
RUN npm run build

# ===== app: python serves the api and the built ui on one port
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY backend ./backend
COPY --from=web /src/frontend/dist ./backend/nfiforge/web
# btcgate is included but off unless btcgate.enabled; git only to fetch it, removed after
RUN apt-get update && apt-get install -y --no-install-recommends git \
  && pip install --no-cache-dir ".[btcgate]" \
  && apt-get purge -y git && apt-get autoremove -y && rm -rf /var/lib/apt/lists/* \
  && useradd -r -u 1000 nfiforge && mkdir /data && chown nfiforge /data
USER nfiforge
EXPOSE 8880
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import json,os,urllib.request; p=os.environ.get('NFIFORGE_PORT','8880'); urllib.request.urlopen(f'http://127.0.0.1:{p}/api/health', timeout=4)"
ENTRYPOINT ["nfiforge"]
CMD ["--config", "/data/config.yaml"]
