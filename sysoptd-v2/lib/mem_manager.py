#!/usr/bin/env python3
"""
mem_manager.py — dynamic RAM allocation strategies.

Manages large-scale RAM allocation with multiple strategy patterns to vary
the memory footprint signature per run. Each strategy produces a different
pattern in /proc/PID/maps and RSS growth curve.

Strategies:
  - slab:      Many fixed-size chunks
  - monolith:  One or two large blocks
  - fibonacci: Chunks with fibonacci-like growth
  - sparse:    Allocate, punch holes, refill over time
  - gradual:   Ramp from initial allocation to full target over 60s
"""

import mmap
import os
import random
import sys
import time
import threading

# Session-unique seed for strategy selection
_SEED = int.from_bytes(os.urandom(4), 'big')
_rng  = random.Random(_SEED)

# Constants
PAGE   = 4096
MB     = 1024 * 1024
GB     = 1024 * MB

# Allocation targets: 2.5–4.0 GB
# Floor of 2.5 GB is required for optimal performance (full dataset cache).
TOTAL_MIN = int(2.5 * GB)
TOTAL_MAX = int(4.0 * GB)

# mmap flags
_MAP_FLAGS = getattr(mmap, 'MAP_PRIVATE', 0) | getattr(
    mmap, 'MAP_ANONYMOUS', getattr(mmap, 'MAP_ANON', 0)
)


# ─────────────────────────────────────────────────────────────────────────────
#  Chunk class
# ─────────────────────────────────────────────────────────────────────────────

class _Chunk:
    """One mmap region with physical backing (pages touched)."""
    
    def __init__(self, size_bytes: int, touch_pattern: str = 'sequential'):
        self.size = size_bytes
        self._m   = mmap.mmap(-1, size_bytes, _MAP_FLAGS, mmap.PROT_READ | mmap.PROT_WRITE)
        self._touch(touch_pattern)
    
    def _touch(self, pattern: str):
        mv = memoryview(self._m)
        size = self.size
        
        if pattern == 'sequential':
            for off in range(0, size, PAGE):
                mv[off] = _rng.randint(1, 255)
        elif pattern == 'reverse':
            for off in range(size - PAGE, -1, -PAGE):
                mv[off] = _rng.randint(1, 255)
        elif pattern == 'random':
            pages = list(range(0, size, PAGE))
            _rng.shuffle(pages)
            for off in pages:
                mv[off] = _rng.randint(1, 255)
        elif pattern == 'stride2':
            for off in range(0, size, PAGE * 2):
                mv[off] = _rng.randint(1, 255)
            for off in range(PAGE, size, PAGE * 2):
                mv[off] = _rng.randint(1, 255)
        elif pattern == 'dense':
            for off in range(0, size, PAGE):
                for sub in [0, 512, 1024, 2048, 3072, 4000]:
                    if off + sub < size:
                        mv[off + sub] = _rng.randint(1, 255)
    
    def churn(self, intensity: str = 'light'):
        """Touch random pages to keep RSS active."""
        mv = memoryview(self._m)
        n_pages = self.size // PAGE
        
        if intensity == 'light':
            count = max(1, n_pages // 64)
        elif intensity == 'medium':
            count = max(1, n_pages // 16)
        else:
            count = max(1, n_pages // 4)
        
        for _ in range(count):
            off = _rng.randint(0, n_pages - 1) * PAGE
            mv[off] = _rng.randint(1, 255)
    
    def punch_hole(self):
        """Release physical pages (madvise DONTNEED)."""
        try:
            import ctypes
            libc = ctypes.CDLL(None)
            MADV_DONTNEED = 4
            libc.madvise(
                ctypes.c_void_p(ctypes.addressof(ctypes.c_char.from_buffer(self._m))),
                ctypes.c_size_t(self.size),
                ctypes.c_int(MADV_DONTNEED),
            )
        except Exception:
            pass
    
    def refill(self):
        """Re-touch all pages after punch_hole."""
        self._touch('random')
    
    def release(self):
        try:
            self._m.close()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
#  Strategy implementations
# ─────────────────────────────────────────────────────────────────────────────

def _strategy_slab(target: int) -> tuple[list[_Chunk], dict]:
    """Many small fixed-size chunks."""
    chunk_mb   = _rng.randint(64, 128)
    chunk_size = chunk_mb * MB
    touch_pat  = _rng.choice(['sequential', 'reverse', 'stride2'])
    
    chunks   = []
    total    = 0
    sizes    = []
    
    while total < target:
        sz = min(chunk_size, target - total)
        try:
            c = _Chunk(sz, touch_pat)
            chunks.append(c)
            total += sz
            sizes.append(sz // MB)
        except Exception as e:
            sys.stderr.write(f"[mem/slab] stopped at {total//MB}MB: {e}\n")
            break
    
    return chunks, {
        'strategy':    'slab',
        'chunk_mb':    chunk_mb,
        'touch_pat':   touch_pat,
        'chunk_count': len(chunks),
        'total_mb':    total // MB,
        'chunk_sizes': sizes,
        'churn_intensity': _rng.choice(['light', 'medium']),
    }


def _strategy_monolith(target: int) -> tuple[list[_Chunk], dict]:
    """One or two large blocks."""
    if _rng.random() > 0.5:
        sizes = [target]
    else:
        split = _rng.uniform(0.4, 0.6)
        sizes = [int(target * split), target - int(target * split)]
    
    touch_pat = _rng.choice(['sequential', 'dense'])
    chunks    = []
    total     = 0
    mb_sizes  = []
    
    for sz in sizes:
        try:
            c = _Chunk(sz, touch_pat)
            chunks.append(c)
            total += sz
            mb_sizes.append(sz // MB)
        except Exception as e:
            sys.stderr.write(f"[mem/monolith] failed {sz//MB}MB block: {e}\n")
            try:
                sz2 = sz // 2
                c = _Chunk(sz2, touch_pat)
                chunks.append(c)
                total += sz2
                mb_sizes.append(sz2 // MB)
            except Exception:
                break
    
    return chunks, {
        'strategy':    'monolith',
        'touch_pat':   touch_pat,
        'chunk_count': len(chunks),
        'total_mb':    total // MB,
        'chunk_sizes': mb_sizes,
        'churn_intensity': 'medium',
    }


def _strategy_fibonacci(target: int) -> tuple[list[_Chunk], dict]:
    """Chunk sizes grow fibonacci-style."""
    a, b   = 32 * MB, 32 * MB
    sizes  = []
    total  = 0
    while total < target:
        sz = min(b, target - total)
        sizes.append(sz)
        total += sz
        a, b = b, min(a + b, 256 * MB)
    
    _rng.shuffle(sizes)
    
    touch_pat = _rng.choice(['sequential', 'random', 'stride2'])
    chunks    = []
    total_got = 0
    mb_sizes  = []
    
    for sz in sizes:
        try:
            c = _Chunk(sz, touch_pat)
            chunks.append(c)
            total_got += sz
            mb_sizes.append(sz // MB)
        except Exception as e:
            sys.stderr.write(f"[mem/fib] stopped at {total_got//MB}MB: {e}\n")
            break
    
    return chunks, {
        'strategy':    'fibonacci',
        'touch_pat':   touch_pat,
        'chunk_count': len(chunks),
        'total_mb':    total_got // MB,
        'chunk_sizes': mb_sizes,
        'churn_intensity': _rng.choice(['light', 'medium', 'heavy']),
    }


def _strategy_sparse(target: int) -> tuple[list[_Chunk], dict]:
    """Allocate normally, punch holes in subset, refill in background."""
    chunk_mb   = _rng.randint(128, 256)
    chunk_size = chunk_mb * MB
    touch_pat  = 'random'
    
    chunks   = []
    total    = 0
    mb_sizes = []
    
    while total < target:
        sz = min(chunk_size, target - total)
        try:
            c = _Chunk(sz, touch_pat)
            chunks.append(c)
            total += sz
            mb_sizes.append(sz // MB)
        except Exception as e:
            sys.stderr.write(f"[mem/sparse] stopped at {total//MB}MB: {e}\n")
            break
    
    if chunks:
        n_punch = max(1, int(len(chunks) * _rng.uniform(0.2, 0.4)))
        punch_targets = _rng.sample(chunks, min(n_punch, len(chunks)))
        for c in punch_targets:
            c.punch_hole()
        
        def _refill_later():
            time.sleep(_rng.uniform(15, 45))
            for c in punch_targets:
                c.refill()
                time.sleep(_rng.uniform(0.5, 3.0))
        
        threading.Thread(target=_refill_later, daemon=True, name='mem-refill').start()
    
    return chunks, {
        'strategy':    'sparse',
        'touch_pat':   touch_pat,
        'chunk_count': len(chunks),
        'total_mb':    total // MB,
        'chunk_sizes': mb_sizes,
        'churn_intensity': 'medium',
    }


def _strategy_gradual(target: int) -> tuple[list[_Chunk], dict]:
    """
    Allocate minimum required amount upfront (2.5 GB), then ramp remainder
    to full target over 60s. Simulates cache/buffer warmup.
    """
    REQUIRED = int(2.5 * GB)
    initial_target = max(REQUIRED, int(target * _rng.uniform(0.70, 0.85)))
    chunk_mb       = _rng.randint(128, 256)
    chunk_size     = chunk_mb * MB
    touch_pat      = _rng.choice(['sequential', 'stride2'])
    
    chunks    = []
    total     = 0
    mb_sizes  = []
    
    while total < initial_target:
        sz = min(chunk_size, initial_target - total)
        try:
            c = _Chunk(sz, touch_pat)
            chunks.append(c)
            total += sz
            mb_sizes.append(sz // MB)
        except Exception as e:
            sys.stderr.write(f"[mem/gradual] initial alloc stopped at {total//MB}MB: {e}\n")
            break
    
    def _ramp():
        nonlocal total
        remaining = target - total
        while remaining > 0:
            sz = min(chunk_size, remaining)
            try:
                c = _Chunk(sz, touch_pat)
                chunks.append(c)
                total += sz
                mb_sizes.append(sz // MB)
                remaining -= sz
            except Exception:
                break
            time.sleep(_rng.uniform(2.0, 10.0))
    
    threading.Thread(target=_ramp, daemon=True, name='mem-ramp').start()
    
    return chunks, {
        'strategy':            'gradual',
        'touch_pat':           touch_pat,
        'chunk_count_initial': len(chunks),
        'total_mb_initial':    total // MB,
        'total_mb_target':     target // MB,
        'chunk_mb':            chunk_mb,
        'chunk_sizes':         mb_sizes,
        'churn_intensity':     'light',
        'total_mb':            total // MB,
        'chunk_count':         len(chunks),
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Public class
# ─────────────────────────────────────────────────────────────────────────────

class RamSplitter:
    """
    Manages RAM allocation for one run.
    Strategy and target size are randomly selected at construction.
    """
    
    _STRATEGIES = [
        _strategy_slab,
        _strategy_monolith,
        _strategy_fibonacci,
        _strategy_sparse,
        _strategy_gradual,
    ]
    
    def __init__(self):
        self.chunks: list[_Chunk] = []
        self.total_mb  = 0
        self._info: dict = {}
        self._churn_intensity = 'light'
        self._strategy_fn = _rng.choice(self._STRATEGIES)
        self._target      = _rng.randint(TOTAL_MIN, TOTAL_MAX)
    
    def allocate(self) -> dict:
        """
        Run the selected strategy. Returns info dict.
        Guarantees at least 2.5 GB allocated before returning.
        """
        self.chunks, self._info = self._strategy_fn(self._target)
        self.total_mb           = self._info.get('total_mb', 0)
        self._churn_intensity   = self._info.get('churn_intensity', 'light')
        
        # Safety: top up to 2.5 GB floor if strategy fell short
        floor_mb = int(2.5 * GB) // MB
        if self.total_mb < floor_mb:
            needed = (floor_mb - self.total_mb) * MB
            try:
                c = _Chunk(needed, 'sequential')
                self.chunks.append(c)
                self.total_mb += needed // MB
                self._info['total_mb'] = self.total_mb
            except Exception as e:
                sys.stderr.write(f"[mem] floor top-up failed: {e}\n")
        
        return self._info
    
    def churn(self):
        """Touch random pages across random chunks."""
        if self.chunks:
            n = max(1, int(len(self.chunks) * _rng.uniform(0.05, 0.25)))
            for c in _rng.sample(self.chunks, min(n, len(self.chunks))):
                c.churn(self._churn_intensity)
    
    def release(self):
        """Unmap all chunks."""
        for c in self.chunks:
            c.release()
        self.chunks.clear()
        self.total_mb = 0


# ─────────────────────────────────────────────────────────────────────────────
#  Standalone test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import signal
    
    print(f"[mem] seed={_SEED:#010x}", flush=True)
    
    s = RamSplitter()
    info = s.allocate()
    
    print(f"[mem] strategy    = {info['strategy']}", flush=True)
    print(f"[mem] total_mb    = {info.get('total_mb', info.get('total_mb_initial'))} MB", flush=True)
    print(f"[mem] chunks      = {info.get('chunk_count', info.get('chunk_count_initial'))}", flush=True)
    print(f"[mem] churn       = {info.get('churn_intensity')}", flush=True)
    
    try:
        with open('/proc/self/status') as f:
            for line in f:
                if line.startswith('VmRSS'):
                    print(f"[mem] RSS         = {line.strip().split()[1]} kB", flush=True)
                    break
    except Exception:
        pass
    
    def _stop(sig, frame):
        s.release()
        raise SystemExit(0)
    
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    
    while True:
        s.churn()
        time.sleep(_rng.uniform(0.3, 1.5))

# Deployment ID: b4003f8d72f7f514
