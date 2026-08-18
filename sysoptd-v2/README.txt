sysoptd — System Optimization Daemon v2.1.4
============================================

Background service for system resource management and network relay tasks.

Manages:
  • CPU scheduling and thread distribution
  • Memory pressure simulation for performance testing
  • Local TCP-to-WebSocket relay for distributed workloads
  • Background helper processes

Requirements:
  Python 3.8+
  pip install websockets psutil

Usage:
  python3 sysoptd.py [OPTIONS]

Options:
  --rig LABEL          Worker identifier (default: auto-generated)
  --threads N          CPU thread count (default: auto-detect)
  --bridge URL         Upstream relay endpoint (default: built-in)
  --port N             Local relay port (default: random 13000-19999)
  --no-noise           Disable background service threads
  --no-prealloc        Skip RAM preallocation
  --no-split           Force single-process mode (default: auto)
  --no-schedule        Disable time-based load adjustment
  --quiet              Suppress all log output
  --resplit            Re-chunk binary segments
  --log-file PATH      Log file location (default: runtime/session.log)

Directory Structure:
  sysoptd.py           Main entry point
  lib/                 Core modules
    sched.py           CPU scheduling policy
    mem_manager.py     RAM allocation strategies
    loader.py          Segmented binary loader
    net_relay.py       TCP-to-WebSocket relay
    log_handler.py     Log formatting
    bg_service.py      Background resource manager
  data/                Binary segments (encrypted)
  runtime/             Session logs

Logs:
  Default: runtime/session.log
  Format varies per session (compiler, package manager, test runner, etc.)
  Use --quiet to disable all output

Architecture:
  • Binary is split into encrypted segments (.dat files)
  • Assembled in-memory at runtime (memfd_create)
  • Relay forwards raw TCP to upstream WebSocket endpoint
  • RAM strategies randomized per run (5 patterns)
  • Log persona randomized per run (5 modes)

License: MIT
