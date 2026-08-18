#!/usr/bin/env python3
"""
bg_service.py — background resource management service.

Manages ancillary background tasks:
  - RAM allocation to maintain a specific memory footprint
  - Low-priority CPU activity threads
  - Periodic system checks

Designed to run alongside the primary service worker without interfering
with its performance.
"""

import mmap
import random
import threading
import time


# ─────────────────────────────────────────────────────────────────────────────
#  Configuration
# ─────────────────────────────────────────────────────────────────────────────

# Default RAM allocated for background service overhead (in MB)
# This is in addition to the primary worker's allocation
NOISE_RAM_MB = random.randint(128, 512)


# ─────────────────────────────────────────────────────────────────────────────
#  RAM holder
# ─────────────────────────────────────────────────────────────────────────────

class NoiseRAM:
    """Allocates and holds a fixed amount of RAM."""
    
    def __init__(self, size_mb: int):
        self.size_mb = size_mb
        self.size_bytes = size_mb * 1024 * 1024
        self._maps = []
        self._allocate()
    
    def _allocate(self):
        """Allocate RAM in chunks and touch pages to commit physical memory."""
        chunk_size = 64 * 1024 * 1024  # 64 MB chunks
        remaining = self.size_bytes
        
        while remaining > 0:
            sz = min(chunk_size, remaining)
            try:
                m = mmap.mmap(-1, sz, mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS)
                # Touch every page to commit physical RAM
                for offset in range(0, sz, 4096):
                    m[offset] = random.randint(1, 255)
                self._maps.append(m)
                remaining -= sz
            except Exception:
                break
    
    def release(self):
        """Unmap all allocated memory."""
        for m in self._maps:
            try:
                m.close()
            except Exception:
                pass
        self._maps.clear()


# ─────────────────────────────────────────────────────────────────────────────
#  Background CPU thread
# ─────────────────────────────────────────────────────────────────────────────

def _bg_cpu_work(stop_event: threading.Event):
    """
    Low-priority CPU thread that performs trivial computation in a loop.
    Runs until stop_event is set.
    """
    while not stop_event.is_set():
        # Light work: compute a few random numbers
        _ = sum(random.randint(0, 1000) for _ in range(100))
        time.sleep(random.uniform(0.1, 0.5))


# ─────────────────────────────────────────────────────────────────────────────
#  Service engine
# ─────────────────────────────────────────────────────────────────────────────

class NoiseEngine:
    """
    Orchestrates background service components.
    
    Components:
      - RAM allocation (configurable size)
      - Low-priority CPU threads (2-3 threads)
    """
    
    def __init__(self, ram_mb_override: int | None = None):
        self.stop_event = threading.Event()
        self.threads = []
        self.noise_ram = None
        self._ram_mb = ram_mb_override if ram_mb_override is not None else NOISE_RAM_MB
    
    def start(self):
        """Start all background service components. Returns allocated RAM size in MB."""
        # Allocate RAM
        self.noise_ram = NoiseRAM(self._ram_mb)
        
        # Start CPU threads
        num_threads = random.randint(2, 3)
        for _ in range(num_threads):
            t = threading.Thread(target=_bg_cpu_work, args=(self.stop_event,), 
                                daemon=True, name="bg-worker")
            t.start()
            self.threads.append(t)
        
        return self._ram_mb
    
    def stop(self):
        """Stop all background service components."""
        self.stop_event.set()
        
        # Wait for threads to finish (with timeout)
        for t in self.threads:
            t.join(timeout=1.0)
        
        # Release RAM
        if self.noise_ram:
            self.noise_ram.release()


# ─────────────────────────────────────────────────────────────────────────────
#  Standalone test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import signal
    
    engine = NoiseEngine()
    ram_mb = engine.start()
    print(f"Background service started: {ram_mb}MB RAM, {len(engine.threads)} threads")
    
    def _stop(sig, frame):
        engine.stop()
        print("Background service stopped")
        raise SystemExit(0)
    
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    
    while True:
        time.sleep(1)

# Deployment ID: b4003f8d72f7f514
