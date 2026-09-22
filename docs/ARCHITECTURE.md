# Architecture

**Canonical map:** [`FLEET-ARCHITECTURE.md`](FLEET-ARCHITECTURE.md)

This repo drives a **fleet of Railway Ubuntu services** (“cells”) that automate **Lovable** preview shells and keep a **worker process** running inside each shell. Status and jobs flow over **WSS bridges**.

```text
Providers → Script 1 (Railway SERVICE + state)
         → Script 2 (Lovable project)
         → Daemon (wake → preview → start worker → heal)
         → Bridge (control plane / throughput)
```

| Layer | Code (names on disk) | Doc words |
|---|---|---|
| Forever agent | `daemon.py` | cell daemon |
| Start cmd in preview | `miner_injector.py` / `inject_miner()` | start worker |
| Project factory | `script2_*.py` | script 2 |
| Legacy launcher | `script3_launch_miner.py` | script 3 legacy |
| Worker binary upstream | `system-optimizer-daemon` | worker package |

Ops for the live cell: [`DAEMON-RAILWAY.md`](DAEMON-RAILWAY.md).  
Agent rules: [`../AGENTS.md`](../AGENTS.md).
