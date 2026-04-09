---
name: debug-mind-container
description: Debug a mind agent running in a Docker container
---

# Debugging a mind agent in Docker

## Find the agent

```bash
uv run mngr list --format json | python3 -c "
import sys,json; data=json.load(sys.stdin)
for a in data.get('agents',[]):
    print(a['id'], a.get('name',''), a.get('state',''), a.get('host',{}).get('name',''))
"
```

## Run commands inside the container

```bash
uv run mngr exec <agent-id-or-name> "<command>"

# Examples:
uv run mngr exec forever "curl -s http://127.0.0.1:8000/"
uv run mngr exec forever "cat \$MNGR_AGENT_STATE_DIR/events/servers/events.jsonl"
```

## Check tmux windows

```bash
# List all tmux windows:
uv run mngr exec <agent> "tmux list-windows -t mngr-<name>"

# Capture the main Claude pane:
uv run mngr exec <agent> "tmux capture-pane -t mngr-<name>:0 -p -S -20"

# Capture the web server pane (usually window 5, named svc-web):
uv run mngr exec <agent> "tmux capture-pane -t mngr-<name>:5 -p -S -20"
```

## Check server events (how the desktop client discovers backends)

```bash
# What servers has the agent registered?
uv run mngr events <agent> servers --quiet

# Follow in real-time:
uv run mngr events <agent> servers --follow --quiet
```

## Check the SSH tunnel (how the desktop client proxies to the container)

```bash
# Get SSH connection details:
uv run mngr list --format json | python3 -c "
import sys,json; data=json.load(sys.stdin)
for a in data.get('agents',[]):
    if 'forever' in str(a.get('name','')):
        ssh = a.get('host',{}).get('ssh',{})
        print(f'SSH: {ssh.get(\"command\",\"\")}\nPort: {ssh.get(\"port\",\"\")}\nKey: {ssh.get(\"key_path\",\"\")}')
"

# Test SSH tunnel manually:
ssh -i <key_path> -p <port> -o StrictHostKeyChecking=no root@127.0.0.1 "curl -s http://127.0.0.1:8000/"
```

## Common problems

### "Backend connection lost" in the browser
- The SSH tunnel to the container dropped or the web server isn't ready
- Check the `pnpm start` terminal for WARNING messages
- Verify the web server is running: `uv run mngr exec <agent> "curl -s http://127.0.0.1:8000/"`

### "Session file not found" spam in web server logs
- Normal when Claude hasn't had any conversation yet (no session JSONL exists)
- Goes away after the first message is sent

### `mngr events` processes keep dying
- Check for stale processes from previous runs: `ps aux | grep "mngr observe\|mngr events"`
- Kill stale ones: `pkill -f "mngr observe --discovery-only"; pkill -f "mngr events.*--follow"`

### Docker container name conflict
- `docker rm -f mngr-<name>-host` then retry creation

### Web server shows "Frontend not built"
- The template's Dockerfile is missing the Node.js + npm build step for claude-web-chat
- Fix: add `npm ci && npm run build` in `vendor/mngr/apps/claude_web_chat/frontend/` to the Dockerfile

### localhost IPv6 resolution failures
- SSH channels don't do dual-stack fallback
- Backend URLs using `localhost` may resolve to `::1` (IPv6) inside containers
- The desktop client normalizes `localhost` to `127.0.0.1` in `ssh_tunnel.py:parse_url_host_port()`
