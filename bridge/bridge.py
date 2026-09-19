#!/usr/bin/env python3
"""
WebSocket ↔ Stratum bridge for Railway.
Railway only exposes HTTPS/WSS, so this accepts WSS from the local shim
and relays raw Stratum TCP bytes to the pool.

Wallet injection: the bridge rewrites the stratum login message so the
miner only needs to send any worker ID — the real wallet is injected
server-side from the WALLET env var. The miner never needs to know it.
"""

import asyncio
import logging
import os
import json
import websockets

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(message)s')
log = logging.getLogger(__name__)

# Railway injects PORT; pool is configurable via env vars
LISTEN_PORT  = int(os.environ.get('PORT', 8080))
POOL_HOST    = os.environ.get('POOL_HOST', 'pool.supportxmr.com')
POOL_PORT    = int(os.environ.get('POOL_PORT', 3333))
WALLET       = os.environ.get('WALLET', '')   # injected server-side

stats = {'clients': 0, 'shares': 0, 'accepted': 0}


async def relay(src_read, dst_write, label, track_share=False, track_accept=False):
    """
    Zero-copy byte relay between two streams.
    Only peeks at data for share/accept counters - no parsing, no latency.
    """
    try:
        while True:
            chunk = await src_read(8192)
            if not chunk:
                break
            if track_share and b'"method":"submit"' in chunk:
                stats['shares'] += 1
                log.info(f'[{label}] share #{stats["shares"]}')
            if track_accept and b'"error":null' in chunk and b'"id"' in chunk:
                stats['accepted'] += 1
                log.info(f'[{label}] accepted {stats["accepted"]}/{stats["shares"]}')
            dst_write(chunk)
    except Exception as e:
        log.debug(f'[{label}] relay ended: {e}')


async def handle(ws):
    client_addr = ws.remote_address
    stats['clients'] += 1
    log.info(f'[+] client {client_addr} (active: {stats["clients"]})')

    try:
        pool_reader, pool_writer = await asyncio.open_connection(POOL_HOST, POOL_PORT)
        log.info(f'[→] pool {POOL_HOST}:{POOL_PORT}')
    except Exception as e:
        log.error(f'[!] pool connect failed: {e}')
        stats['clients'] -= 1
        return

    try:
        async def ws_to_pool():
            """WS frames → raw TCP bytes to pool (upstream)
            Intercepts the first 'login' message to inject the server wallet.
            All subsequent messages are forwarded as-is.
            """
            login_done = False
            try:
                async for msg in ws:
                    data = msg if isinstance(msg, bytes) else msg.encode()

                    # Inject wallet on login if WALLET env is set
                    if not login_done and WALLET and b'"login"' in data:
                        try:
                            lines = data.decode().strip().splitlines()
                            for i, line in enumerate(lines):
                                obj = json.loads(line)
                                if obj.get('method') == 'login' and 'params' in obj:
                                    orig_user = obj['params'].get('login', '')
                                    # preserve worker id after dot if any
                                    worker_suffix = orig_user.split('.')[-1] if '.' in orig_user else orig_user
                                    obj['params']['login'] = f"{WALLET}.{worker_suffix}"
                                    log.info(f'[login] injected wallet for worker={worker_suffix}')
                                    lines[i] = json.dumps(obj)
                            data = ('\n'.join(lines) + '\n').encode()
                        except Exception as e:
                            log.debug(f'[login-inject] parse error: {e}')
                        login_done = True

                    if b'"method":"submit"' in data:
                        stats['shares'] += 1
                        log.info(f'[↑] share #{stats["shares"]} from {client_addr[0]}')
                    pool_writer.write(data)
                    await pool_writer.drain()
            except Exception as e:
                log.debug(f'[ws→pool] ended: {e}')
            finally:
                pool_writer.close()

        async def pool_to_ws():
            """Raw TCP bytes from pool → WS frames (downstream)"""
            try:
                while True:
                    chunk = await pool_reader.read(8192)
                    if not chunk:
                        break
                    if b'"error":null' in chunk and b'"id"' in chunk:
                        stats['accepted'] += 1
                        log.info(f'[✓] accepted {stats["accepted"]}/{stats["shares"]}')
                    await ws.send(chunk)
            except Exception as e:
                log.debug(f'[pool→ws] ended: {e}')

        await asyncio.gather(ws_to_pool(), pool_to_ws(), return_exceptions=True)

    finally:
        stats['clients'] -= 1
        log.info(f'[-] client {client_addr} disconnected (active: {stats["clients"]})')
        try:
            pool_writer.close()
        except Exception:
            pass


async def main():
    log.info('=' * 55)
    log.info('WebSocket↔Stratum Bridge')
    log.info(f'Listen : 0.0.0.0:{LISTEN_PORT}')
    log.info(f'Pool   : {POOL_HOST}:{POOL_PORT}')
    log.info(f'Wallet : {"SET" if WALLET else "MISSING"} ({len(WALLET)} chars)')
    log.info('=' * 55)

    async with websockets.serve(
        handle,
        '0.0.0.0',
        LISTEN_PORT,
        ping_interval=30,
        ping_timeout=10,
        max_size=None,       # no frame-size cap
        compression=None,    # no compression = lower latency
    ):
        await asyncio.Future()  # run forever


if __name__ == '__main__':
    asyncio.run(main())
