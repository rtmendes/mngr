# mngr_forever_claude

A simple persistent Claude agent plugin for mngr.

Registers the `forever-claude` agent type which runs continuously, communicates via Telegram, and manages its own background services through a bootstrap service manager.

## Usage

```bash
mngr create my-agent forever-claude --project ~/project/my-forever-claude-template \
    --pass-env TELEGRAM_BOT_TOKEN --pass-env TELEGRAM_USER_NAME
```

## Required Environment Variables

- `TELEGRAM_BOT_TOKEN`: Telegram Bot API token
- `TELEGRAM_USER_NAME`: Telegram username to accept messages from
