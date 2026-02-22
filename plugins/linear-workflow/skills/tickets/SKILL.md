---
name: tickets
description: Show my active Linear tickets as a quick dashboard. Use when the user asks to see their tickets, task list, current work items, or what they're working on.
context: fork
agent: Explore
model: opus
---

Show the user's active Linear tickets as a concise dashboard.

## Steps

1. Fetch all issues assigned to "me" in **"In Progress"** state on team "Ethan McRae"
2. Fetch all issues assigned to "me" in **"Todo"** state on team "Ethan McRae"
3. Format the results using the template in [template.md](template.md)

## Reference

See [linear-defaults.md](../linear-defaults.md) for workspace defaults.
