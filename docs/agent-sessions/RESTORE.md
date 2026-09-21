# Resume this Cursor agent session on another computer

Session ID: `cf4d4ac9-ab1e-4c63-ac07-5e02976a532c`
Title: Railway Miner Launch
Original cwd: `/home/alae`
Workspace chat bucket (original): `8c374be42ec3e05af9c5ac32b17daca5`

## What is in this archive
- `chats/<workspaceHash>/cf4d4ac9-ab1e-4c63-ac07-5e02976a532c/` — full Cursor agent state (`store.db`, meta, history) — **required for resume**
- `agent-transcripts/cf4d4ac9-ab1e-4c63-ac07-5e02976a532c/` — JSONL transcript mirror

## Restore (Linux / macOS)
1. Quit Cursor / agent on the target machine.
2. Unzip:
   ```bash
   cd /tmp
   cat chimera-agent-cf4d4ac9-ab1e-4c63-ac07-5e02976a532c.zip.part* > chimera-agent-cf4d4ac9-ab1e-4c63-ac07-5e02976a532c.zip   # if split
   unzip chimera-agent-cf4d4ac9-ab1e-4c63-ac07-5e02976a532c.zip -d cursor_sess_restore
   ```
3. Find your workspace chat bucket under `~/.cursor/chats/` (open this project once in Cursor so a folder appears), OR reuse the bundled hash:
   ```bash
   WS=$(ls -1d ~/.cursor/chats/*/ 2>/dev/null | head -1 | xargs -I{} basename {})
   # preferred: use the hash Cursor created for THIS project on the new machine
   ```
4. Install chat store (pick the target WS hash for the project on the new PC):
   ```bash
   SRC=/tmp/cursor_sess_restore/chats/8c374be42ec3e05af9c5ac32b17daca5/cf4d4ac9-ab1e-4c63-ac07-5e02976a532c
   DEST=~/.cursor/chats/$WS/cf4d4ac9-ab1e-4c63-ac07-5e02976a532c
   mkdir -p \"$DEST\"
   cp -a \"$SRC/.\" \"$DEST/\"
   ```
5. Install transcript (optional but useful):
   ```bash
   # Cursor project id folder under ~/.cursor/projects/<slug>/agent-transcripts/
   mkdir -p ~/.cursor/projects/<your-project-slug>/agent-transcripts/cf4d4ac9-ab1e-4c63-ac07-5e02976a532c
   cp -a /tmp/cursor_sess_restore/agent-transcripts/cf4d4ac9-ab1e-4c63-ac07-5e02976a532c/. \
     ~/.cursor/projects/<your-project-slug>/agent-transcripts/cf4d4ac9-ab1e-4c63-ac07-5e02976a532c/
   ```
6. Resume:
   ```bash
   agent --resume=cf4d4ac9-ab1e-4c63-ac07-5e02976a532c
   ```
   or from Cursor UI: resume chat `cf4d4ac9-ab1e-4c63-ac07-5e02976a532c`.

## Notes
- Contains secrets (tokens, passwords, TOTP, proxy). Keep private.
- If resume does not list the chat, copy into the workspace hash that matches the opened project (not necessarily `8c374be42ec3e05af9c5ac32b17daca5`).
