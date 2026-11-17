# Dashboard and phone access (Tailscale)

The dashboard (`dashboard/server.py`) is a read-only web page showing the
composite score and its components, score history, stock picks, Polymarket
odds, Gulf news headlines and data freshness. It refreshes every minute.

It listens on **127.0.0.1:8050 only**, so nothing is exposed on your Wi-Fi or
the internet. Your phone reaches it through Tailscale, a private network
between your own devices, using `tailscale serve`, which proxies the local port
to an HTTPS address that only devices signed in to your tailnet can open.

## On the PC (WSL)

The service is installed by `deploy/install.sh --apply`; enable it with:

```bash
systemctl --user enable --now dashboard
curl -s localhost:8050/healthz        # -> ok
```

Open http://localhost:8050 in a Windows browser to check it.

Install Tailscale inside WSL. Two ways:

**A. Rootless (no sudo; what this machine uses).** Tailscale's static build runs
as a user service in userspace-networking mode, which is all `tailscale serve`
needs:

```bash
V=$(curl -fsSL "https://pkgs.tailscale.com/stable/?mode=json" | python3 -c "import json,sys;print(json.load(sys.stdin)['TarballsVersion'])")
F=tailscale_${V}_amd64.tgz
curl -fsSLO https://pkgs.tailscale.com/stable/$F
echo "$(curl -fsSL https://pkgs.tailscale.com/stable/$F.sha256)  $F" | sha256sum -c
tar xzf $F && mkdir -p ~/.local/lib/tailscale ~/.local/share/tailscale ~/.local/bin
cp tailscale_${V}_amd64/tailscale tailscale_${V}_amd64/tailscaled ~/.local/lib/tailscale/
printf '#!/bin/sh\nexec "$HOME/.local/lib/tailscale/tailscale" --socket="$HOME/.local/share/tailscale/tailscaled.sock" "$@"\n' > ~/.local/bin/tailscale
chmod 755 ~/.local/bin/tailscale
deploy/install.sh --apply                  # installs deploy/systemd/tailscaled.service
systemctl --user enable --now tailscaled
tailscale up --hostname=gulf-monitor       # prints a login URL; open it, click Connect
tailscale serve --bg 8050                  # first time: prints a link to enable Serve
tailscale serve status
```

To update later, repeat the download/copy lines and `systemctl --user restart tailscaled`.

**B. System package (needs sudo):**

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
sudo tailscale set --operator=$USER    # lets you run `tailscale serve` without sudo
tailscale serve --bg 8050
tailscale serve status
```

If `tailscale serve` says HTTPS is not enabled for your tailnet, open the link
it prints (admin console → DNS → enable MagicDNS and HTTPS Certificates) and run
it again. `--bg` makes the setting persistent across reboots.

Optional: God's Eye View on the phone too (heavy 3D page, better on a tablet):

```bash
tailscale serve --bg --https 8443 4173
```

## On the phone

1. Install the Tailscale app (App Store / Play Store) and sign in with the
   same account.
2. Open the `https://<name>.<tailnet>.ts.net` URL from `tailscale serve status`.
3. Share → **Add to Home Screen** to get an app-like icon.

## Notes

- The phone sees live data only while the PC is awake. When Windows sleeps,
  WSL pauses too; the page then shows "offline", and on wake the
  **Data freshness** panel flags anything stale with ⚠.
- To stop sharing: `tailscale serve reset`. To stop the dashboard:
  `systemctl --user disable --now dashboard`.
- Change the port with `DASHBOARD_PORT=...` in the unit (and the `serve` target).
  Do not set `DASHBOARD_HOST=0.0.0.0` unless you want it on your LAN without a
  password.
