---
name: send-message-to-user
description: Send a message to the user in a conversation thread. Use to reply in an existing conversation, start a new conversation, or proactively reach out.
---

# Sending messages to the user

You communicate with users through conversation threads. Each thread has a unique `conversation_id`. You can send messages in two ways:

## Replying in an existing conversation

When responding to a user message (or following up in a thread you already know about), inject your message into that conversation:

```bash
$MNG_HOST_DIR/commands/chat.sh --new --as-agent "Your message here"
```

This creates a new conversation and injects your message. To find the right conversation to reference, use the `list-conversations` skill or check the `conversation_id` from the event you are responding to.

## Starting a new conversation

When you want to proactively reach out (e.g. to notify the user about completed work, ask a question, or share an update):

```bash
$MNG_HOST_DIR/commands/chat.sh --new --as-agent "Your message here"
```

## Choosing which conversation to use

- If you are responding to a user message, always reference the `conversation_id` from the event. Start a new conversation with `--new --as-agent` and mention which thread you are following up from if relevant.
- If you are proactively notifying the user, start a new conversation unless there is an obvious existing thread where the update belongs.
- If you are unsure, default to starting a new conversation. Short, focused threads are easier for users to follow than long, multi-topic ones.

## Guidelines

- Keep messages concise and actionable.
- When notifying about completed work, include a summary and any relevant URLs (e.g. links to sub-agents or PRs).
- When asking questions, be specific about what you need to know.
- Reference the event or context that triggered the message when it helps the user understand why you are reaching out.
