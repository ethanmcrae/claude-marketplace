---
name: new-ticket
description: Create a new Linear ticket with standard defaults. Use when the user wants to create a ticket, task, issue, or work item.
argument-hint: "[title]"
model: opus
---

Create a new Linear ticket using the defaults in [linear-defaults.md](../linear-defaults.md).

## Workflow

If the user provided a title via `$ARGUMENTS`, use it. Otherwise ask for one.

Then ask for the remaining fields **in a single AskUserQuestion call** with multiple questions:

1. **Estimate** — show the scale from [template.md](template.md)
2. **Parent ticket** — optional, ask if this is a sub-ticket (default: none)

Only ask for a **description** if the title alone is ambiguous. Skip it for self-explanatory titles.

## Defaults (apply automatically, don't ask)

- Status: "Todo"
- Assignee: "me"
- Team: "Ethan McRae"
- Project: "Claude Tools"
- Labels: ["Agent Network"]

## After Creation

Confirm with:
- Ticket identifier (e.g. ETH-XX)
- Title
- A direct link to the ticket
