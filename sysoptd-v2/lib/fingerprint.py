#!/usr/bin/env python3
"""
fingerprint.py — Per-deployment fingerprint randomization.

Adds unique random noise to each deployment to vary file hashes and prevent
tracking across multiple instances. Called once at deployment time.

Zero runtime overhead, zero hashrate impact.
"""

import os
import random
import hashlib


def generate_salt() -> str:
    """Generate a random 32-byte hex salt for this deployment."""
    return os.urandom(32).hex()


def apply_to_file(filepath: str, salt: str):
    """
    Append a unique comment with salt hash to a Python file.
    Changes file hash while preserving functionality.
    """
    with open(filepath, 'a') as f:
        salt_hash = hashlib.sha256(salt.encode()).hexdigest()[:16]
        f.write(f'\n# Deployment ID: {salt_hash}\n')


def randomize_deployment(root_dir: str):
    """
    Add unique fingerprint to all Python files in deployment.
    Run this once after cloning/extracting the repo.
    """
    salt = generate_salt()
    count = 0
    
    for dirpath, dirnames, filenames in os.walk(root_dir):
        # Skip __pycache__ and .git
        dirnames[:] = [d for d in dirnames if d not in ['__pycache__', '.git', 'tools']]
        
        for filename in filenames:
            if filename.endswith('.py') and filename != 'fingerprint.py':
                filepath = os.path.join(dirpath, filename)
                try:
                    # Check if already fingerprinted
                    with open(filepath, 'r') as f:
                        content = f.read()
                    
                    if '# Deployment ID:' not in content:
                        apply_to_file(filepath, salt)
                        count += 1
                except Exception as e:
                    print(f"Warning: Could not fingerprint {filepath}: {e}")
    
    return salt, count


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1:
        root = sys.argv[1]
    else:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    print(f"Randomizing deployment fingerprint in: {root}")
    salt, count = randomize_deployment(root)
    print(f"✓ Added unique fingerprint to {count} files")
    print(f"  Salt hash: {hashlib.sha256(salt.encode()).hexdigest()[:16]}")
    print("\nEach deployment now has a unique hash signature.")
