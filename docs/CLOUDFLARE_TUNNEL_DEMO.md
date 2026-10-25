# Share a temporary demo

Set up the app and matching real data using [Installation](INSTALLATION.md). Install an official [cloudflared release](https://github.com/cloudflare/cloudflared/releases), then put it on `PATH` or at `tools/cloudflared.exe`.

Double-click **Run_Cloudflare_Demo.cmd** and share the printed HTTPS URL. Keep this PC awake, online and the launcher open. Anyone with the link can reach the app. Press **Ctrl+C** to stop sharing; restarting generates a different address.

For an explicit executable path, run from the app directory:

```powershell
& '.venv/Scripts/python.exe' scripts/serve_tunnel.py `
  --cloudflared-path 'C:/Tools/cloudflared.exe' --no-browser
```

The launcher starts or reuses the local app at port 8040. Add `--port 8041` to change it, `--reuse-only` to require an existing server, or `--protocol http2` if UDP is blocked. `--help` lists all options.

Calculations and datasets remain on this PC. Stopping the launcher leaves a reused local server running and stops a server it started itself. Quick Tunnels provide temporary sharing without an uptime guarantee; see [Cloudflare's limits](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/). For hosting independently of this PC, use the [Cloudflare hosting guide](CLOUDFLARE_DEPLOYMENT.md).
