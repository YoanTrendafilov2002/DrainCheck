# syntax=docker/dockerfile:1.7
# Private runtime data are restored from a BuildKit bind mount. The 4 GB TAR
# therefore never occupies a permanent image layer alongside its extracted files.
FROM node:22-bookworm-slim AS frontend
WORKDIR /web
RUN corepack enable && corepack prepare pnpm@11.25.0 --activate
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY index.html tsconfig.json vite.config.ts ./
COPY src ./src
COPY shared ./shared
COPY scripts/compress_dist.mjs ./scripts/compress_dist.mjs
RUN pnpm build

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 PROJ_NETWORK=OFF \
    SOFIA_DTM_PATH=/app/data/native/sofia_dtm_2024_1m_gee.tif \
    DRAINCHECK_DATA_MANIFEST=/app/runtime-data-manifest.json \
    DRAINCHECK_STATE_URL=http://draincheck-state.internal PORT=8080
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 draincheck \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin draincheck
COPY requirements-lock.txt ./
RUN pip install --no-cache-dir --only-binary=:all: -r requirements-lock.txt
COPY backend ./backend
COPY scripts ./scripts
COPY config ./config
COPY docs ./docs
COPY --from=frontend /web/dist ./dist
RUN --mount=type=bind,source=.cloudflare-data,target=/snapshot,readonly \
    python scripts/restore_cloudflare_data.py --archive /snapshot/runtime-data.tar \
      --manifest /snapshot/runtime-data-manifest.json --destination /app \
    && find /app/data -type f -exec chmod 0444 {} + \
    && find /app/data -type d -exec chmod 0555 {} + \
    && chmod 0444 /app/runtime-data-manifest.json \
    && chgrp 10001 /app/data/cache && chmod 1770 /app/data/cache \
    && mkdir /app/data/cache/rendered_tiles /app/data/cache/clogging \
    && chown 10001:10001 /app/data/cache/rendered_tiles /app/data/cache/clogging \
    && chmod 0700 /app/data/cache/rendered_tiles /app/data/cache/clogging
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD python -c "import json,urllib.request; r=json.load(urllib.request.urlopen('http://127.0.0.1:8080/api/health',timeout=4)); assert r.get('status')=='ok' and r.get('terrain_available') and r.get('spatial_ready')"
CMD ["python", "scripts/serve_cloud.py"]
