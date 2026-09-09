#!/usr/bin/env python3
"""
WebSocket ↔ TCP relay for Railway/cloud deployment.
Accepts WSS connections and forwards raw TCP byte streams to upstream service.
"""

import asyncio
import logging
import os
import json
import socket
import websockets

try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    _UVLOOP = True
except Exception:
    _UVLOOP = False

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(message)s')
log = logging.getLogger(__name__)

# Railway/cloud platform injects PORT
LISTEN_PORT    = int(os.environ.get('PORT', 8080))
UPSTREAM_HOST  = os.environ.get('UPSTREAM_HOST', 'upstream.example.com')
UPSTREAM_PORT  = int(os.environ.get('UPSTREAM_PORT', 3333))
AUTH_TOKEN     = os.environ.get('AUTH_TOKEN', '')
CHUNK          = int(os.environ.get('RELAY_CHUNK', '65536'))

stats = {'clients': 0, 'messages': 0}


def _tune_sock(sock):
    """TCP_NODELAY + keepalive — kills Nagle 30x slow on Linux asyncio."""
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except Exception:
        pass
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    except Exception:
        pass
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
    except Exception:
        pass


async def relay(src_read, dst_write, label):
    """Zero-copy byte relay between two streams."""
    try:
        while True:
            chunk = await src_read(CHUNK)
            if not chunk:
                break
            dst_write(chunk)
    except Exception as e:
        log.debug(f'[{label}] relay ended: {e}')


async def handle(ws):
    client_addr = ws.remote_address
    stats['clients'] += 1
    log.info(f'[+] client {client_addr} (active: {stats["clients"]})')

    # tune WS socket — TCP_NODELAY kills Nagle latency spikes
    try:
        _sock = ws.transport.get_extra_info('socket')
        if _sock is not None:
            _tune_sock(_sock)
    except Exception:
        pass

    try:
        upstream_reader, upstream_writer = await asyncio.open_connection(UPSTREAM_HOST, UPSTREAM_PORT)
        try:
            _usock = upstream_writer.get_extra_info('socket')
            if _usock is not None:
                _tune_sock(_usock)
        except Exception:
            pass
        log.info(f'[→] upstream {UPSTREAM_HOST}:{UPSTREAM_PORT}')
    except Exception as e:
        log.error(f'[!] upstream connect failed: {e}')
        stats['clients'] -= 1
        return

    try:
        async def ws_to_upstream():
            """WS frames → raw TCP bytes to upstream (binary fast, no utf-8)."""
            try:
                async for msg in ws:
                    data = msg if isinstance(msg, (bytes, bytearray, memoryview)) else msg.encode()
                    stats['messages'] += 1
                    upstream_writer.write(data)
                    await upstream_writer.drain()
            except Exception as e:
                log.debug(f'[ws→upstream] ended: {e}')
            finally:
                try:
                    upstream_writer.close()
                except Exception:
                    pass

        async def upstream_to_ws():
            """Raw TCP bytes from upstream → WS binary frames (64k)."""
            try:
                while True:
                    chunk = await upstream_reader.read(CHUNK)
                    if not chunk:
                        break
                    await ws.send(chunk)
            except Exception as e:
                log.debug(f'[upstream→ws] ended: {e}')

        await asyncio.gather(ws_to_upstream(), upstream_to_ws(), return_exceptions=True)
    finally:
        stats['clients'] -= 1
        log.info(f'[-] client {client_addr} (active: {stats["clients"]})')
        try:
            upstream_writer.close()
            await upstream_writer.wait_closed()
        except Exception:
            pass


async def main():
    log.info(f'Starting fast relay on port {LISTEN_PORT} (uvloop={_UVLOOP} chunk={CHUNK})')
    log.info(f'Upstream: {UPSTREAM_HOST}:{UPSTREAM_PORT}')

    async with websockets.serve(
        handle, '0.0.0.0', LISTEN_PORT,
        ping_interval=20, ping_timeout=20,
        max_size=None, compression=None,
    ):
        await asyncio.Future()  # run forever


if __name__ == '__main__':
    asyncio.run(main())
