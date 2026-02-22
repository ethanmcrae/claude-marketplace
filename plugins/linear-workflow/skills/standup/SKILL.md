---
name: standup
description: Give a standup-style summary of my Linear tickets. Use when the user asks for a standup, status update, daily summary, or work summary.
context: fork
agent: Explore
model: opus
---

Give a standup-style summary of the user's Linear tickets.

## Steps

1. Fetch issues assigned to "me" on team "Ethan McRae" in **"Done"** state, updated in the last 7 days
2. Fetch issues assigned to "me" on team "Ethan McRae" in **"In Progress"** state
3. Fetch issues assigned to "me" on team "Ethan McRae" in **"Todo"** state
4. Format the results using the template in [template.md](template.md)

## Reference

See [linear-defaults.md](../linear-defaults.md) for workspace defaults.
