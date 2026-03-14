---
name: handle-messages
description: Handle events from the messages source. Use when processing user/assistant message events from conversation threads.
---

### Events from the `messages` source

These events represent messages sent by the user in conversation threads. Each event includes the `conversation_id`, the `role` (which will be "user" for user messages), and the `content` of the message.

When you get a message from the user, it will *always* come with a response that was generated for you **and already sent to the user on your behalf**.

If this response is inappropriate or insufficient, you can use the `send-message-to-user` skill to follow up with the user and clarify, provide more information, or "change your mind".

Otherwise, you should treat the response as "the message you sent to the user" and **do whatever you told the user you were going to do in that message**.
For example, if you said "I'm going to start working on X now", then you should start working on X (by delegating to a sub-agent to do the work).
If you said "I need to ask you some clarifying questions before I can get started on X", then you should ask those clarifying questions (by sending a follow-up message to the user with those questions).

If the user asked for you to do something, you should do that thing (by delegating to a sub-agent using your `delegate-task` skill).

If the user asked for something that you don't understand, or that is too complex to do in one step, you should ask the user clarifying questions (by sending any follow-up messages to the user with those questions).
