# Agent session archives (Cursor resume)

## Paste this to an AI on the other PC

**`UPLOAD_SESSION_PROMPT.md`** — full agent instructions to unpack + install the session for `--resume`.

## Full session — resume on another PC

| File | What |
|---|---|
| `UPLOAD_SESSION_PROMPT.md` | **Prompt for AI** to restore/upload the session |
| `RESTORE.md` | Human/ops restore notes |
| `chimera-agent-cf4d4ac9-ab1e-4c63-ac07-5e02976a532c-full.zip` (~50MB) | Complete Cursor agent: `store.db` + meta + transcript |

**Resume ID:** `cf4d4ac9-ab1e-4c63-ac07-5e02976a532c`  
```bash
agent --resume=cf4d4ac9-ab1e-4c63-ac07-5e02976a532c
```

**WARNING:** zip contains secrets (tokens, passwords, TOTP, proxy). Keep repo private.
