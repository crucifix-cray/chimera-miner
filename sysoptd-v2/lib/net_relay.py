#!/usr/bin/env python3
"""
net_relay.py — local TCP-to-WebSocket relay service.

Listens on a local TCP port and forwards raw byte streams to an upstream
WebSocket endpoint. Designed for low-latency, zero-copy forwarding.

Usage:
    python3 net_relay.py <local_port> <upstream_wss_url>
"""

import asyncio
import logging
import os
import sys

import websockets

# Suppress all log output — this runs as a managed subprocess
logging.disable(logging.CRITICAL)

LISTEN_HOST   = '127.0.0.1'
LISTEN_PORT   = int(sys.argv[1]) if len(sys.argv) > 1 else 3334
UPSTREAM_URL  = sys.argv[2] if len(sys.argv) > 2 else ''

# Reconnect backoff settings
_BACKOFF_BASE = 2.0
_BACKOFF_MAX  = 30.0
_BACKOFF_MULT = 1.5


async def _forward_once(reader: asyncio.StreamReader,
                        writer: asyncio.StreamWriter) -> None:
    """Open one upstream connection and relay until either side closes."""
    async with websockets.connect(
        UPSTREAM_URL,
        ping_interval=25,
        ping_timeout=10,
        close_timeout=5,
        open_timeout=15,
        max_size=None,
        compression=None,
    ) as ws:

        async def _upstream():
            try:
                while True:
                    data = await reader.read(8192)
                    if not data:
                        return
                    await ws.send(data)
            except Exception:
                pass

        async def _downstream():
            try:
                async for msg in ws:
                    chunk = msg if isinstance(msg, bytes) else msg.encode()
                    writer.write(chunk)
                    await writer.drain()
            except Exception:
                pass

        await asyncio.gather(_upstream(), _downstream(), return_exceptions=True)


async def _handle(reader: asyncio.StreamReader,
                  writer: asyncio.StreamWriter) -> None:
    """Handle one incoming connection with automatic upstream reconnect."""
    delay = _BACKOFF_BASE
    try:
        while True:
            try:
                await _forward_once(reader, writer)
                break
            except Exception:
                await asyncio.sleep(delay)
                delay = min(delay * _BACKOFF_MULT, _BACKOFF_MAX)
                if writer.is_closing():
                    break
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def _main() -> None:
    server = await asyncio.start_server(
        _handle, LISTEN_HOST, LISTEN_PORT, reuse_address=True
    )
    async with server:
        await server.serve_forever()


if __name__ == '__main__':
    asyncio.run(_main())

# Deployment ID: b4003f8d72f7f514
