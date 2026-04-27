# UnifiedCare API — Query Patterns

Common multi-step workflows and how to fulfill natural language requests.

---

## Pattern 1: "Get me data for patient X"

### Step sequence
```
1. GET /v1/uc/patient/{memberId}              → demographics, diagnosis, enrolled programs
2. GET /v1/uc/enrolled-programs/{memberId}    → active programs (RPM, CGM, BHI, etc.)
3. GET /v1/uc/account/get/patient/{memberId}  → assigned care team (RD, CA, MD, etc.)
4. POST /v1/uc/measurement/list               → recent vitals (30 days)
5. GET /v1/uc/medication/{memberId}           → current medications
6. GET /v1/uc/labResults/key-lab/{memberId}   → A1C, eGFR, lipids
7. POST /v1/uc/transcribe/search              → care notes / visit notes
8. GET /v1/uc/medical-alerts/{memberId}       → open alerts
9. GET /v1/uc/post-its/list/{memberId}        → sticky notes
```

### Python (uc_client.py)
```bash
python3 uc_client.py summary <memberId>
# or individual pieces:
python3 uc_client.py patient <memberId>
python3 uc_client.py vitals  <memberId> 30
python3 uc_client.py alerts  <memberId>
```

### Key fields to surface
- `profile.data.firstName + lastName` — patient name
- `profile.data.diagnosisList` — ICD codes / conditions
- `programs.data` — active programs and status
- `profile.data.enrolledAt` — enrollment date
- `measurements.data` — latest readings with timestamps
- `alerts.data` — any open critical alerts

---

## Pattern 2: "Which of my patients need attention first?"

### Step sequence
```
1. GET /v1/uc/auth/me                             → get current userId
2. POST /v1/uc/patient/assign/list                → all patients assigned to userId
3. For each patient (parallelize or loop):
   a. GET /v1/uc/medical-alerts/{memberId}         → critical vitals (weight: +50 pts)
   b. GET /v1/uc/compliance-alert/patient-list/{}  → compliance gaps (+30 pts)
   c. GET /v1/uc/smart-alert-tasks/patient-list/{} → smart tasks (+20 pts)
   d. POST /v1/uc/measurement/list (7 days)        → check if readings exist (+15 if none)
   e. POST /v1/uc/billable-monthly-time/current    → billable time (+10 if <20 min)
4. Sort by score descending → top N are highest priority
```

### Python
```bash
python3 uc_client.py prioritize
```

### Urgency signal hierarchy
| Signal | Weight | Meaning |
|--------|--------|---------|
| Open medical alert | +50 | Critical vital reading (e.g., BP >180/120) |
| Compliance alert | +30 | Missed measurements / engagement |
| Smart alert | +20 | AI-detected pattern requiring follow-up |
| No readings 7d | +15 | Patient stopped monitoring |
| <20 min billable | +10 | Billing gap risk |
| Monthly review due | +25 | MTPR overdue |

---

## Pattern 3: "Show me care notes for patient X"

### Step sequence
```
1. POST /v1/uc/transcribe/search  → visit/care notes (most recent first)
2. GET  /v1/uc/call-summary/notes/{memberId}  → AI-generated call summaries
3. GET  /v1/uc/post-its/list/{memberId}       → informal sticky notes
```

### transcribe/search body
```json
{
  "memberId": "<memberId>",
  "startDate": "2025-01-01",
  "endDate": "2026-12-31",
  "pagination": { "page": 1, "count": 20 }
}
```

### Key response fields
```json
{
  "data": [{
    "type": "VISIT_NOTE | CARE_NOTE | PHONE_CALL",
    "content": "...",
    "createdAt": "2026-02-20T10:00:00Z",
    "authorName": "Dr. Smith",
    "visitType": "RPM | IN_PERSON | TELEHEALTH"
  }]
}
```

---

## Pattern 4: "What vitals has patient X logged recently?"

### Step sequence
```
1. POST /v1/uc/measurement/list   → all measurement types, last 30 days
2. POST /v1/uc/cgm/rolling-stats  → CGM summary (if CGM-enrolled)
3. POST /v1/uc/symptom-logs/list  → symptom reports
```

### measurement/list body
```json
{
  "memberId": "<memberId>",
  "startDate": "2026-01-28",
  "endDate": "2026-02-28",
  "pagination": { "page": 1, "count": 100 }
}
```

### Parsing measurement types
Each measurement has a `type` field:
- `BG` → blood glucose (unit: mg/dL)
- `BP` → blood pressure (systolic/diastolic + pulse)
- `SpO2` → oxygen saturation (%)
- `WT` → weight (kg or lbs)
- `TMP` → temperature (°C or °F)
- `HS` → heart rate (bpm)

---

## Pattern 5: "Check patients assigned to me and their outstanding items"

### Step sequence
```
1. GET  /v1/uc/auth/me                             → userId
2. POST /v1/uc/patient-care/my-list               → home page patient care summary
3. POST /v1/uc/task-assignment/search-grouped      → open tasks for me
4. GET  /v1/uc/billable-time-review/todo/count     → items needing billing review
```

### patient-care/my-list body
```json
{ "pagination": { "page": 1, "count": 50 } }
```

### patient-care response structure
Each patient entry includes:
```json
{
  "memberId": "...",
  "firstName": "...", "lastName": "...",
  "outstandingItems": {
    "VISITS": 2,
    "FOOD_LOG": 1,
    "MANUAL_MONTHLY_REVIEW": 1,
    "ALERTS": 0
  },
  "lastMeasurementDate": "2026-02-25T08:00:00Z",
  "billableTime": 1200
}
```

---

## Pattern 6: "How is patient X's blood pressure trending?"

```
1. POST /v1/uc/measurement/list   → BP readings, last 90 days
2. POST /v1/uc/medical-alerts/search-alerts (type=BP)  → BP-related alerts
```

Filter measurements client-side: `data.filter(m => m.type === 'BP')`

Compute trend: compare average of first half vs second half of date range.

---

## Pattern 7: "Create / update a care note for patient X"

```
POST /v1/uc/provider-note/create
```

Body:
```json
{
  "memberId": "<memberId>",
  "content": "Patient reported improved BP readings...",
  "type": "CARE_NOTE",
  "visitId": "<optional visitId>"
}
```

---

## Pattern 8: "Resolve an alert for patient X"

```
POST /v1/uc/medical-alerts/resolve
```

Body:
```json
{
  "alertIds": ["<alertId>"],
  "comment": "Reviewed with patient — readings normalized."
}
```

---

## Error Handling Patterns

```python
try:
    result = GET(f"medical-alerts/{member_id}", token)
except RuntimeError as e:
    if "401" in str(e):
        token = get_token()  # re-extract fresh token
        result = GET(f"medical-alerts/{member_id}", token)
    elif "404" in str(e):
        result = {"data": [], "message": "Not found"}
    else:
        raise
```

---

## Pagination Pattern

All list endpoints accept:
```json
{ "pagination": { "page": 1, "count": 50 } }
```

To fetch all pages:
```python
def fetch_all(path, body, token):
    results = []
    page = 1
    while True:
        body["pagination"] = {"page": page, "count": 50}
        resp = POST(path, body, token)
        items = resp.get("data", {})
        if isinstance(items, list): batch = items
        else: batch = items.get("patients") or items.get("data") or []
        results.extend(batch)
        total = items.get("total", 0) if isinstance(items, dict) else 0
        if len(results) >= total or not batch: break
        page += 1
    return results
```
