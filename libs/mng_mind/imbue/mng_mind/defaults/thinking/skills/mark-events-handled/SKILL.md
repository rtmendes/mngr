---
name: mark-events-handled
description: Mark event IDs as handled so the system knows they have been processed. Use after finishing a group of events.
---

When finished handling a group of events, append the handled event id(s) to `/tmp/handled_event_ids`, one event ID per line.

The format must be exactly one event ID per line (newline-delimited), for example:

```bash
echo "evt-abc123" >> /tmp/handled_event_ids
echo "evt-def456" >> /tmp/handled_event_ids
```

Or for multiple IDs at once:

```bash
printf '%s\n' "evt-abc123" "evt-def456" >> /tmp/handled_event_ids
```

This file is checked by a stop hook that prevents the agent from stopping until all events in the delivered event files have been marked as handled.
