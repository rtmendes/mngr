---
name: search-event-history
description: Search past events by source, type, or content. Use when you need to look up historical events that you did not store in memory.
---

# Searching event history

You can search past events by inspecting the raw event log files.

## Event log locations

All events are stored as JSONL files at:
```
$MNG_AGENT_STATE_DIR/events/<source>/events.jsonl
```

## Useful search commands

View recent events from a source:
```bash
tail -50 "$MNG_AGENT_STATE_DIR/events/<source>/events.jsonl"
```

Search for events matching a pattern:
```bash
grep '<pattern>' "$MNG_AGENT_STATE_DIR/events/<source>/events.jsonl"
```

Count events per source:
```bash
wc -l "$MNG_AGENT_STATE_DIR/events/"*/events.jsonl
```
