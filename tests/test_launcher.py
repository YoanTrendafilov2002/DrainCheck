"""Executable launcher regression: existing APIs are reused across title changes."""
import json,subprocess,sys,threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from backend.app import app

@pytest.mark.parametrize('older_api',[False,True],ids=['stable-application-id','compatible-older-api'])
def test_launcher_reuses_api_after_rainfall_title_change(older_api):
    metadata=TestClient(app).get('/api/meta').json()
    if older_api:metadata.pop('application_id')
    metadata['config']['name']='Sofia Terrain, Sewer, Rainfall & Pluvial Screening Explorer'
    body=json.dumps(metadata).encode('utf-8')
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.path=='/api/meta'
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(body)
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        root=Path(__file__).resolve().parents[1]
        result=subprocess.run([sys.executable,'scripts/serve.py','--port',str(server.server_port),'--no-browser'],
                              cwd=root,capture_output=True,text=True,timeout=10)
        assert result.returncode==0,result.stderr
        assert 'already running' in result.stdout
        assert 'Started server' not in result.stderr
    finally:
        server.shutdown();server.server_close();thread.join(timeout=2)
