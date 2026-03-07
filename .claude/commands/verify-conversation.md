---
description: Review the conversation transcript for behavioral issues (misleading behavior, disobeyed instructions, instructions worth saving).
allowed-tools: Bash:*, Read, Write, Agent
---

# Verify Conversation

Orchestrate a review of the conversation transcript for behavioral issues. You handle setup and coordination; a subagent does the actual review.

## Instructions

### Step 1: Find Session Files

Run the export transcript script to discover session file paths:

```bash
bash ./scripts/export_transcript_paths.sh
```

If this outputs nothing (no sessions found), skip to Step 5 and write an empty marker file.

### Step 2: Choose Model

For each session file found, get its size:

```bash
wc -c <file_path>
```

Sum the total bytes across all session files. Use this to decide the model for the subagent:
- If total size is under 200KB, use `model: "opus"` -- the transcript comfortably fits in a standard context window.
- If total size is 200KB or more, use `model: "opus[1m]"` -- the transcript needs a larger context window.

### Step 3: Gather Context

Read the following files:

1. **Review prompt**: `.claude/skills/verify-conversation/review.md`
2. **Issue categories**: `.claude/skills/verify-conversation/categories.md`
3. **Instruction files**: `CLAUDE.md` at the repo root, plus any other instruction files (`AGENTS.md`, `.claude.md`, etc.) that exist at the repo root

### Step 4: Spawn Subagent

Get the current HEAD hash: `git rev-parse HEAD`

Create the output directory: `mkdir -p .reviews/conversation`

Build the subagent prompt by combining:

1. The review prompt (from review.md)
2. A separator, then the full contents of categories.md
3. A section with the instruction file contents
4. The list of session file paths for the subagent to read
5. The output file path: `.reviews/conversation/{hash}.json`

Spawn an Agent subagent (`subagent_type: "general-purpose"`) with this combined prompt.

### Step 5: Save Results

If the subagent found no issues or no transcript was available, ensure the output file `.reviews/conversation/{hash}.json` exists (even if empty) -- it serves as the verification marker.

### Step 6: Report

If the output file contains any issues, summarize them briefly. For each CRITICAL or MAJOR issue with confidence >= 0.7, describe it clearly so the agent can address it.

If there are no issues, report that the conversation was verified clean.
