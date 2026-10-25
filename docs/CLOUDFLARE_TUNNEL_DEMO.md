# Free Cloudflare Tunnel demo

Double-click **Run_Cloudflare_Demo.cmd**. It starts or reuses the real local
DrainCheck API, starts an existing official `cloudflared` executable and prints
the temporary public HTTPS URL. The map and calculations continue to use this
computer's complete real datasets and existing application functions.

**Keep this PC online and the launcher running.** Anyone with the generated
link can reach the app. Press **Ctrl+C** in the launcher's window to stop
sharing. A new run creates a new hostname, so share the latest printed URL.
This is a temporary demonstration, with no uptime guarantee or paid upgrade.
It does not move the application or its datasets into Cloudflare Containers.

The original **Run_Sofia_App.cmd** still runs the app locally. If the demo reuses
an already running app, stopping the demo leaves that app running. If the demo
starts its own API process, it stops that process when the demo ends. On
Windows, the launcher's child-process cleanup group also closes its own
children if the launcher is forcibly terminated; it never includes an existing
local server.

## Existing executable

The launcher does not install or download software and does not request an
account, token or payment. It searches these locations in order:

1. An explicit `--cloudflared-path` argument.
2. The `DRAINCHECK_CLOUDFLARED_PATH` environment variable.
3. `tools/cloudflared.exe` inside the app.
4. `cloudflared` on the system's executable search path.
5. On this computer, the preserved task executable at
   `../../work/cloudflare-tunnel/cloudflared-2026.10.3.exe` relative to the app.

The official Windows amd64 2026.10.3 release used for this demo is 55,329,336
bytes, SHA256
`76b2805253d0d6ffacb092a7acfbee99e7af6917835c0c5410e23f3ef5052da2`.
The binary remains outside the source repository. Obtain any replacement
directly from [Cloudflare's official releases](https://github.com/cloudflare/cloudflared/releases).

## Command line

Run from the application directory using its Python environment:

```powershell
& '..\..\work\hydro_env\Scripts\python.exe' scripts/serve_tunnel.py --no-browser
```

Specify an executable on another computer:

```powershell
& '.venv\Scripts\python.exe' scripts/serve_tunnel.py `
  --cloudflared-path 'C:\Tools\cloudflared.exe' --no-browser
```

Add `--reuse-only` to require an already running app. The default local port is
8040; `--port 8041` selects another port. The launcher checks DrainCheck's
application identity and genuine native-terrain/spatial-data readiness before
sharing. It refuses a port occupied by another application.

Use `--protocol http2` if the network blocks UDP/QUIC. The default `auto`
protocol follows Cloudflare's own connection selection. `--help` lists options
without starting an app, accessing the network or opening a tunnel.

## Scope and limits

Cloudflare forwards HTTPS requests to the existing local API. All risk modes,
terrain, buildings, historical floods, rainfall, area selection, pipe-blockage
calculations and downloads remain the same application. Scenario results and
saved local colour scales stay in the existing local data cache. The private
R2 adapter is used only by the separate prepared Container deployment, whose
environment variables are absent from the local launcher.

Quick Tunnels support up to 200 simultaneous requests and do not support
Server-Sent Events. The current app uses normal HTTP requests and map tiles.
Full cloud-hosting preparation remains in `cloudflare/`, the Dockerfile and
[the separate deployment guide](CLOUDFLARE_DEPLOYMENT.md).

Source: [Cloudflare Quick Tunnels documentation](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).
