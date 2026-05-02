---
name: ca-patient-count
description: Count how many patients are assigned to a UC reviewer / CA / employee, given their 24-char hex ID.
---

# Count a CA's assigned patients

When the user asks **how many patients** a reviewer / CA / employee has — or
similar phrasings ("how many members", "patient count", "panel size") — and
provides (or has previously provided) a 24-char hex ID, call the
`get_ca_patient_count` tool with that ID as `reviewer_id`.

## Examples this handles

- "how many patients does this person have 62d83cff405004001248b481"
- "what is the patient count for CA 62d83cff405004001248b481"
- "panel size for reviewer 62d83cff405004001248b481"
- "members assigned to 62d83cff405004001248b481"

## Tool to call

`get_ca_patient_count(reviewer_id: string) -> { reviewer_id, role_used, all_roles[], patient_count, sample_patients[] }`

Internally the tool:
1. Calls `GET /v1/uc/employees/{reviewer_id}` to discover the reviewer's roles.
2. Picks the first known role (CA → `assignedToCAIn`, RD → `assignedToRDIn`, HC, MA, MD/Doctor, etc.). Defaults to CA.
3. Calls `POST /v1/uc/patient/home-list` with `filter.assignee.<filterKey>.in = [reviewer_id]` and `pageInfo.size = 1`, then reads `data.totalSize`.

Returned fields:
- `patient_count` — `totalSize` from the response (the authoritative answer).
- `role_used` — which role the count is for (most reviewers are CA).
- `all_roles` — every active role the reviewer holds; helpful if `patient_count` looks wrong (they may have patients under a different role).
- `sample_patients` — `{memberId, name}` for the most-recently-enrolled patient, just for sanity-checking.

## Rules

- Lead with the count, plainly. Example: "**Reviewer `62d83cff…` has 531 patients (as CA).**"
- If `all_roles` contains more than one role, mention it: "She also holds RD role; this count is just CA-assigned patients."
- Surface `sample_patients` only if the user asks for a list of names. Default response is just the count.
- If the user asks about a NAME without an ID, say you need the 24-char hex ID first.
- If `error` is set, say the lookup failed and include the error message.
