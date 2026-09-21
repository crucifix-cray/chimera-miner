# UPLOAD SESSION PROMPT

**Paste this entire file into a Cursor / CLI agent on the machine where you want to resume the session.**

---

## Mission

Restore the archived Cursor agent session from this repo so I can run:

```bash
agent --resume=cf4d4ac9-ab1e-4c63-ac07-5e02976a532c
```

Do the work yourself (shell tools). Do not ask me to copy files by hand unless something is impossible without my login.

---

## Session facts (do not invent IDs)

| Field | Value |
|---|---|
| Session ID | `cf4d4ac9-ab1e-4c63-ac07-5e02976a532c` |
| Archive in repo | `docs/agent-sessions/chimera-agent-cf4d4ac9-ab1e-4c63-ac07-5e02976a532c-full.zip` |
| Inside zip: chat store | `chats/8c374be42ec3e05af9c5ac32b17daca5/cf4d4ac9-ab1e-4c63-ac07-5e02976a532c/` (`store.db`, `meta.json`, …) |
| Inside zip: transcript | `agent-transcripts/cf4d4ac9-ab1e-4c63-ac07-5e02976a532c/` |
| Original workspace hash (may differ on this PC) | `8c374be42ec3e05af9c5ac32b17daca5` |

Also read `docs/agent-sessions/RESTORE.md` if present.

---

## Steps (execute in order)

### 1. Locate repo + zip
- Find `chimera-miner` (or this checkout). Confirm the zip exists:
  - `docs/agent-sessions/chimera-agent-cf4d4ac9-ab1e-4c63-ac07-5e02976a532c-full.zip`
- If missing: `git pull` on `master`, or clone `crucifix-cray/chimera-miner`.

### 2. Quit conflicting clients
- Prefer: ask me to quit Cursor UI / other `agent` processes before overwriting chat DB.
- If safe: stop leftover `agent` PIDs that are not yourself (do **not** kill your own process).

### 3. Unzip to a temp dir
```bash
ZIP="<repo>/docs/agent-sessions/chimera-agent-cf4d4ac9-ab1e-4c63-ac07-5e02976a532c-full.zip"
DEST=/tmp/cursor_sess_restore
rm -rf "$DEST"
mkdir -p "$DEST"
unzip -o "$ZIP" -d "$DEST"
ls -la "$DEST/chats"/*/*/store.db
```

### 4. Discover THIS machine’s Cursor workspace chat bucket
Cursor stores chats under `~/.cursor/chats/<workspaceHash>/<sessionId>/`.

1. Ensure the same project is opened once in Cursor (or agent cwd is the project) so a chats bucket exists.
2. Pick the correct hash for **this** project — do **not** blindly reuse `8c374be42ec3e05af9c5ac32b17daca5` unless it already exists here and matches this workspace.

Heuristic:
```bash
ls -la ~/.cursor/chats/
# Prefer the hash folder that is newest / that already has other sessions for this project.
# If only one hash exists, use it.
WS=<chosen-hash>
```

### 5. Install the chat store (required for --resume)
```bash
SESS=cf4d4ac9-ab1e-4c63-ac07-5e02976a532c
SRC=/tmp/cursor_sess_restore/chats/8c374be42ec3e05af9c5ac32b17daca5/$SESS
DEST=~/.cursor/chats/$WS/$SESS
mkdir -p "$DEST"
cp -a "$SRC"/. "$DEST"/
ls -lh "$DEST"/store.db "$DEST"/meta.json
```

### 6. Install agent-transcripts (recommended)
Find the project slug under `~/.cursor/projects/` (often a path-derived name like `home-<user>` or similar). Then:
```bash
SESS=cf4d4ac9-ab1e-4c63-ac07-5e02976a532c
# set PROJ to the matching ~/.cursor/projects/<slug> for this workspace
PROJ=~/.cursor/projects/<slug>
mkdir -p "$PROJ/agent-transcripts/$SESS"
cp -a /tmp/cursor_sess_restore/agent-transcripts/$SESS/. "$PROJ/agent-transcripts/$SESS"/
```

### 7. Verify
```bash
test -f ~/.cursor/chats/$WS/cf4d4ac9-ab1e-4c63-ac07-5e02976a532c/store.db && echo CHAT_OK
# show resume command for the human
echo "agent --resume=cf4d4ac9-ab1e-4c63-ac07-5e02976a532c"
```

### 8. Report back (short)
Tell me:
- Which `$WS` hash you used
- Paths you wrote
- That I should run: `agent --resume=cf4d4ac9-ab1e-4c63-ac07-5e02976a532c`
- Any failure (missing zip, no chats dir, permission)

---

## Rules
- Do **not** commit secrets or re-upload the zip unless I ask.
- Do **not** invent a different session ID.
- If `~/.cursor/chats` is empty: open the project in Cursor once, then retry step 4.
- If resume still fails after copy: try copying into **each** hash under `~/.cursor/chats/` that belongs to this user/project and report which ones you tried.

---

## One-liner for the human after you finish

```bash
agent --resume=cf4d4ac9-ab1e-4c63-ac07-5e02976a532c
```
