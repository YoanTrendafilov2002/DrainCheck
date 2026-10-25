"""Run the local app and open it only after its own API responds."""
import argparse,json,sys,threading,time,urllib.request,webbrowser
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uvicorn

def is_sofia_explorer(metadata):
    """Recognize this API independently of its user-facing release title."""
    if metadata.get('application_id')=='sofia-terrain-explorer':return True
    config=metadata.get('config',{})
    return (config.get('project')=='rivertracker-512606' and
            config.get('elevation',{}).get('asset')=='projects/rivertracker-512606/assets/sofia_dtm_2024_1m_gee' and
            'revision' in metadata and 'terrain_sources' in metadata)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8040);parser.add_argument('--no-browser',action='store_true')
    args=parser.parse_args();url=f'http://127.0.0.1:{args.port}'
    already_running=False
    try:
        with urllib.request.urlopen(url+'/api/meta',timeout=1) as response:
            already_running=is_sofia_explorer(json.load(response))
    except Exception:pass
    if already_running:
        print('Sofia explorer is already running at '+url)
        if not args.no_browser:webbrowser.open(url)
        raise SystemExit(0)
    if not args.no_browser:
        def open_when_ready():
            for _ in range(60):
                try:
                    with urllib.request.urlopen(url+'/api/meta',timeout=1) as response:
                        if is_sofia_explorer(json.load(response)):
                            webbrowser.open(url);return
                except Exception:time.sleep(.3)
        threading.Thread(target=open_when_ready,daemon=True).start()
    uvicorn.run('backend.app:app',host='127.0.0.1',port=args.port,access_log=False)
