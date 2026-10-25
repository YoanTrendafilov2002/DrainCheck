"""Verify that the demo shares only DrainCheck and cleans up its own children."""
import importlib.util
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import threading

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('serve_tunnel', ROOT/'scripts/serve_tunnel.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


@pytest.fixture
def origin_server():
    documents = {'/api/meta': {'application_id': 'sofia-terrain-explorer'},
                 '/api/health': {'status': 'ok', 'terrain_available': True, 'spatial_ready': True}}
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            value = json.dumps(documents.get(self.path, {})).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(value)))
            self.end_headers()
            self.wfile.write(value)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', documents
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)


def test_help_is_available_without_a_binary_data_or_network():
    result = subprocess.run([sys.executable, str(ROOT/'scripts/serve_tunnel.py'), '--help'],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0
    assert '--cloudflared-path' in result.stdout and '--no-browser' in result.stdout
    assert '--reuse-only' in result.stdout and 'must stay online' in result.stdout


def test_http_readiness_rejects_wrong_application_and_missing_real_terrain(origin_server):
    origin, documents = origin_server
    assert launcher.origin_ready(origin) is True
    documents['/api/meta']['application_id'] = 'another-application'
    with pytest.raises(launcher.OriginConflict, match='different application'):
        launcher.origin_ready(origin)
    documents['/api/meta']['application_id'] = 'sofia-terrain-explorer'
    documents['/api/health']['terrain_available'] = False
    with pytest.raises(launcher.OriginConflict, match='native DTM'):
        launcher.origin_ready(origin)


def test_stopping_launcher_children_does_not_stop_an_existing_server_process():
    existing = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    children = launcher.OwnedChildren()
    try:
        owned = children.start([sys.executable, '-c', 'import time; time.sleep(60)'])
        children.close()
        assert owned.poll() is not None
        assert existing.poll() is None
    finally:
        children.close()
        existing.terminate()
        existing.wait(timeout=10)


def test_public_url_recognition_uses_only_official_quick_tunnel_hostnames():
    message = launcher.log_message(json.dumps({'message': 'Temporary URL: https://real-demo-url.trycloudflare.com'}))
    assert launcher.QUICK_URL.search(message).group(0) == 'https://real-demo-url.trycloudflare.com'
    assert launcher.QUICK_URL.search('https://trycloudflare.com.attacker.example') is None
    assert launcher.QUICK_URL.search('https://real.trycloudflare.com.attacker.example') is None
    assert launcher.QUICK_URL.search('https://other-host.example') is None


def test_official_executable_accepts_launcher_flags_without_creating_a_tunnel():
    try:
        executable = launcher.cloudflared_binary()
    except RuntimeError:
        pytest.skip('The separately verified official cloudflared executable is not installed')
    command = launcher.tunnel_command(executable, 'http://127.0.0.1:8040', 'auto')
    result = subprocess.run(command + ['--help'], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr or result.stdout
    assert 'cloudflared tunnel' in result.stdout
