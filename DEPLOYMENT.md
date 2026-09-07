# Deploying Wordle on your VPS

Written for: 3 vCPU, 4 GB RAM, native IPv6, NAT (shared) IPv4, no domain,
Hermes Agent already running on the box.

---

## Short answer

Your VPS is not too weak. It is 20 times bigger than this app needs.

**Use Docker.** Not because the app is heavy, but because Hermes Agent already
owns the system Python and you do not want the two fighting over it.

**Note there are two services**, run separately: the API on port 8000 and the
frontend's web server on port 8080. Only the frontend needs to be reachable by
visitors in a browser — but the browser also calls the API directly, so **both
ports must be reachable**. That shapes every option below.

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
| **Wordle API container** | **~100 MB** |
| **Wordle web container** (nginx) | **~10 MB** |
| Hermes Agent (API only) | ~500 MB-1 GB |
| Hermes Agent (local memory/models) | 2 GB+ |
| Left over | 1-3 GB |

Comfortable, unless you run local LLMs for Hermes. If you do, keep the limits
`docker-compose.yml` already sets — 512 MB on the API, 64 MB on nginx — so
neither can crowd Hermes out.

**When to skip Docker.** If you want the absolute smallest footprint, run it
under systemd instead — see the [systemd appendix](#appendix-systemd-no-docker) at the end.
It saves the daemon's 50-80 MB and costs you the four things listed above. On a
4 GB box that trade is not worth it. Use Docker.

---

## Step 1: install Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
```

### That block of text at the end is not an error

The script finishes by printing this, and it looks like a complaint:

```
To run Docker as a non-privileged user, consider setting up the
Docker daemon in rootless mode for your user:

    dockerd-rootless-setuptool.sh install

WARNING: Access to the remote API on a privileged Docker daemon is equivalent
         to root access on the host.
```

It is the script's **success message**. In the source it is a function called
`echo_docker_as_nonroot`, and it runs immediately after the daemon starts,
followed by `exit 0`:

```sh
start_docker_daemon
echo_docker_as_nonroot
exit 0
```

It is telling you two optional things: that rootless mode exists, and that
anyone you add to the `docker` group effectively has root. Neither is a
failure.

A real permissions failure from this script looks completely different, and
exits 1:

```
Error: this installer needs the ability to run commands as root.
We are unable to find either "sudo" or "su" available to make this happen.
```

Check which one you got:

```bash
echo $?                              # 0 means the install worked
systemctl is-active docker           # active
sudo docker version                  # both Client and Server sections print
```

### Then: running docker without sudo

This is the part people actually trip on. The daemon listens on a Unix socket
owned by root:

```bash
ls -l /var/run/docker.sock
# srw-rw---- 1 root docker 0 ... /var/run/docker.sock
```

Mode `rw-rw----` means root and the `docker` group can use it, nobody else. So
`docker ps` as your normal user gives:

```
permission denied while trying to connect to the Docker daemon socket
```

That is a file permission on the socket, not a problem with the install. Join
the group:

```bash
sudo usermod -aG docker $USER
newgrp docker            # or log out and back in
docker run --rm hello-world
```

`newgrp` is needed because group membership is attached to your login session.
Adding yourself to a group does not change the shell you are already sitting
in.

**What the WARNING meant.** Being in the `docker` group is equivalent to root:
you can start a container that mounts `/` and edit anything. That is expected
on a box you own. Do not add other people to it casually.

### One IPv6 note

Your VPS reaches the internet over NAT IPv4, so pulls work regardless. Worth
knowing anyway: Docker Hub now publishes AAAA records, so an IPv6-only host can
pull images too. That was not true for years.

```bash
dig +short AAAA registry-1.docker.io    # answers
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

Secrets go in files, not in `.env`. `docker inspect` and `/proc/<pid>/environ`
both show a container's environment; neither shows a mounted secret.

```bash
mkdir -p secrets
printf '%s' 'the-password-you-will-share' > secrets/wordle_password
python3 -c "import secrets; print(secrets.token_urlsafe(32), end='')" > secrets/wordle_secret_key
chmod 600 secrets/wordle_*
```

Everything else goes in `.env`:

```ini
# Both of these are what the BROWSER sees. Fill them in after Step 6,
# when you know your real URLs.
WORDLE_ALLOWED_ORIGINS=http://[your-ipv6]:8080
WORDLE_API_BASE=http://[your-ipv6]:8000
```

```bash
chmod 600 .env
```

**These last two are the setting people get wrong.** They are not container
addresses. They are the URLs a visitor's browser uses.

- `WORDLE_API_BASE` gets written into `frontend/config.js` when the web
  container starts. It is where the browser sends API calls.
- `WORDLE_ALLOWED_ORIGINS` is the API's CORS allow-list. It must be exactly
  where the browser loaded the page from — scheme, host and port, no trailing
  slash.

Symptom of getting them wrong: the password page loads fine, then logging in
does nothing. The browser console shows a CORS error, or the page says
"Cannot reach the server". Comma-separate the origins if you have more than one
way in (an IPv6 URL and a Tailscale URL, say).

---

## Step 4: start it

```bash
cd /opt/wordle
docker compose up -d --build
docker compose ps               # both api and web should be up, with ports
docker compose logs -f          # Ctrl-C to stop watching

curl -s localhost:8000/healthz  # API: expect {"status":"ok"}
curl -s -o /dev/null -w '%{http_code}\n' localhost:8080/   # web: expect 200
```

### What the compose file gives you

- **A named volume, `wordle-data`.** Games in progress live in SQLite there.
  Destroy the container, rebuild the image, `docker compose down` — the volume
  survives all of it. Only `docker volume rm wordle-data` removes it.
- **Both containers run as non-root** with a read-only root filesystem, all
  Linux capabilities dropped, and `no-new-privileges`. The only writable paths
  are the volume and a small tmpfs.
- **Secrets are mounted files**, not environment variables.

Verify all of that after it starts:

```bash
docker exec wordle-api id                     # uid=10001, not root
docker exec wordle-api touch /app/x           # must fail: read-only
docker exec wordle-api touch /data/x          # must succeed: the volume
docker exec wordle-api ls -l /run/secrets/    # the two secret files
docker inspect wordle-api --format '{{json .Config.Env}}' | grep -c PASSWORD   # 0
```

### Ports, and whether you need the production override

The base file publishes ports: **8080** for the page, **8000** for the API.
Both must be reachable — the browser loads the page from 8080 and then calls
8000 itself, with no proxy in between.

Check what Docker bound, from on the box:

```bash
docker compose ps        # want [::]:8080->8080 in the Ports column, not just 0.0.0.0
curl -6 http://[::1]:8080/            # loopback, so the firewall is not involved yet
```

Testing from outside needs the firewall open first — that is Step 5. Come back
and run `curl -6 http://[your-ipv6]:8080/` from another machine after it.

If IPv6 is published and you are happy with the firewall situation, you are
done — the base file is enough.

Switch to host networking if either applies:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

- **IPv6 is not being published.** Docker 27 and later turn on `ip6tables` by
  default and publish on both stacks. An older daemon, or one with `ip6tables`
  disabled, writes IPv4 rules only. Host networking answers on both regardless.
- **You rely on `ufw`.** Published Docker ports bypass `ufw` rules, which is a
  well-known way to expose a service you thought was firewalled. Host
  networking has no port publishing, so `ufw` applies normally.

Check your daemon version with `docker version --format "{{.Server.Version}}"`.

---

## Step 5: firewall

```bash
sudo ufw allow 22/tcp                 # keep your SSH in first
sudo ufw allow 8080/tcp               # the page
sudo ufw allow 8000/tcp               # the API — the browser calls it directly
sudo ufw --force enable
sudo ufw status verbose
```

Open the ports the **host** listens on. If you went with Option B and your
provider forwards fixed numbers like 20001 and 20002, allow those instead.

Both ports, not just 8080. The browser fetches the page from 8080 and then
talks to 8000 itself; there is no server-side proxy between them.

`ufw` covers IPv6 too, as long as `IPV6=yes` is set in `/etc/default/ufw`
(it is, by default, on current Debian and Ubuntu).

---

## Step 6: pick how people reach it

This is the decision that matters. Remember you need **two** ports reachable,
not one: the page on 8080 and the API on 8000. Four options, honestly compared.

| | Who can reach it | HTTPS | URL | Domain needed | Third party |
|---|---|---|---|---|---|
| **A. Tailscale Funnel** | everyone | yes, free | stable `ts.net` name | no | Tailscale |
| **B. NAT IPv4 port** | everyone | **no** | `http://ip:20001` | no | none |
| **C. Direct IPv6** | ~half of users | possible | `http://[ipv6]:8080` | no | none |
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
tailnet (Access Controls → add the `funnel` node attribute).

Funnel allows exactly three public ports: 443, 8443 and 10000. You need two, so
put the page on 443 and the API on 8443:

```bash
sudo tailscale funnel --bg --https 443  8080   # the page
sudo tailscale funnel --bg --https 8443 8000   # the API
sudo tailscale funnel status                   # shows both public URLs
```

Now fill in the two URLs, using the hostname Funnel printed:

```ini
# .env
WORDLE_ALLOWED_ORIGINS=https://your-box.your-tailnet.ts.net
WORDLE_API_BASE=https://your-box.your-tailnet.ts.net:8443
```

```bash
docker compose up -d      # rebuilds config.js with the new API base
```

Visit `https://your-box.your-tailnet.ts.net`. Note the page URL has no port
(443 is implied) but the API URL does.

Worth knowing:

- The name is always `*.ts.net`. No custom domain.
- Funnel is still labelled beta.
- Anyone with the link can reach the page. That is what you want here — your
  password is what keeps them out.

### Option B — the NAT IPv4 port (simplest, no HTTPS)

You need **two** ports from your forwarded range. Say the panel forwards public
`20001` to your `8080` and public `20002` to your `8000`:

```ini
# .env
WORDLE_ALLOWED_ORIGINS=http://<shared-ipv4>:20001
WORDLE_API_BASE=http://<shared-ipv4>:20002
```

Then the site is at `http://<shared-ipv4>:20001`.

Nothing to install. Works for every visitor. But the password travels in clear
text, so treat this as a "just me, just testing" option, or pair it with a
password you use nowhere else.

**If your provider cannot choose the internal port.** Some panels forward
`public 20001 → your 20001` with no way to map it to 8080. Then the containers
have to listen on those numbers. Override them rather than editing the base
file:

```yaml
# docker-compose.override.yml  (compose picks this up automatically)
services:
  web:
    ports: !override ["20001:8080"]
  api:
    ports: !override ["20002:8000"]
```

The left number is the host port your provider forwards; the right one stays
8080/8000, because that is what the processes inside the containers bind to.
Open the host-side numbers in `ufw`, not 8080/8000.

If your provider forwards only one port, this option is out — use Tailscale
Funnel instead.

### Option C — direct IPv6, with a real certificate

Your IPv6 address is genuinely yours, all ports included. And since January
2026 Let's Encrypt issues certificates **for IP addresses**, so you can have
real HTTPS with no domain at all.

The catches are real: only about half of visitors have IPv6 at all, IP
certificates last ~6 days so renewal must be automated, and you must use the
`http-01` or `tls-alpn-01` challenge (DNS validation cannot work for an IP).
With Caddy in front:

Here Caddy is worth it, because it can serve both halves on one port and one
certificate — the only option that avoids the two-port dance:

```
# /etc/caddy/Caddyfile
[2001:db8::1] {
    handle /api/* {
        reverse_proxy localhost:8000
    }
    handle {
        reverse_proxy localhost:8080
    }
}
```

Then both URLs are the same origin, and CORS stops mattering:

```ini
# .env
WORDLE_ALLOWED_ORIGINS=https://[2001:db8::1]
WORDLE_API_BASE=https://[2001:db8::1]
```

Useful as a second door alongside Option A. Not enough on its own, because half
your visitors cannot reach IPv6 at all.

### Option D — Cloudflare Quick Tunnel (for a quick test)

```bash
docker run --rm --network host cloudflare/cloudflared:latest \
  tunnel --url http://localhost:8080 --edge-ip-version auto
```

It prints a free `https://something-random.trycloudflare.com` URL. No account,
no domain. But the URL changes every time the tunnel restarts, and Cloudflare
does not intend it for permanent use. Good for showing someone the site in the
next ten minutes; not for keeping it up.

Awkward here, because you would need a **second** tunnel for the API and both
random URLs change on every restart, so `.env` goes stale each time. Fine for a
ten-minute demo, painful beyond that. Use Option A if you want it to stay up.

If your VPS ever loses outbound IPv4, add `--edge-ip-version 6`. `auto` picks
for you based on what the OS has, which on your box means IPv4 via NAT.

---

## Step 7: check it works

```bash
# Both services alive
curl -s localhost:8000/healthz                              # {"status":"ok"}
curl -s -o /dev/null -w "%{http_code}\n" localhost:8080/    # 200

# The gate must hold: this has to be 401, not 201
curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:8000/api/games

# The API must serve no pages: 404
curl -s -o /dev/null -w "%{http_code}\n" localhost:8000/

# A real login, end to end
curl -s -X POST localhost:8000/api/login \
  -H 'Content-Type: application/json' -d '{"password":"YOUR-PASSWORD"}'
```

Then check the frontend picked up the right API base:

```bash
curl -s localhost:8080/config.js     # must show your public API URL
```

Finally open the site on your phone, on mobile data rather than your own Wi-Fi.
That is the test that catches "works for me only" — especially with Option C.
If the page loads but login does nothing, open the browser console: a CORS
error means `WORDLE_ALLOWED_ORIGINS` does not match where the page came from.

---

## Running it day to day

```bash
docker compose logs -f --tail=100     # watch logs
docker compose restart                # restart
docker compose down                   # stop, keeping the volume
docker stats --no-stream              # what it is using

# Update after pushing changes
cd /opt/wordle && git pull && docker compose up -d --build

# Change the password. Everyone is logged out.
printf '%s' 'new-password' > secrets/wordle_password && docker compose up -d
```

**Back up** `secrets/`, `.env`, and the volume:

```bash
docker run --rm -v wordle-data:/data -v "$PWD":/backup alpine \
  tar czf /backup/wordle-data.tar.gz -C /data .
```

**Restore:**

```bash
docker run --rm -v wordle-data:/data -v "$PWD":/backup alpine \
  tar xzf /backup/wordle-data.tar.gz -C /data
```

The volume holds games in progress. Losing it is not a disaster — players get a
fresh board — but there is no reason to.

### Developing against it

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml watch
```

`watch` syncs edits into the running containers, so a change to a `.py` or
`.js` file takes effect without a rebuild, and a change to `pyproject.toml`
triggers one. The override also publishes ports instead of using host
networking, which is what makes this work on a Mac or Windows machine.

---

## Things that will bite you

**Restarting ends games in progress.** Games are held in the app's memory. A
restart wipes them and players get "that game expired" and a fresh board. Fine
for a word game; know that it is the behaviour.

**The two URLs in `.env` are browser URLs, not container URLs.** This is the
single most common way to break the split setup. `WORDLE_API_BASE` must be
reachable from a visitor's browser; `localhost` works only when the visitor is
on the VPS itself. Change either URL and you must run `docker compose up -d`
again, because `config.js` is regenerated at container start.

**Run exactly one worker.** The compose file sets `--workers 1`. Do not raise
it. A second worker is a separate process with its own memory, so it cannot see
games the first one created, and players would get random 404s. If you ever need
more than one, games have to move to Redis first — the code has a `GameStore`
protocol for exactly that.

**Mixed HTTP and HTTPS will be blocked.** If the page is served over HTTPS and
`WORDLE_API_BASE` is `http://`, browsers block the request as mixed content and
the console says so. Both must be the same scheme.

**Docker's published ports ignore `ufw`.** Not an issue with the compose file as
written, because it uses host networking. It becomes an issue the moment
someone switches it to `-p`.

**The login throttle is per process.** Ten wrong passwords locks that IP out for
five minutes. It is a speed bump, not a rate limiter. If the site is on the open
internet and you care, put a real limit in front of it — Cloudflare or Caddy.

**Hermes Agent and Wordle both want to be up.** Give Wordle the 512 MB limit the
compose file already sets, so a runaway container cannot starve Hermes.

---

## Appendix: systemd, no Docker

Only if you want the last 50 MB back.

You need two units: the API, and something to serve the frontend's files.

```bash
sudo apt update && sudo apt install -y python3-venv git nginx
sudo mkdir -p /opt/wordle && sudo chown $USER /opt/wordle
git clone <your-github-url> /opt/wordle
cd /opt/wordle/backend
python3 -m venv .venv
.venv/bin/pip install poetry
.venv/bin/poetry install --only main
```

**The API:**

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
Environment=WORDLE_DATA_DIR=/var/lib/wordle
ExecStart=/opt/wordle/backend/.venv/bin/uvicorn wordle.app:create_app \
  --factory --host :: --port 8000 --workers 1 \
  --proxy-headers --forwarded-allow-ips '*'
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
StateDirectory=wordle
ReadWritePaths=/var/lib/wordle

[Install]
WantedBy=multi-user.target
```

Without Docker there are no mounted secrets, so put the password and key in
`/opt/wordle/.env` and `chmod 600` it.

```bash
sudo useradd --system --no-create-home wordle
sudo systemctl daemon-reload
sudo systemctl enable --now wordle
sudo systemctl status wordle --no-pager
```

**The frontend.** No systemd unit needed — point nginx at the directory. Write
`config.js` by hand, since there is no container start hook to do it:

```bash
cat > /opt/wordle/frontend/config.js <<'JS'
window.WORDLE_CONFIG = { apiBase: 'http://[your-ipv6]:8000' };
JS
```

```nginx
# /etc/nginx/sites-available/wordle
server {
    listen 8080;
    listen [::]:8080;
    root /opt/wordle/frontend;
    index index.html;
    location / { try_files $uri $uri/ =404; }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/wordle /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

Remember to re-run the `config.js` command after every `git pull`, since the
pull will overwrite it.

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
