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

Install Tailscale inside WSL (needs your sudo password; run each line yourself,
or prefix with `!` in Claude Code):

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up                      # prints a login URL; sign in
sudo tailscale set --operator=$USER    # lets you run `tailscale serve` without sudo
tailscale serve --bg 8050              # HTTPS on your tailnet -> 127.0.0.1:8050
tailscale serve status                 # shows the https://<name>.<tailnet>.ts.net URL
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
