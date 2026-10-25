"""Cloudflare Container entrypoint: one ASGI process and no browser launch."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    import uvicorn
    port = int(os.environ.get('PORT', '8080'))
    if not 1 <= port <= 65535:
        raise ValueError('PORT must be between 1 and 65535')
    # Forwarded request headers are trusted only after the Worker/container
    # boundary; no multi-worker fork duplicates large dataset verification.
    uvicorn.run('backend.app:app', host='0.0.0.0', port=port, workers=1,
                access_log=False, proxy_headers=True, forwarded_allow_ips='*')


if __name__ == '__main__':
    main()
