#!/usr/bin/env python3
"""
string_obfuscator.py — ROT13 obfuscation layer for embedded strings in binary.

Applies an additional XOR pass with a different key after the primary XOR
encryption to hide recognizable strings from `strings` command.
"""

import itertools

# Secondary obfuscation key (different from loader XOR key)
_OBFUSCATE_KEY = b'\xde\xad\xbe\xef\xca\xfe\xba\xbe\x13\x37\x42\x69'

def obfuscate(data: bytes) -> bytes:
    """Apply secondary XOR layer."""
    return bytes(a ^ b for a, b in zip(data, itertools.cycle(_OBFUSCATE_KEY)))

def deobfuscate(data: bytes) -> bytes:
    """Remove secondary XOR layer (same as obfuscate for XOR)."""
    return obfuscate(data)


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 3:
        print("Usage: python3 string_obfuscator.py <input_file> <output_file>")
        sys.exit(1)
    
    with open(sys.argv[1], 'rb') as f:
        data = f.read()
    
    obfuscated = obfuscate(data)
    
    with open(sys.argv[2], 'wb') as f:
        f.write(obfuscated)
    
    print(f"Obfuscated {len(data)} bytes: {sys.argv[1]} → {sys.argv[2]}")

# Deployment ID: b4003f8d72f7f514
