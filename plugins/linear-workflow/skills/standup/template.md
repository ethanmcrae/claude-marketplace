# Standup Template

Format the output exactly like this. Omit a section entirely if it has no tickets.

---

## Recently Completed (last 7 days)
- **ETH-XX** Title

## In Progress
- **ETH-XX** Title

## Up Next
- **ETH-XX** Title *(Est: M)*

---

Rules:
- "Recently Completed" shows only tickets moved to Done within the last 7 days
- "In Progress" lists current work; flag anything **stale** (in progress but not updated in 3+ days) with a warning like: `-- stale, last updated 5 days ago`
- "Up Next" shows Todo tickets sorted by priority (urgent first), then estimate (largest first); include the estimate label
- Use the estimate labels (XS=1, S=2, M=3, L=5, XL=8), not raw numbers
- If all sections are empty, say "Nothing on the board."
