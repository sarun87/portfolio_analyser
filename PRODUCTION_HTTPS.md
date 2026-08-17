# Production HTTPS setup

The production session cookie is `Secure`, HttpOnly, and only works over HTTPS. Do not expose the application on a public network with its development HTTP configuration.

## Recommended: reverse proxy with a trusted certificate

1. Build the frontend and install the backend environment as described in the README.
2. Obtain and renew a certificate for a DNS name, such as `portfolio.example.com`, using your hosting platform or an ACME client such as Certbot.
3. Run the application behind a TLS-terminating reverse proxy. Bind Uvicorn only to loopback in this configuration and proxy requests to it.
4. Set the production cookie and origin configuration before starting Uvicorn:

```bash
export PORTFOLIO_ENV=production
export PORTFOLIO_SESSION_COOKIE_SECURE=true
export PORTFOLIO_TRUSTED_ORIGINS=https://portfolio.example.com
.venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Example Nginx virtual host (replace the hostname and certificate paths):

```nginx
server {
    listen 443 ssl;
    server_name portfolio.example.com;

    ssl_certificate /etc/letsencrypt/live/portfolio.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/portfolio.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

Redirect port 80 to HTTPS at the proxy. Do not add an HTTP listener to Uvicorn for public traffic.

## Direct Uvicorn HTTPS

For a trusted certificate already available on the host, the launcher can serve TLS directly and bind to all interfaces:

```bash
export PORTFOLIO_ENV=production
export PORTFOLIO_TRUSTED_ORIGINS=https://portfolio.example.com:8443
export PORTFOLIO_SSL_CERTFILE=/etc/letsencrypt/live/portfolio.example.com/fullchain.pem
export PORTFOLIO_SSL_KEYFILE=/etc/letsencrypt/live/portfolio.example.com/privkey.pem
export PORTFOLIO_HOST=0.0.0.0
export PORTFOLIO_PORT=8443
./run_portfolio_analyser
```

The trusted origin must match the URL users open, including a non-standard port. The script automatically enables `PORTFOLIO_SESSION_COOKIE_SECURE=true` in production.

### Self-signed certificate setup

For a private network where clients can explicitly trust a local certificate, run:

```bash
./setup_self_signed_production_tls
```

It supports macOS, Linux servers, and Ubuntu on ARM/Raspberry Pi. The script installs OpenSSL when needed (Homebrew on macOS; apt, dnf, yum, or pacman on Linux), prompts for both a DNS/URL name and an IPv4 address, and includes both as certificate SANs. It then creates a protected certificate key, production environment file, and `./run_self_signed_production` launcher for direct Uvicorn TLS on `0.0.0.0`.

No Nginx package is installed because this setup intentionally uses Uvicorn's TLS listener directly. Use the reverse-proxy setup above when you need trusted public certificates, port 443, or proxy-level controls.

## Security checks

- Use a certificate issued by a trusted CA in production; self-signed certificates are suitable only for isolated testing.
- Restrict firewall access to the chosen HTTPS port and restrict certificate-key permissions to the service account.
- The application refuses production startup unless secure cookies and HTTPS trusted origins are configured.
- Browser sessions end on browser close, explicit Lock, or backend restart. HTTPS protects the cookie in transit; it does not make an unlocked server safe for untrusted users with network or host access.

## Explicit insecure network mode

For a short-lived, trusted-network test without certificates, the launcher provides an explicit HTTP mode:

```bash
PORTFOLIO_TRUSTED_ORIGINS=http://192.168.1.25:8000 \
  ./run_portfolio_analyser --insecure
```

It binds to `0.0.0.0:8000` by default. Set `PORTFOLIO_TRUSTED_ORIGINS` to the exact URL opened in the browser (including a non-standard port), then override the bind address or port with `PORTFOLIO_HOST` and `PORTFOLIO_PORT` if needed. This mode is rejected when `PORTFOLIO_ENV=production`, disables the `Secure` cookie flag so browser sessions work over HTTP, and must never be used on an untrusted or public network.
