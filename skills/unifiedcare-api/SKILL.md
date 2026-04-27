---
name: unifiedcare-api
description: Interact with the UnifiedCare DEV or PROD portal backend API. Use when asked about patient data, vitals, care notes, alerts, task lists, or "who should I see first". Handles auth automatically, selects correct endpoints, and digests API responses into readable summaries.
---

# UnifiedCare API Skill

## Overview

You have access to the UnifiedCare care management platform's full API (526 endpoints).
The Python client at `scripts/uc_client.py` handles auth, HTTP, and response parsing.
See `references/endpoints.md` for the full catalog and `references/query-patterns.md` for multi-step workflows.

**Base URLs:**
| Environment | Base URL | Portal |
|-------------|----------|--------|
| **DEV** | `https://dev-uc.ihealth-eng.com/v1/uc` | `https://ucfe-dev.ihealth-eng.com` |
| **PROD** | `https://uc-prod.ihealth-eng.com/v1/uc` | `https://portal.ihealthunifiedcare.com` |

**Auth header:** `x-session-token: <JWT>` — auto-extracted from the running Chrome browser.  
**Always use the Python client** (`uc_client.py`) rather than raw curl — it handles token extraction, error retries, and pagination.

**Switching to prod:**
```bash
export UC_BASE_URL="https://uc-prod.ihealth-eng.com/v1/uc"
export UC_SESSION_TOKEN="<prod-jwt>"   # use /gen-jwt prod
python3 scripts/uc_client.py summary <memberId>
```

---

## Quick API Verification (2-step check)

Before doing real work, verify token + environment with these 2 calls:

```bash
TOKEN="<your-jwt>"
BASE="https://uc-prod.ihealth-eng.com/v1/uc"   # or dev-uc.ihealth-eng.com

# 1. Token health check — returns your user profile
curl -s "$BASE/employees/me" -H "x-session-token: $TOKEN" | python3 -m json.tool | grep -E '"email"|"firstName"|"lastName"'

# 2. Patient lookup — confirms patient exists and is accessible
curl -s "$BASE/patient/<memberId>" -H "x-session-token: $TOKEN" | python3 -c "
import json,sys; d=json.load(sys.stdin).get('data') or {}
p=d.get('profile',{}) or {}
print(p.get('firstName',''), p.get('lastName',''), '|', d.get('id','NOT FOUND'))
"
```

---

## Quick Decision Map

| User asks about… | Workflow to use | Script command |
|---|---|---|
| A specific patient's full data | Pattern 1 in query-patterns.md | `uc_client.py summary <memberId>` |
| Which patients need attention / prioritization | Pattern 2 | `uc_client.py prioritize` |
| Care notes / visit notes for a patient | Pattern 3 | `uc_client.py care-notes <memberId>` |
| Vitals / readings / blood pressure trend | Pattern 4 | `uc_client.py vitals <memberId> [days]` |
| My patients list / outstanding items | Pattern 5 | `uc_client.py my-patients` |
| Alerts for a patient | Pattern 9 | `uc_client.py alerts <memberId>` |
| Unread patient messages / chat inbox | CHS endpoints (see below) | curl direct (not uc_client.py) |
| A raw API call | Direct call | `uc_client.py get <path>` or `post <path> <json>` |

---

## How to Run

```bash
cd /home/ihealth/.openclaw/workspace/skills/unifiedcare-api
python3 scripts/uc_client.py <command> [args]
```

**Auth is automatic** — keep the DEV portal open in Chrome. The script intercepts a lightweight
request from the browser to capture the live session token. No manual copy-paste needed.

Override token manually:
```bash
export UC_SESSION_TOKEN="eyJ0eXAi..."
python3 scripts/uc_client.py my-patients
```

---

## Step-by-Step: Handling User Requests

### 1. "Get patient data for [name or ID]"
```bash
# If you have memberId:
python3 scripts/uc_client.py summary <memberId>

# If you only have a name, search first:
python3 scripts/uc_client.py post patient/search-list '{"searchKey":"<name>","pagination":{"page":1,"count":10}}'
# → get memberId from results, then run summary
```

Surface to user:
- Name, DOB, enrolled programs
- Latest vitals with dates (BG, BP, weight, SpO2)
- Open alerts (sorted by severity)
- Last care note snippet + author
- Current medications count
- Recent lab results (A1C is highest priority)

### 2. "Which patients should I see first?"
```bash
python3 scripts/uc_client.py prioritize
```

Output is already sorted by urgency score. Present as ranked list:
```
1. John Doe (score=80)
   ⚠️ Open medical alert — BP 182/120
   📋 Compliance alert — missed 5 BG readings
2. Jane Smith (score=35)
   📉 No readings in 7 days
   ⏱️ Only 12 min billable this month
```

### 3. "Show me care notes for patient X"
```bash
python3 scripts/uc_client.py care-notes <memberId>
```

Surface: note type, date, author, first 200 chars of content. Group by month.

### 4. "What are patient X's recent vitals?"
```bash
python3 scripts/uc_client.py vitals <memberId> 30   # last 30 days
```

Surface: table of type → latest value → date → trend (vs previous week). Flag anything outside normal range.

Normal ranges for flagging:
- BG fasting: 70–130 mg/dL; post-meal: <180 mg/dL
- BP: <120/80 normal; >130/80 elevated; >140/90 Stage 1 HTN; >160/100 Stage 2
- SpO2: ≥95%; <90% critical
- HR: 60–100 bpm

---

## Patient Messages (CHS — Chat History Service)

Patient chat messages use a **separate base path** (`/chs/`) — the `uc_client.py` `/v1/uc/` client does NOT cover these. Use direct curl with the token.

> ⚠️ `POST /v1/uc/message/list` does NOT exist — do not use it.

### Step 1 — Get unread channels (which patients have unread messages)
```bash
TOKEN=$(cd /home/ihealth/.openclaw/workspace/skills/unifiedcare-api && python3 scripts/uc_client.py token)
curl -s -X POST "https://dev-uc.ihealth-eng.com/chs/channels" \
  -H "Content-Type: application/json" \
  -H "x-session-token: $TOKEN" \
  -d '{"fromTimestamp":"0","unread":true}'
```
Response: `{ "Channels": ["new-<memberId>", ...], "NextFromTimestamp": "..." }`

- `Channels` = list of patient IDs with unread messages
- `teamUnread` count in history response = messages the care team hasn't read

### Step 2 — Get message history for a patient
```bash
curl -s -X POST "https://dev-uc.ihealth-eng.com/chs/history" \
  -H "Content-Type: application/json" \
  -H "x-session-token: $TOKEN" \
  -d '{"count":10,"patientIds":["<memberId>"],"origin":"new","ignoreACK":true}'
```
Response: array of patient objects, each with `messages[]`, `teamUnread`, `clientUnread`.

Each message has:
- `payload.type` — `text`, `measurements`, `commentFoodLog`, `fileUpload`
- `payload.text` — message content
- `payload.userRole` — `patient` or `employee`
- `payload.displayName` — sender name
- `tag.read` — whether care team has read it

### Triage Logic
- Filter for `payload.userRole == "patient"` and `tag.read == false` → these need a response
- `type=measurements` + `vitalName=BG/BP` → route to RD 🥗
- `type=commentFoodLog` → route to RD 🥗
- `type=text` (non-clinical questions, device issues) → route to CA 💚

---

## Common memberId values (DEV environment)

| Patient | memberId |
|---------|----------|
| Unicheck (Lucky) Test | `6705020f443bc6531d6b478c` |

To find others: `python3 scripts/uc_client.py my-patients`

---

## Response Digestion Rules

1. **Always extract `data` field** from response envelope `{ code, data, message }`
2. **Pagination**: if `data.total > count`, there are more pages — fetch all if the user asks for "all"
3. **Dates**: convert ISO strings to human-readable (`2026-02-20T10:00:00Z` → `Feb 20, 2026 10:00 AM`)
4. **IDs**: never show raw ObjectIds to users unless they specifically ask
5. **Empty arrays**: say "none found" not "[]"
6. **Errors**:
   - 401 → token expired, re-extract and retry once
   - 404 → resource doesn't exist (say so clearly)
   - 422 → bad request body (show which field is wrong)

---

## Reference Files

| File | Contents |
|------|----------|
| `references/auth.md` | Token extraction methods, headers, error codes |
| `references/endpoints.md` | All 20 endpoint categories with request/response shapes |
| `references/query-patterns.md` | 8 multi-step workflows for common user intents |
| `scripts/uc_client.py` | Python client — auth, HTTP, high-level helpers, CLI |

---

## Security

- **Never log or print** `x-session-token` values in Discord or shared channels
- **Never modify production data** — always confirm with user before any PUT/POST that changes state
- **Dev only**: this skill is configured for `dev-uc.ihealth-eng.com` — do not point at prod without explicit approval
- Redact token from any error messages before posting to Discord
