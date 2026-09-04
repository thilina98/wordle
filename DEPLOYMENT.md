# Deploying Wordle on your VPS

Written for: 3 vCPU, 4 GB RAM, native IPv6, NAT (shared) IPv4, no domain,
Hermes Agent already running on the box.

---

## Short answer

Your VPS is not too weak. It is 20 times bigger than this app needs.

**Use Docker.** Not because the app is heavy, but because Hermes Agent already
owns the system Python and you do not want the two fighting over it.

**Your real problem is not power. It is reach.** Read the next section before
you pick how to expose the site.

---

## The problem you actually have

Two facts decide everything else.

**1. Half the internet cannot reach an IPv6-only address.**
Google measures IPv6 users at just over 50% worldwide (it crossed the halfway
mark in March 2026). So if you publish only `http://[your-ipv6]:8000`, roughly
half your visitors get a timeout. Not an error page. A timeout.

**2. You do not own your IPv4 address.**
NAT IPv4 means the address is shared with other customers. Your provider
forwards a handful of ports to you — usually something like 20000-20100, almost
never 80 or 443. Two consequences:

- The URL will look like `http://185.x.x.x:20001`, not `http://185.x.x.x`.
- You cannot get an HTTPS certificate for that address, because you cannot
  prove you own it.

**Why fact 2 matters more than it looks.** This site is protected by a password.
Over plain HTTP, that password crosses the network in clear text. Anyone
between the visitor and your VPS can read it — a café Wi-Fi, an ISP, a hop in
between. If you only ever open the site from your own network, that risk is
yours to take. If you send the link to other people, get HTTPS.

---

## Step 0: find out what your provider gave you

Do this first. Everything else depends on the answer.

```bash
# Your public IPv6 (full ports, all yours)
ip -6 addr show scope global | grep inet6

# What the outside world sees
curl -6 -s https://ifconfig.co ; echo
curl -4 -s https://ifconfig.co ; echo    # the shared NAT address

# Is anything already on port 80/8000?
sudo ss -tlnp | grep -E ':(80|443|8000)\b'
```

Then open your provider's control panel and write down **the forwarded port
range**. It is the single piece of information this guide cannot get for you.

If `curl -4` returns an address, your outbound IPv4 works. Good — that is all
the tunnel options in the next section need.

---

## Should you use Docker?

Yes. Here is the honest accounting.

**What Docker costs you**

The daemon is a fixed background cost — tens of megabytes on a Linux server.
(Ignore the multi-gigabyte figures you find online; those are Docker Desktop on
Mac and Windows, which runs a whole virtual machine. Your VPS does not.)
This app's container adds roughly 100 MB while running. Measure it yourself
after starting:

```bash
docker stats --no-stream
systemctl status docker --no-pager | grep Memory
```

**What Docker buys you**

- Hermes Agent needs Python 3.11+ on this box. This app needs its own
  dependencies. In a container they cannot break each other.
- `restart: unless-stopped` — the app comes back after a reboot or a crash,
  with no work from you.
- Log rotation is configured, so logs cannot fill the disk.
- Redeploying is two commands, and rolling back is one.

**Your budget**

| | RAM |
|---|---|
| Total | 4096 MB |
| Debian/Ubuntu base | ~200 MB |
| Docker daemon | ~50-80 MB |
| **Wordle container** | **~100 MB** |
| Hermes Agent (API only) | ~500 MB-1 GB |
| Hermes Agent (local memory/models) | 2 GB+ |
| Left over | 1-3 GB |

Comfortable, unless you run local LLMs for Hermes. If you do, keep the 512 MB
limit that `docker-compose.yml` already sets on Wordle so it can never crowd
Hermes out.

**When to skip Docker.** If you want the absolute smallest footprint, run it
under systemd instead — see [Option B](#option-b-systemd-no-docker) at the end.
It saves the daemon's 50-80 MB and costs you the four things listed above. On a
4 GB box that trade is not worth it. Use Docker.

---

## Step 1: install Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker            # or log out and back in
docker run --rm hello-world
```

---

## Step 2: get the code onto the box

```bash
sudo mkdir -p /opt/wordle && sudo chown $USER /opt/wordle
git clone <your-github-url> /opt/wordle
cd /opt/wordle
```

---

## Step 3: set the two secrets

The app will not start without these. That is on purpose — a default password is
not a password.

```bash
cd /opt/wordle
cp .env.example .env

# Generate a real signing key
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Edit `.env`:

```ini
WORDLE_PASSWORD=the-password-you-will-share
WORDLE_SECRET_KEY=<paste the generated key>
WORDLE_COOKIE_SECURE=false
```

```bash
chmod 600 .env
```

**About `WORDLE_COOKIE_SECURE`.** Leave it `false` while you serve plain HTTP.
Set it `true` the moment you have HTTPS — with it on, the browser refuses to
send the session cookie over HTTP, and you will get an endless login loop and
no clue why.

---

## Step 4: start it

```bash
cd /opt/wordle
docker compose up -d --build
docker compose logs -f          # Ctrl-C to stop watching
curl -s localhost:8000/healthz  # expect {"status":"ok"}
```

The compose file uses `network_mode: host`. That is deliberate:

- The container answers on IPv6 **and** IPv4 with no extra configuration.
  Docker's normal port publishing (`-p 80:8000`) only writes IPv4 firewall
  rules unless you enable IPv6 in `/etc/docker/daemon.json`, and the exact
  behaviour differs between Docker versions. Host networking sidesteps all of it.
- Your firewall keeps working. Published Docker ports bypass `ufw` rules —
  a classic way to expose a service you thought was blocked. With host
  networking there is no port publishing, so `ufw` applies normally.

---

## Step 5: firewall

```bash
sudo ufw allow 22/tcp                 # keep your SSH in first
sudo ufw allow 8000/tcp               # only if exposing 8000 directly
sudo ufw --force enable
sudo ufw status verbose
```

`ufw` covers IPv6 too, as long as `IPV6=yes` is set in `/etc/default/ufw`
(it is, by default, on current Debian and Ubuntu).

---

## Step 6: pick how people reach it

This is the decision that matters. Four options, honestly compared.

| | Who can reach it | HTTPS | URL | Domain needed | Third party |
|---|---|---|---|---|---|
| **A. Tailscale Funnel** | everyone | yes, free | stable `ts.net` name | no | Tailscale |
| **B. NAT IPv4 port** | everyone | **no** | `http://ip:20001` | no | none |
| **C. Direct IPv6** | ~half of users | possible | `http://[ipv6]:8000` | no | none |
| **D. Cloudflare Quick Tunnel** | everyone | yes, free | **changes on restart** | no | Cloudflare |

**Recommended: A.** It is the only option that gives you HTTPS and reaches
everyone without a domain.

### Option A — Tailscale Funnel (recommended)

Funnel gives you a public HTTPS URL like
`https://your-box.your-tailnet.ts.net`. Tailscale accepts the traffic and
forwards it to your VPS over a connection your VPS opened outward, so no
inbound port and no NAT problem. It is on the free Personal plan.

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Funnel is off by default and needs turning on in **two** places — the admin
console and the machine. In the Tailscale admin console, enable Funnel for your
tailnet (Access Controls → add the `funnel` node attribute). Then:

```bash
sudo tailscale funnel --bg 8000
sudo tailscale funnel status        # shows your public URL
```

Then set HTTPS on, because Tailscale terminates TLS for you:

```bash
sed -i 's/WORDLE_COOKIE_SECURE=false/WORDLE_COOKIE_SECURE=true/' .env
docker compose up -d
```

Worth knowing:

- Funnel only listens on 443, 8443 and 10000. You do not choose the public
  port; `--bg 8000` means "forward the public 443 to my local 8000".
- The name is always `*.ts.net`. No custom domain.
- Funnel is still labelled beta.
- Anyone with the link can reach the page. That is what you want here — your
  password is what keeps them out.

### Option B — the NAT IPv4 port (simplest, no HTTPS)

Take a port from your forwarded range, say the panel forwards public `20001` to
your `8000`. Then the site is at `http://<shared-ipv4>:20001`.

Nothing to install. Works for every visitor. But the password travels in clear
text, so treat this as a "just me, just testing" option, or pair it with a
password you use nowhere else.

If your provider maps only a fixed internal port, change the port in
`docker-compose.yml` and in `ufw` to match.

### Option C — direct IPv6, with a real certificate

Your IPv6 address is genuinely yours, all ports included. And since January
2026 Let's Encrypt issues certificates **for IP addresses**, so you can have
real HTTPS with no domain at all.

The catches are real: only about half of visitors have IPv6 at all, IP
certificates last ~6 days so renewal must be automated, and you must use the
`http-01` or `tls-alpn-01` challenge (DNS validation cannot work for an IP).
With Caddy in front:

```
# /etc/caddy/Caddyfile
[2001:db8::1] {
    tls { ca https://acme-v02.api.letsencrypt.org/directory
          ca_root /etc/ssl/certs/ca-certificates.crt }
    reverse_proxy localhost:8000
}
```

Useful as a second door alongside Option A. Not enough on its own.

### Option D — Cloudflare Quick Tunnel (for a quick test)

```bash
docker run --rm --network host cloudflare/cloudflared:latest \
  tunnel --url http://localhost:8000 --edge-ip-version auto
```

It prints a free `https://something-random.trycloudflare.com` URL. No account,
no domain. But the URL changes every time the tunnel restarts, and Cloudflare
does not intend it for permanent use. Good for showing someone the site in the
next ten minutes; not for keeping it up.

If your VPS ever loses outbound IPv4, add `--edge-ip-version 6`. `auto` picks
for you based on what the OS has, which on your box means IPv4 via NAT.

---

## Step 7: check it works

```bash
# On the box
curl -s localhost:8000/healthz

# The gate must hold: this has to be 303, not 200
curl -s -o /dev/null -w "%{http_code}\n" localhost:8000/

# And this must be 401, not 200
curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:8000/api/games
```

Then open the URL on your phone, on mobile data rather than your own Wi-Fi.
That is the test that catches "works for me only" — especially with Option C.

---

## Running it day to day

```bash
docker compose logs -f --tail=100     # watch logs
docker compose restart                # restart
docker compose down                   # stop
docker stats --no-stream              # what it is using

# Update after pushing changes
cd /opt/wordle && git pull && docker compose up -d --build

# Change the password
nano .env && docker compose up -d     # everyone is logged out
```

There is nothing to back up but `.env`. No database, no volumes, no state on
disk.

---

## Things that will bite you

**Restarting ends games in progress.** Games are held in the app's memory. A
restart wipes them and players get "that game expired" and a fresh board. Fine
for a word game; know that it is the behaviour.

**Run exactly one worker.** The compose file sets `--workers 1`. Do not raise
it. A second worker is a separate process with its own memory, so it cannot see
games the first one created, and players would get random 404s. If you ever need
more than one, games have to move to Redis first — the code has a `GameStore`
protocol for exactly that.

**`WORDLE_COOKIE_SECURE=true` on plain HTTP means an endless login loop.** The
browser silently refuses to send the cookie. Match the setting to your setup.

**Docker's published ports ignore `ufw`.** Not an issue with the compose file as
written, because it uses host networking. It becomes an issue the moment
someone switches it to `-p`.

**The login throttle is per process.** Ten wrong passwords locks that IP out for
five minutes. It is a speed bump, not a rate limiter. If the site is on the open
internet and you care, put a real limit in front of it — Cloudflare or Caddy.

**Hermes Agent and Wordle both want to be up.** Give Wordle the 512 MB limit the
compose file already sets, so a runaway container cannot starve Hermes.

---

## Option B: systemd, no Docker

Only if you want the last 50 MB back.

```bash
sudo apt update && sudo apt install -y python3-venv git
sudo mkdir -p /opt/wordle && sudo chown $USER /opt/wordle
git clone <your-github-url> /opt/wordle
cd /opt/wordle/backend
python3 -m venv .venv
.venv/bin/pip install poetry
.venv/bin/poetry install --only main
```

```ini
# /etc/systemd/system/wordle.service
[Unit]
Description=Wordle
After=network-online.target

[Service]
Type=exec
User=wordle
WorkingDirectory=/opt/wordle/backend
EnvironmentFile=/opt/wordle/.env
Environment=WORDLE_FRONTEND_DIR=/opt/wordle/frontend
ExecStart=/opt/wordle/backend/.venv/bin/uvicorn wordle.app:create_app \
  --factory --host :: --port 8000 --workers 1 \
  --proxy-headers --forwarded-allow-ips '*'
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true

[Install]
WantedBy=multi-user.target
```

```bash
sudo useradd --system --no-create-home wordle
sudo systemctl daemon-reload
sudo systemctl enable --now wordle
sudo systemctl status wordle --no-pager
```

Python 3.11 or newer is required. Check with `python3 --version` — Debian 12
ships 3.11, Ubuntu 24.04 ships 3.12, both fine.

---

## Sources

- IPv6 adoption crossing 50%: [Internet Society Pulse](https://pulse.internetsociety.org/en/blog/2026/04/18-years-later-ipv6-reaches-majority/), [APNIC](https://blog.apnic.net/2026/04/28/google-hits-50-ipv6/), [Google IPv6 statistics](https://www.google.com/intl/en/ipv6/statistics.html)
- NAT VPS port forwarding: [LowEndTalk on how NAT VPS works](https://lowendtalk.com/discussion/102645/how-do-people-offer-nat-vps), [IPv4 shared address space](https://en.wikipedia.org/wiki/IPv4_shared_address_space)
- Tailscale Funnel, free plan, port limits, double opt-in: [Funnel docs](https://tailscale.com/kb/1223/tailscale-funnel/), [funnel CLI](https://tailscale.com/kb/1311/tailscale-funnel), [free plan](https://tailscale.com/kb/1154/free-plans-discounts)
- Let's Encrypt IP address certificates: [general availability, Jan 2026](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability), [certificate profiles](https://letsencrypt.org/docs/profiles/), [Certbot support](https://letsencrypt.org/2026/03/11/shorter-certs-certbot)
- Cloudflare Quick Tunnels and IPv6 edge connections: [Quick Tunnels](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/run-parameters/), [cloudflared IPv6-only hosts](https://www.forwardingplane.net/post/2025-01-11-cloudflared-tunnel-ipv6/)
- Docker IPv6 for published ports: [Docker docs](https://docs.docker.com/engine/daemon/ipv6/)
- Hermes Agent requirements: [Nous Research Hermes Agent](https://hermes-agent.ai/blog/best-vps-for-hermes-agent)
