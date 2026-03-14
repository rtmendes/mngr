---
name: handle-events
description: Generic event handler for sources without a dedicated handler. Use as the fallback when no source-specific skill exists.
---

# Handling events (generic)

This is the default handler for events from sources that do not have a dedicated handler skill.

When you receive events from a source without a specific `handle-<source>` skill, use this generic handler:

1. Read the events and understand what happened.
2. Decide what action, if any, is needed in response.
3. If action is needed, delegate it using the `delegate-task` skill.
4. If the user should be notified, use the `send-message-to-user` skill.
5. Mark the events as handled using the `mark-events-handled` skill.
