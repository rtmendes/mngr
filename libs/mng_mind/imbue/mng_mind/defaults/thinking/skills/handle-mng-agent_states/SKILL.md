---
name: handle-mng-agent_states
description: Handle events from the mng/agents source. Use when processing sub-agent state transitions (finished, crashed, blocked, etc).
---

### Events from the `mng/agent_states` source

These events represent state changes for any sub-agents that you have launched via `delegate-task`.
Each event includes the `agent_id`, the new `state` (eg, "finished", "blocked", "crashed"), and any relevant metadata about the transition (eg, error message if it crashed).

If this agent was launched to perform a task, you should generally just use the "verify-task" skill to check whether the task was completed successfully.

If this agent *was* the "task verification" agent, then you should see what it recommended you do next, and do that (eg, provide feedback to the original task agent, ask the user for clarification, take some action to complete the task, restart a crashed task, etc).

If you believe that the user should be notified about this work (according to their notification preferences, see ["Memory" section below](#memory)), then you should proactively send a message to the user about it (using the `send-message-to-user` skill).
