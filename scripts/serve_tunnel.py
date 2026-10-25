"""Share the real local DrainCheck app through a temporary Cloudflare Quick Tunnel.

No account, payment, software download or credential is used by this launcher.
The computer, local API and this process must stay online for the URL to work.
"""
import argparse
import json
import os
from pathlib import Path
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
QUICK_URL = re.compile(r'https://[a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com(?![a-z0-9.-])')


class OriginConflict(RuntimeError):
    """The local port is occupied or the real application is not ready."""


def application_identity(metadata):
    if not isinstance(metadata, dict):
        return False
    if 'application_id' in metadata:
        return metadata['application_id'] == 'sofia-terrain-explorer'
    config = metadata.get('config', {})
    return (isinstance(config, dict) and config.get('project') == 'rivertracker-512606'
            and config.get('elevation', {}).get('asset')
            == 'projects/rivertracker-512606/assets/sofia_dtm_2024_1m_gee'
            and 'revision' in metadata and 'terrain_sources' in metadata)


def origin_ready(origin, timeout=2):
    """Only reuse this app; never tunnel an unrelated service on the same port."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(origin + '/api/meta', timeout=timeout) as response:
            metadata = json.load(response)
        if not application_identity(metadata):
            raise OriginConflict('The local port belongs to a different application; no tunnel was started.')
        with opener.open(origin + '/api/health', timeout=timeout) as response:
            health = json.load(response)
        if not isinstance(health, dict) or health.get('status') != 'ok':
            return False
        if not health.get('spatial_ready') or not health.get('terrain_available'):
            raise OriginConflict('DrainCheck is running, but its real spatial data or native DTM is unavailable. Restore the existing data before sharing it.')
        return True
    except OriginConflict:
        raise
    except (urllib.error.URLError, OSError, ValueError):
        return False


def port_occupied(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=1):
            return True
    except OSError:
        return False


def cloudflared_binary(explicit=None):
    candidates = [explicit] if explicit else []
    if not explicit:
        candidates += [os.environ.get('DRAINCHECK_CLOUDFLARED_PATH'),
                       ROOT / 'tools/cloudflared.exe', shutil.which('cloudflared'),
                       ROOT.parents[1] / 'work/cloudflare-tunnel/cloudflared-2026.10.3.exe']
    for value in candidates:
        if value:
            path = Path(value).expanduser().resolve()
            if path.is_file():
                return path
    raise RuntimeError('Official cloudflared executable not found. Supply --cloudflared-path PATH; this launcher never downloads software.')


class OwnedChildren:
    """Stop only children we started; Windows also cleans up a forced exit."""
    def __init__(self):
        self.children = []
        self.job = None
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            size_t = ctypes.c_size_t
            class BasicLimits(ctypes.Structure):
                _fields_ = [('process_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong),
                            ('flags', wintypes.DWORD), ('min_working_set', size_t),
                            ('max_working_set', size_t), ('active_processes', wintypes.DWORD),
                            ('affinity', size_t), ('priority', wintypes.DWORD), ('scheduling', wintypes.DWORD)]
            class IoCounters(ctypes.Structure):
                _fields_ = [(name, ctypes.c_ulonglong) for name in
                            ['read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes']]
            class ExtendedLimits(ctypes.Structure):
                _fields_ = [('basic', BasicLimits), ('io', IoCounters), ('process_memory', size_t),
                            ('job_memory', size_t), ('peak_process_memory', size_t), ('peak_job_memory', size_t)]
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
            kernel.CreateJobObjectW.restype = wintypes.HANDLE
            kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
            kernel.SetInformationJobObject.restype = wintypes.BOOL
            kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
            kernel.AssignProcessToJobObject.restype = wintypes.BOOL
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle.restype = wintypes.BOOL
            self.kernel = kernel
            self.job = kernel.CreateJobObjectW(None, None)
            limits = ExtendedLimits()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not self.job or not kernel.SetInformationJobObject(self.job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                if self.job:
                    kernel.CloseHandle(self.job)
                self.job = None
                raise RuntimeError('Windows could not create the demo child-process cleanup group.')

    def start(self, command, **kwargs):
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        process = subprocess.Popen(command, creationflags=flags, **kwargs)
        self.children.append(process)
        if self.job and not self.kernel.AssignProcessToJobObject(self.job, int(process._handle)):
            process.terminate()
            process.wait(timeout=10)
            raise RuntimeError('Windows could not attach the demo child process to its cleanup group.')
        return process

    def close(self):
        for process in reversed(self.children):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            if process.stdout:
                process.stdout.close()
        if self.job:
            self.kernel.CloseHandle(self.job)
            self.job = None


def read_lines(process, events, name):
    try:
        for line in process.stdout:
            events.put((name, line.rstrip()))
    except (OSError, ValueError):
        pass  # The owner closed the pipe while stopping its child process.


def log_message(line):
    try:
        record = json.loads(line)
        return str(record.get('message', line)) if isinstance(record, dict) else line
    except ValueError:
        return line


def tunnel_command(executable, origin, protocol):
    return [str(executable), 'tunnel', '--url', origin, '--no-autoupdate', '--protocol', protocol]


def print_events(events):
    while True:
        try:
            name, line = events.get_nowait()
        except queue.Empty:
            return
        print(f'[{name}] {log_message(line)}', flush=True)


def wait_origin(origin, process, events, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        print_events(events)
        if process.poll() is not None:
            raise RuntimeError('The local DrainCheck API exited before it was ready. See its messages above.')
        if origin_ready(origin):
            return
        time.sleep(.3)
    raise RuntimeError('The local DrainCheck API did not become ready before the startup timeout.')


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('--cloudflared-path', help='Existing official cloudflared executable; no download is performed')
    result.add_argument('--port', type=int, default=8040, help='Local DrainCheck port (default: 8040)')
    result.add_argument('--no-browser', action='store_true', help='Print the public URL without opening a browser')
    result.add_argument('--reuse-only', action='store_true', help='Require an already running DrainCheck API')
    result.add_argument('--startup-timeout', type=float, default=240, help='Seconds to wait for a newly started local API')
    result.add_argument('--protocol', choices=['auto', 'http2', 'quic'], default='auto', help='Cloudflare connection protocol; use http2 if UDP is unavailable')
    return result


def main(argv=None):
    arguments = parser().parse_args(argv)
    if not 1 <= arguments.port <= 65535 or not 0 < arguments.startup_timeout <= 600:
        parser().error('Port must be 1..65535 and startup timeout must be greater than zero and at most 600 seconds.')
    children = None
    try:
        executable = cloudflared_binary(arguments.cloudflared_path)
        origin = f'http://127.0.0.1:{arguments.port}'
        events = queue.Queue()
        children = OwnedChildren()
        owned_api = None
        if origin_ready(origin):
            print('Reusing the verified local DrainCheck app at ' + origin, flush=True)
        else:
            if port_occupied(arguments.port):
                raise OriginConflict('The local port is occupied but the DrainCheck API is not ready. Start or repair the local app first.')
            if arguments.reuse_only:
                raise RuntimeError('DrainCheck is not running. Start Run_Sofia_App.cmd first, or omit --reuse-only.')
            print('Starting the real local DrainCheck API at ' + origin, flush=True)
            owned_api = children.start([sys.executable, '-m', 'uvicorn', 'backend.app:app',
                                       '--host', '127.0.0.1', '--port', str(arguments.port), '--no-access-log'],
                                      cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      text=True, encoding='utf-8', errors='replace', bufsize=1)
            threading.Thread(target=read_lines, args=(owned_api, events, 'DrainCheck'), daemon=True).start()
            wait_origin(origin, owned_api, events, arguments.startup_timeout)
        print('Starting a free temporary Cloudflare Tunnel. Keep this PC online and this window open.', flush=True)
        print('Press Ctrl+C to stop sharing. The local app continues running if it was already open.', flush=True)
        tunnel = children.start(tunnel_command(executable, origin, arguments.protocol),
                                cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding='utf-8', errors='replace', bufsize=1)
        print(f'Launcher PID: {os.getpid()} | Tunnel PID: {tunnel.pid}', flush=True)
        threading.Thread(target=read_lines, args=(tunnel, events, 'Cloudflare'), daemon=True).start()
        public_url = None
        deadline = time.monotonic() + 120
        while tunnel.poll() is None:
            if owned_api is not None and owned_api.poll() is not None:
                raise RuntimeError('The local DrainCheck API stopped; the tunnel is being closed.')
            try:
                name, line = events.get(timeout=.3)
                message = log_message(line)
                print(f'[{name}] {message}', flush=True)
                match = QUICK_URL.search(message)
                if public_url is None and match:
                    public_url = match.group(0)
                    print('\nPublic demo URL: ' + public_url, flush=True)
                    print('This link reaches the app on this PC; it ends when this launcher stops.\n', flush=True)
                    if not arguments.no_browser:
                        webbrowser.open(public_url)
            except queue.Empty:
                pass
            if public_url is None and time.monotonic() > deadline:
                raise RuntimeError('Cloudflare did not provide a temporary URL within 120 seconds. Check the connection messages above; try --protocol http2 if UDP is blocked.')
        print_events(events)
        raise RuntimeError(f'Cloudflare Tunnel stopped (exit code {tunnel.returncode}).')
    except KeyboardInterrupt:
        print('\nStopping the public demo...', flush=True)
        return 0
    except (RuntimeError, OSError) as error:
        print('Demo not started or stopped: ' + str(error), file=sys.stderr, flush=True)
        return 1
    finally:
        if children is not None:
            children.close()


if __name__ == '__main__':
    raise SystemExit(main())
