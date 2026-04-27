---
name: rd-api
description: >
  RD (Registered Dietitian) skill for iHealth UnifiedCare.
  Covers five focused workflows: patient panel, BG/CGM review, BP review,
  medication highlight, and goal tracking.
  Uses uc_client.py — same server, same auth. No separate client needed.
---

# RD API Skill

## Overview

Five skills for an RD's daily workflow, all running through the existing
`uc_client.py` client. Auth, HTTP, and pagination are handled automatically.

```bash
cd /home/ihealth/.openclaw/workspace/skills/unifiedcare-api
python3 scripts/uc_client.py <rd-command> [args]
```

**Auth:** keep the UC Portal open in Chrome, or set `UC_SESSION_TOKEN`.  
**Server:** default is `dev-uc.ihealth-eng.com`. Override with env var:

```bash
export UC_BASE_URL="https://uc-prod.ihealth-eng.com/v1/uc"
export UC_SESSION_TOKEN="<prod token from portal>"
python3 scripts/uc_client.py rd-bp <memberId> 2026-03
```

> ⚠️ `/gen-jwt` produces a **dev-only token** (signed with the dev secret). It will return 401 on prod.
> You must copy a real session token from the prod portal Network tab (`x-session-token` header).

---

## Prod vs Dev — Critical Differences

The prod backend (`uc-prod.ihealth-eng.com`) has a **different API contract** than dev for
`measurement/list`. Every field name, body structure, and response shape differs.
`uc_client.py` handles both automatically via `measurement_list()`.

### measurement/list — body

| | Dev | Prod |
|---|---|---|
| memberId location | top-level `memberId` | `filter.memberId` |
| Date filter | `startDate` / `endDate` (YYYY-MM-DD) | `filter.dateRange.gte` / `lte` (ISO UTC) |
| Type filter key | `type: ["BP"]` | `filter.typeList: ["BP"]` |
| Extra required fields | — | `filter.needStats: true`, `filter.needDataInVisits: true` |
| Pagination | `pagination: {page, count}` | `pageInfo: {"pagination": false}` |
| **Date filter enforced?** | Yes | **NO — server ignores date range; filter client-side** |

### measurement/list — response shape

| | Dev | Prod |
|---|---|---|
| Records path | `data[]` list | `data.results.content[]` |
| SBP field | `r.systolic` (number) | `r.systolic_blood_pressure.value` (object) |
| DBP field | `r.diastolic` (number) | `r.diastolic_blood_pressure.value` (object) |
| BG field | `r.blood_glucose` (number) | `r.blood_glucose.value` (object) |
| Local date | not present | `r.day` (YYYY-MM-DD, patient's timezone) |
| UTC timestamp | `r.createdAt` | `r.date` (device measurement time, UTC) |
| Patient timezone | not present | `r.timezone` (e.g. `"America/Los_Angeles"`) |

### Origin / Referer headers

| | Dev | Prod |
|---|---|---|
| Origin | `https://ucfe-dev.ihealth-eng.com` | `https://portal.ihealthunifiedcare.com` |

`uc_client.py` auto-selects the correct Origin based on `UC_BASE_URL`.

### care-note/search — response shape

| | Dev | Prod |
|---|---|---|
| Notes path | `data[]` list | `data.content[]` (paginated wrapper) |

---

## Time-of-Day Buckets — Portal-Exact Definition

Source: `ucfe/src/helpers/timezone/timezoneService.ts` → `getTimeOfDay()`

The portal classifies each reading into one of four buckets using the **patient's local time**
(from `r.timezone`), NOT the UTC timestamp directly.

| Bucket | Local Hour Range | Notes |
|--------|-----------------|-------|
| **Overnight** | 0:00 – 3:59 | Late night / very early morning |
| **Morning** | 4:00 – 11:59 | Before noon |
| **Afternoon** | 12:00 – 17:59 | Noon to 6 PM |
| **Evening** | 18:00 – 23:59 | 6 PM to midnight |

**Implementation in `uc_client.py`:**
- Use `r.date` (UTC) + `r.timezone` to compute local hour
- UTC→local offset table for US timezones (avoids pytz dependency):
  - `America/Los_Angeles`: −7 (PDT, Apr–Oct) / −8 (PST, Nov–Mar)
  - Default to −7 if timezone unknown
- `_time_bucket(ts, timezone)` returns the bucket string

**Common mistake:** Using the UTC hour directly gives wrong buckets.
Example: a reading at `2026-04-12T03:26:44Z` (3 AM UTC) is `2026-04-11 20:26 PDT` → **Evening**, not Overnight.

---

## Month-Based Date Ranges

Use `month='YYYY-MM'` argument to get a calendar month instead of a rolling window:

```bash
python3 scripts/uc_client.py rd-bp <memberId> 2026-03   # March 2026
python3 scripts/uc_client.py rd-bp <memberId> 2026-04   # April 2026
python3 scripts/uc_client.py rd-bp <memberId> 30        # last 30 days (default)
```

`month_range('2026-03')` in `uc_client.py` generates Pacific-timezone UTC boundaries:
- `gte = 2026-03-01T08:00:00.000Z` (midnight Pacific PST = UTC−8)
- `lte = 2026-04-01T06:59:59.999Z` (11:59:59 PM Pacific PDT = UTC−7)

Period display is always shown as calendar dates (`2026-03-01 → 2026-03-31`), never UTC timestamps.

---

## Quick Reference

| Skill | Command | What it does |
|-------|---------|--------------|
| My patient panel | `rd-patients [page] [size]` | All enrolled patients assigned to me as RD |
| BG / CGM review | `rd-bg <memberId> [days]` | TIR, TBR, avg, A1c, fasting/post-meal, SOP flag |
| BP review | `rd-bp <memberId> [days]` | Avg, AM/PM split, stage breakdown, trend, goal status |
| Medication highlight | `rd-meds <memberId>` | Meds by category (BG/BP/Lipid), flags, CA tasks |
| Goal tracker | `rd-goals <memberId>` | Prior MTPR goals verbatim + MTPR history |

---

## Skill 1 — My Patient Panel

```bash
python3 scripts/uc_client.py rd-patients
python3 scripts/uc_client.py rd-patients 2 100   # page 2, 100 per page
```

Uses `POST patient/home-list` with `assignedToRDIn` filter — returns only
patients where the current user is the assigned RD.
Standard `my-patients` uses `patient/assign/list` which returns all assignees
regardless of role; `rd-patients` is RD-specific.

**API call inside uc_client.py:**
```json
POST /v1/uc/patient/home-list
{
  "filter": {
    "listType": "ENROLLED",
    "assignee": { "assignedToRDIn": { "in": ["<rdUserId>"] } }
  },
  "pageInfo": { "page": 1, "size": 100, "sort": [{ "property": "patientListInfo.enrollmentDate", "direction": "DESC" }] }
}
```

**Output:**
```
RD patient panel — 775 total enrolled patients
Page 1 | Showing 100 patients

     1.  Plez Ingram                     69dd3822b008c4fcfc2684b5
     2.  Barbara Keller                  69b87ee30214c8a8eed85bb4
     3.  Jean Whitman                    69d3ed81bfe9fb3e31cf674d
   ...
```

**Response fields extracted:**
```
data.totalSize          → total enrolled (e.g. 775)
data.content[].id       → memberId (use this for all other rd-* commands)
data.content[].profile.firstName / lastName
data.content[].profile.birthday
data.content[].profile.doctorId
```

---

## Skill 2 — BG / CGM Review

```bash
python3 scripts/uc_client.py rd-bg <memberId>          # default 30 days
python3 scripts/uc_client.py rd-bg <memberId> 14       # last 14 days
python3 scripts/uc_client.py rd-bg <memberId> 2026-03  # calendar month
```

**API calls inside uc_client.py:**

For CGM patients:
```json
POST /v1/uc/cgm/rolling-stats
{ "memberId": "<memberId>", "startDate": "YYYY-MM-DD", "endDate": "YYYY-MM-DD", "intervalInDay": 30 }
```

For BG device patients — uses `measurement_list()` (see prod/dev differences above):
```json
POST /v1/uc/measurement/list
{
  "filter": {
    "memberId": "<memberId>",
    "dateRange": { "gte": "...", "lte": "..." },
    "typeList": ["BG"],
    "needStats": true,
    "needDataInVisits": true
  },
  "pageInfo": { "pagination": false }
}
```

A1c from labs:
```
GET /v1/uc/labResults/key-lab/<memberId>   → data.A1C.value + data.A1C.date
```

**Prod BG field extraction:**
```python
bg = r.get("blood_glucose")
value = bg.get("value") if isinstance(bg, dict) else bg   # prod vs dev
```

**BG measurement fields (prod):**

| Field | Type | Description |
|-------|------|-------------|
| `mealType` | `BgMealTypeEnum` | BREAKFAST, LUNCH, DINNER, SNACK, BEDTIME, OVERNIGHT |
| `beforeMeal` | `boolean` | true = before meal, false = after meal |
| `bgSeverity` | `BgSeverityEnum` | VERY_LOW, LOW, NORMAL, HIGH, CRITICAL |

**Portal-exact 7 BG summary categories** (source: `BGChartHelper.ts`, `useBGResultToSummaryTable.ts`):

| Display Label | Logic |
|---|---|
| **Fasting** | `mealType=BREAKFAST && beforeMeal=true` OR `mealType=OVERNIGHT` |
| **Before Meal** | `mealType=LUNCH\|DINNER && beforeMeal=true` |
| **After Meal** | `mealType=BREAKFAST\|LUNCH\|DINNER && beforeMeal=false` OR `mealType=BEDTIME` |
| **Bedtime** | `mealType=BEDTIME` (subset of After Meal) |
| **Overnight** | `mealType=OVERNIGHT` (subset of Fasting) |
| **Critical High** | `bgSeverity=CRITICAL` |
| **Critical Low** | `bgSeverity=VERY_LOW` |

> Note: `bgSeverity=HIGH` is "High" but NOT "Critical High". Critical High requires `bgSeverity=CRITICAL`.  
> `blood_glucose.unit` may be `mmol/L` — always convert to mg/dL (× 18.0156) before displaying.

**CGM fields used:**

| Field | Meaning | SOP threshold |
|-------|---------|---------------|
| `activeTime` | CGM wear % (AT) | ≥50% (uncontrolled) / ≥80% (graduation) |
| `timeInRange` | TIR 70–180 mg/dL | ≥50% (uncontrolled) / ≥70% (controlled) |
| `timeBelowRange` | TBR <70 mg/dL | <4% |
| `timeAboveRange` | High >180 mg/dL | minimize |
| `averageGlucose` | Avg mg/dL | — |
| `cv` | Glycemic variability % | <36% |
| `gmi` | Est A1c | <8.0% (uncontrolled goal) |

**SOP auto-classification:**
```
UNCONTROLLED (VC.3.1) if ANY:  A1c ≥ 8.0%  OR  TIR < 50%  OR  TBR > 4%  OR  Wear < 50%
CONTROLLED   (VC.3.2) if ALL criteria met
UNKNOWN      if insufficient data (default to UNCONTROLLED for safety)
```

**Output:**
```
BG / CGM Review — month 2026-03 (2026-03-01 → 2026-03-31)

CGM: No data (not on CGM or no recent sensor)

BG readings: 60 total
  All         : avg=141  min=58   max=289  (n=60)
  Fasting     : avg=156  min=89   max=210  (n=27)
  Pre-meal    : avg=147  min=50   max=236  (n=18)
  Post-meal   : avg=172  min=129  max=270  (n=13)

Time of day:
  Overnight   : avg=—     (no readings)
  Morning     : avg=148  min=89   max=200  (n=30)
  Afternoon   : avg=138  min=58   max=200  (n=18)
  Evening     : avg=135  min=90   max=180  (n=12)

A1c: 6.5% (2025-08-14)
BG meds: Farxiga 10mg, Jardiance 10mg, Novolog 13u TID, Tresiba 28u QHS

SOP: CONTROLLED (VC.3.2)
```

---

## Skill 3 — BP Review

```bash
python3 scripts/uc_client.py rd-bp <memberId>          # default 30 days
python3 scripts/uc_client.py rd-bp <memberId> 90       # last 90 days
python3 scripts/uc_client.py rd-bp <memberId> 2026-03  # calendar month
python3 scripts/uc_client.py rd-bp <memberId> 2026-04  # next month (compare)
```

**API call — uses `measurement_list()` (prod/dev-aware, see differences above)**

**Prod BP field extraction:**
```python
sbp = r.get("systolic_blood_pressure")
sbp_val = sbp.get("value") if isinstance(sbp, dict) else r.get("systolic")
# Same pattern for diastolic_blood_pressure / diastolic
```

**Date field for client-side filtering:** use `r.day` (local YYYY-MM-DD), not `r.date` (UTC).
**Date field for time-of-day bucketing:** use `r.date` (UTC) + `r.timezone` → convert to local hour.

**Stage classification (computed per reading):**

| Stage | Threshold |
|-------|-----------|
| Normal | SBP <130 AND DBP <80 |
| Elevated | SBP 130–139 OR DBP 80–89 |
| Stage 1 | SBP 140–159 OR DBP 90–99 |
| Stage 2 | SBP 160–179 OR DBP 100–119 |
| Critical | SBP ≥180 OR DBP ≥120 |

**Time-of-day split (portal-exact — from `timezoneService.getTimeOfDay`):**

| Bucket | Local hour range |
|--------|-----------------|
| Overnight | 0:00 – 3:59 |
| Morning | 4:00 – 11:59 |
| Afternoon | 12:00 – 17:59 |
| Evening | 18:00 – 23:59 |

> Use `_time_bucket(r.date, r.timezone)` — converts UTC → patient local time before bucketing.
> Never use UTC hour directly (3 AM UTC = 8 PM PDT = Evening, not Overnight).

**Escalation logic:**
```
🔴 Hard  → any Critical reading          → notify MD
🟡 Soft  → Stage 2 ≥ 70% of readings    → flag in MTPR
🟡 Soft  → goal not met (avg ≥130/80)   → review at visit
🟢 OK    → goal met, stable/improving
```

**Trend:** compare avg SBP first half vs second half of period.
`diff > +3` = worsening, `diff < -3` = improving, else stable.

**Output (month mode — used for MTPR prep):**
```
BP Review — month 2026-03 (2026-03-01 → 2026-03-31)

Total readings : 27
Average        : 145/91 mmHg

Time of day:
  Overnight   : —  (no readings)
  Morning     : 146/92 mmHg  (n=13)
  Afternoon   : 145/89 mmHg  (n=6)
  Evening     : 144/90 mmHg  (n=8)

Stage breakdown:
  Stage 1      :  17 readings  (63%)
  Elevated     :   6 readings  (22%)
  Stage 2      :   4 readings  (15%)

Trend          : worsening
Goal met       : ❌ No
BP meds        : losartan 100mg, carvedilol 12.5mg
Escalation     : 🟡 Soft — goal not met
```

**MTPR comparison pattern (run both months):**
```bash
MID="<memberId>"
python3 scripts/uc_client.py rd-bp "$MID" 2026-03   # previous month
python3 scripts/uc_client.py rd-bp "$MID" 2026-04   # current month
```
Compare Overnight/Morning/Afternoon/Evening averages across months to identify patterns
(e.g. "mostly morning readings in March; shifted to evening in April").

---

## Skill 4 — Medication Highlight

```bash
python3 scripts/uc_client.py rd-meds <memberId>
```

**API call inside uc_client.py:**
```
GET /v1/uc/medication/<memberId>   → data[] array of medication objects
```

**Medication object fields:**
```json
{
  "name":      "metformin",
  "dosage":    "500 mg",
  "frequency": "BID",
  "active":    true
}
```

**Category grouping (keyword matching on `name`):**

| Category | Keywords matched |
|----------|-----------------|
| BG meds | metformin, jardiance, farxiga, januvia, ozempic, trulicity, insulin, novolog, humalog, glargine, tresiba, lantus, mounjaro … |
| BP meds | lisinopril, losartan, amlodipine, metoprolol, carvedilol, diltiazem, furosemide, valsartan, sacubitril … |
| Lipid meds | atorvastatin, rosuvastatin, simvastatin, pravastatin, ezetimibe … |
| Other | anything not matched above |

**Auto-generated flags:**
```
⚠️  No medications on portal       → Tasked CA to complete meds list
⚠️  On lipid med, HLD dx missing   → Tasked CA to verify diagnosis
ℹ️  No BG or BP meds on record     → verify with patient at next visit
```

**Output:**
```
Medication Highlight — 6 total medications

BG Meds:
  • Farxiga    10 mg   daily
  • Jardiance  10 mg   daily
  • Novolog    13 u    TID
  • Tresiba    28 u    QHS

BP Meds:
  • Amlodipine         5 mg   daily
  • Sacubitril/Valsartan  49-51 mg  daily

Lipid Meds:
  (none)

Flags:
  ⚠️  No lipid med but HLD not confirmed — Tasked CA to verify diagnosis
```

---

## Skill 5 — Goal Tracker

```bash
python3 scripts/uc_client.py rd-goals <memberId>
```

**API call inside uc_client.py:**
```json
POST /v1/uc/care-note/search
{ "filter": { "memberId": "<memberId>" }, "pageInfo": { "pagination": false } }
```

**MTPR note detection — filter by tag:**
```python
MTPR_TAGS = {"MONTHLY_REVIEW", "MONTHLY_REVIEW_RD_HC"}
# tag field: note["tags"]  →  e.g. ["MONTHLY_REVIEW"]
```

> `care-note/search` returns `data[]` directly — no `.content` wrapper.
> Sort by `createdAt` descending; take the first match as "last MTPR".

**Goal extraction — numbered pattern from note content:**
```python
import re
goals = re.findall(r'(\d+\)\s+.+?)(?=\n\d+\)|$)', content, re.DOTALL)
# Matches: "1) BP monitoring: ...\n2) Hydration: ..."
```

Goals are returned **verbatim from the API** — no summarization or paraphrasing.

**Standard goal format used by RDs:**
```
N) <Category>: <Specific action> over <timeframe>.
   Education: <Clinical rationale>.
   [status marker: goal met / Within progress / goal not met]
```

**Output:**
```
Last MTPR: 2026-03-17  by Jason Peng  (note: 69b987e70214c8a8eed87850)

Goals from last MTPR (verbatim):

  1) BP monitoring: Obtain 4-5 home BP readings/wk, AM or evening based on
     schedule over the next month. Education: Know urgent thresholds
     (≥180/≥120) + symptoms → seek care.

  2) Hydration: Increase to 2-3 bottles sparkling water daily over next month.
     Education: Coffee doesn't count toward fluids and can dehydrate; aim to
     progress toward ~64 fl oz/day if tolerated.

  3) Sodium reduction at lunch: When making sandwiches, choose lower-sodium
     options (e.g., turkey/ham). Education: deli meats can be high in sodium
     and can raise BP.

MTPR history (last 3):
  2026-03-17  Jason Peng            MONTHLY_REVIEW
  2026-01-09  Jason Peng            MONTHLY_REVIEW
  2025-11-22  Nora Zhu              MONTHLY_REVIEW
```

---

## Composing Skills for an MTPR Visit

Run all five before or during a visit to have the full picture.
For MTPR, always use **two calendar months** for BP/BG so you can compare vs prior month.

```bash
MID="69a0c639bb6edce15ab8041d"   # Peter Martinez
PREV="2026-03"   # previous month
CURR="2026-04"   # current month

# On prod:
export UC_BASE_URL="https://uc-prod.ihealth-eng.com/v1/uc"
export UC_SESSION_TOKEN="<token from portal>"

python3 scripts/uc_client.py rd-bp    $MID $PREV
python3 scripts/uc_client.py rd-bp    $MID $CURR
python3 scripts/uc_client.py rd-bg    $MID $PREV
python3 scripts/uc_client.py rd-bg    $MID $CURR
python3 scripts/uc_client.py rd-meds  $MID
python3 scripts/uc_client.py rd-goals $MID
```

Or chain into one summary:
```bash
for CMD in "rd-bp $MID $PREV" "rd-bp $MID $CURR" "rd-bg $MID $PREV" "rd-bg $MID $CURR" "rd-meds $MID" "rd-goals $MID"; do
  echo "\n========== $CMD =========="
  python3 scripts/uc_client.py $CMD
done
```

**What to compare across months:**
- Overnight / Morning / Afternoon / Evening averages — look for time-of-day patterns
- Shift in reading timing (e.g. patient switched from morning to evening monitoring)
- Stage distribution — did % Stage 2 improve or worsen?
- Total reading count — compliance trend

---

## Response Rules

1. **care-note/search** on prod returns `data.content[]` (paginated) — not `data[]` directly
2. **patient/home-list** returns `data.content[]` with `data.totalSize`
3. **measurement/list** on prod returns `data.results.content[]` — not `data[]` directly
4. **Goal content** — always return verbatim; never rephrase or summarize
5. **Missing data** — say `No recent data` / `No MTPR found`; never infer a value
6. **Errors:**
   - `401` → token expired; re-extract and retry once. Note: `/gen-jwt` tokens only work on **dev**, not prod.
   - `404` → patient not found or not assigned to this RD
   - `422` → check memberId is a valid 24-char hex string
   - `500 "filter is required"` → you're hitting prod but sending the dev body format; use `filter.memberId`
   - `500 "filter.memberId is required"` → body has `filter: {}` without memberId inside

## Prod Token

`/gen-jwt` generates tokens signed with the **dev secret** — they return 401 on prod.

To get a prod token:
1. Open `https://portal.ihealthunifiedcare.com` in Chrome
2. DevTools → Network tab → any request to `uc-prod.ihealth-eng.com`
3. Copy `x-session-token` header value
4. `export UC_SESSION_TOKEN="<value>"`

---

## Reference Files

| File | Contents |
|------|----------|
| `SKILL.md` | Base skill — generic portal access, full command list |
| `rd-api.md` | This file — 5 RD-specific skills |
| `references/endpoints.md` | Full 526-endpoint catalog |
| `references/query-patterns.md` | Multi-step generic workflows |
| `scripts/uc_client.py` | Python client — add `rd-*` commands are at the bottom |
