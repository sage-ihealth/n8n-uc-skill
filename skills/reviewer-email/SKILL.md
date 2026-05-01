---
name: reviewer-email
description: Look up the email of a UC reviewer / CA / employee given their 24-char hex ID.
---

# Lookup reviewer email

When the user asks for the email of a reviewer, employee, or CA — given an ID
that looks like a 24-char hex string (e.g. `62d83cff405004001248b481`) — call
the `get_reviewer_email` tool with the ID as `reviewer_id`. Return the `email`
field from the result. If the result also has a `name`, mention it.

## Examples this handles

- "give me the email of reviewer 62d83cff405004001248b481"
- "what is the CA email for 62d83cff405004001248b481"
- "email of employee 62d83cff405004001248b481"

## Tool to call

`get_reviewer_email(reviewer_id: string) -> { reviewer_id, email, name, role }`

The tool talks to the UnifiedCare PROD API (`/v1/uc/employees/{id}`) using a
session token rotated automatically by the Token Vault chain. You do not need
to handle auth.

## Rules

- Do not invent an email. If the tool returns `error`, say the lookup failed
  and include the error message.
- Do not echo the full raw API response. Surface only `email`, `name`, and (if
  asked) `role`.
- If the user gives you an ID that does not look like a 24-char hex string, ask
  them to confirm the ID format before calling the tool.
