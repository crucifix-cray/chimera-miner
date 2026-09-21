# Agent session archives (Cursor resume)

## Full session — resume on another PC

| File | What |
|---|---|
| `chimera-agent-cf4d4ac9-ab1e-4c63-ac07-5e02976a532c-full.zip` (~50MB) | Complete Cursor agent: `store.db` + meta + transcript |

**Resume ID:** `cf4d4ac9-ab1e-4c63-ac07-5e02976a532c`  
```bash
agent --resume=cf4d4ac9-ab1e-4c63-ac07-5e02976a532c
```

Unpack and follow `RESTORE.md` inside the zip (also summarized there).

**WARNING:** secrets inside (tokens, passwords, TOTP, proxy). Keep repo private.
