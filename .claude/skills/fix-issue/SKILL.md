---
name: fix-issue
argument-hint: [issue]
description: Fix a GitHub issue given its number or URL. Replicates the bug, finds root cause, and implements a fix.
---

# Fix a GitHub Issue

You are given a GitHub issue to fix: `$1`

## 1. Understand the issue

Fetch the issue details:

```bash
gh issue view $1 --json number,title,body,labels,comments
```

Read it carefully. If the issue is misguided, unclear to the point of being unactionable, or describes something that is already fixed, comment on the issue explaining why (prefix your comment with `[fix-issue]`) and stop.

## 2. Reproduce and investigate (in parallel)

Launch two efforts concurrently:

- **Reproduce**: Write a minimal reproduction (test, script, or manual steps) that demonstrates the bug or missing behavior. If the issue is a feature request rather than a bug, skip reproduction and instead write a failing test that captures the desired behavior.
- **Root-cause search**: Read the relevant code, trace the control flow, and identify where the fix should go.

## 3. Decide on approach

If there is a clear, unambiguous fix, just do it.

If the fix involves a meaningful architectural choice (e.g., where to put new logic, which abstraction to use, changing public interfaces), stop and ask the user before proceeding. Briefly lay out the options and your recommendation.

## 4. Implement the fix

- Fix the root cause.
- Add or update tests to cover the fix.
- Get all tests passing (`uv run pytest` in the relevant project directory).

## 5. Commit the fix

Commit your changes with a message that references the issue number (e.g., "Fix <description> (#<issue_number>)"). A PR will be created automatically by the system.
