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

`get_ca_patient_count(reviewer_id: string) -> { reviewer_id, patient_count, total_reported_by_api, sample_patients[] }`

The tool calls `POST /v1/uc/patient/assign/list` with `assignees: [reviewer_id]`
and a page count of 500. It returns:
- `patient_count` — number of patients returned in the page (the answer to most questions).
- `total_reported_by_api` — server-reported total if present (may be null on some endpoints).
- `note` — non-null warning if the page limit was hit, meaning the true count may be higher.
- `sample_patients` — first 5 patients with `memberId` + `name`, useful for sanity-checking that the IDs map to real people.

## Rules

- Lead with the count, plainly. Example: "**Reviewer `62d83cff…` has 47 patients.**"
- If `note` is non-null (page limit hit), say so explicitly.
- Surface `total_reported_by_api` only if it differs from `patient_count` — otherwise it's redundant.
- Do not list every patient by default. Only mention names if the user asked for a list, in which case use `sample_patients` and note that it's a sample.
- If the user asks about a NAME without an ID, say you need the 24-char hex ID first.
