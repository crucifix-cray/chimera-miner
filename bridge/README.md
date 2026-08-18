# WebSocket Relay Server

TCP-to-WebSocket relay for cloud deployment (Railway, Render, Fly.io).

## Features

- WebSocket Secure (WSS) connections
- Raw TCP byte forwarding
- Cloud platform compatible (Railway PORT injection)
- Lightweight async I/O

## Installation

```bash
pip install -r requirements.txt
python3 relay.py
```

## Environment Variables

```bash
PORT=8080                      # Listen port (auto-injected by Railway)
UPSTREAM_HOST=upstream.svc     # Upstream TCP host
UPSTREAM_PORT=3333             # Upstream TCP port
AUTH_TOKEN=secret123           # Optional auth token
```

## Railway Deployment

```bash
railway link
railway up
```

Railway will auto-inject `PORT` and expose via HTTPS/WSS.

## Docker

```bash
docker build -t relay .
docker run -p 8080:8080 -e UPSTREAM_HOST=upstream.svc relay
```

## License

MIT
