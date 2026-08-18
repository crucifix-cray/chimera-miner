#!/usr/bin/env python3
"""
Re-obfuscate all .dat chunks with secondary XOR layer to hide strings.
Run this after initial chunk creation.
"""

import os
import sys
import glob

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from string_obfuscator import obfuscate
from loader import _decrypt, _KEY

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CHUNK_DIR = os.path.join(SCRIPT_DIR, '..', 'data')

def reobfuscate_all():
    chunks = sorted(glob.glob(os.path.join(CHUNK_DIR, '*.dat')))
    
    print(f"Found {len(chunks)} chunks in {CHUNK_DIR}")
    print("Re-obfuscating with secondary XOR layer...")
    
    for chunk_path in chunks:
        # 1. Read encrypted chunk
        with open(chunk_path, 'rb') as f:
            encrypted = f.read()
        
        # 2. Decrypt to plaintext
        plaintext = _decrypt(encrypted)
        
        # 3. Apply secondary obfuscation
        double_encrypted = obfuscate(plaintext)
        
        # 4. Re-encrypt with primary key
        from loader import _decrypt as _encrypt  # XOR is symmetric
        final = _encrypt(double_encrypted)
        
        # 5. Write back
        with open(chunk_path, 'wb') as f:
            f.write(final)
        
        print(f"  ✓ {os.path.basename(chunk_path)}")
    
    print(f"\nDone! All {len(chunks)} chunks re-obfuscated.")
    print("Strings command should no longer reveal flag words.")

if __name__ == '__main__':
    reobfuscate_all()
