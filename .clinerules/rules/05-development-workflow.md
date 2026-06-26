# 05 - Development Workflow (Compact)

## Standard Flow

1. Understand: goal + affected files + constraints.
2. Analyze: read existing code and find matching patterns.
3. Plan: write short, concrete steps.
4. Implement: minimal change, consistent with patterns.
5. Validate: confirm related logic still works.
6. Test: run key and edge scenarios.
7. Summarize: list changed files and verification result.
8. Update Current Task Record: write the final task state to avoid repeating work.
9. Skip Server Launch: after task completion, do NOT start the development server. Confirm task is done via code review and verification checks only.

## Required Output Format

For technical tasks, use a compact format:

```md
## Requirements

- Goal:
- Affected files:
- Constraints:

## Plan

1. ...

## Changes

- file: summary

## Verification

- checks run:
- result:
```

## Validation Checklist

- Route changes: check auth/role + flash + redirect/render.
- Template changes: ensure Jinja variables match route context.
- Model changes: ensure return types and financial formulas remain correct.
- Schema changes: include migration + dependency updates if needed.

## Current Task Record (Required)

- Record file: `.clinerules/current-task.md`.
- Always update this file after finishing a task.
- Include: task title, status (`done`), files changed, key decisions, constraints handled, and "do-not-repeat" notes.
- If the file does not exist, create it.
- If task scope changes mid-way, update this record immediately.

## Stop And Ask When

- Requirements are ambiguous or changed mid-task.
- A change may break hard constraints in `04-ai-behavior-rules.md`.
- A new dependency is required.
- `balance` or `owner_profit` formulas need changes.
