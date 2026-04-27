# UnifiedCare API — Endpoint Catalog

**Base:** `https://dev-uc.ihealth-eng.com/v1/uc`  
**Auth:** `x-session-token: <JWT>` on every request  
**526 endpoints across 113 modules** — grouped by domain below.

---

## Table of Contents
1. [Auth & Session](#1-auth--session)
2. [Current User (Me)](#2-current-user-me)
3. [Patient — Core](#3-patient--core)
4. [Patient — Vitals & Measurements](#4-patient--vitals--measurements)
5. [Patient — CGM](#5-patient--cgm)
6. [Patient — Care Notes & Visits](#6-patient--care-notes--visits)
7. [Patient — Interventions & Goals](#7-patient--interventions--goals)
8. [Patient — Medications](#8-patient--medications)
9. [Patient — Alerts](#9-patient--alerts)
10. [Patient — Food Log & Lifestyle](#10-patient--food-log--lifestyle)
11. [Patient — Lab Results & Diagnosis](#11-patient--lab-results--diagnosis)
12. [Patient — Devices](#12-patient--devices)
13. [Patient — Billing & Time](#13-patient--billing--time)
14. [Care Team — Assignments](#14-care-team--assignments)
15. [Care Team — Tasks](#15-care-team--tasks)
16. [Care Team — Messages & Notifications](#16-care-team--messages--notifications)
17. [Visits & Calendar](#17-visits--calendar)
18. [Screening](#18-screening)
19. [Insights & Analytics](#19-insights--analytics)
20. [Utilities (Admin)](#20-utilities-admin)

---

## 1. Auth & Session

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/uc/auth/login` | Login → returns JWT token |
| GET | `/v1/uc/auth/me` | Current user profile + roles |
| GET | `/v1/uc/auth/refresh-token` | Refresh JWT |
| GET | `/v1/uc/auth/logout` | Invalidate session |
| POST | `/v1/uc/auth/send-otp` | Send OTP code |

**Login body:**
```json
{ "username": "email@domain.com", "password": "secret" }
```

**auth/me response shape:**
```json
{
  "data": {
    "id": "65bbcee3316c7e2fc37b3688",
    "firstName": "...", "lastName": "...",
    "email": "...",
    "roles": [{ "organization": {...}, "roles": ["RD"] }]
  }
}
```

---

## 2. Current User (Me)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/uc/employees/{userId}` | Employee profile |
| GET | `/v1/uc/employees/{userId}/with-roles` | Employee + role assignments |
| GET | `/v1/uc/on-call/{userId}` | On-call schedule |
| GET | `/v1/uc/role-assignments/getByEmployee/{userId}` | All roles for user |
| POST | `/v1/uc/employees/coworkers` | My coworkers list |

---

## 3. Patient — Core

### List / Search Patients
| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/uc/patient/list` | Full patient list with filters |
| POST | `/v1/uc/patient/assign/list` | Patients by assignee |
| POST | `/v1/uc/patient/search-list` | Search patients by name/MRN |
| POST | `/v1/uc/patient/home-list` | Limited list for home page widget |
| POST | `/v1/uc/patient/mini-patient-list` | Minimal patient data (id, name) |
| POST | `/v1/uc/patient/count` | Count patients matching filters |

**assign/list body (my patients):**
```json
{
  "assignees": ["<userId>"],
  "pagination": { "page": 1, "count": 50 }
}
```

**patient/list body:**
```json
{
  "organizationId": "<clinicId>",
  "pagination": { "page": 1, "count": 50 },
  "filters": {}
}
```

### Single Patient
| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/uc/patient/{memberId}` | Full patient profile |
| PUT | `/v1/uc/patient/{memberId}` | Update patient demographics |
| POST | `/v1/uc/patient/delete` | Soft-delete patient |

### Assignees
| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/uc/account/get/patient/{memberId}` | Get patient's assignees |
| POST | `/v1/uc/account/update/patient/assignees` | Update patient assignees |
| POST | `/v1/uc/patient/assignees` | Upsert assignees |

**Get patient assignees response:**
```json
{
  "data": {
    "RD": { "id": "...", "firstName": "...", "lastName": "..." },
    "CA": { "id": "...", "firstName": "...", "lastName": "..." }
  }
}
```

### Enrolled Programs
| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/uc/enrolled-programs/{memberId}` | Patient's enrolled programs (RPM, CGM, etc.) |
| POST | `/v1/uc/enrolled-programs/list` | List enrolled program patients |

---

## 4. Patient — Vitals & Measurements

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/uc/measurement/list` | Measurement history (BG, BP, SpO2, Weight, Temp) |
| GET | `/v1/uc/measurement/{memberId}` | Monthly measurements |
| POST | `/v1/uc/measurement/weight-summary` | Weight summary stats |
| POST | `/v1/uc/measurement/activity-logs` | Activity/step logs |
| POST | `/v1/uc/symptom-logs/list` | Symptom log entries |
| POST | `/v1/uc/logging-exercise/list` | Exercise log |
| POST | `/v1/uc/logging-wellness/list` | Wellness log |

**measurement/list body (PROD — confirmed from portal Network tab):**
```json
{
  "filter": {
    "memberId": "<memberId>",
    "dateRange": {
      "gte": "2026-03-01T08:00:00.000Z",
      "lte": "2026-04-01T06:59:59.999Z"
    },
    "typeList": ["BP"],
    "needStats": true,
    "needDataInVisits": true
  },
  "pageInfo": { "pagination": false }
}
```

> ⚠️ **Prod vs Dev differences:**
> - Prod requires `filter.memberId` (not top-level `memberId`)
> - Prod uses `filter.dateRange.gte / lte` (ISO UTC timestamps), NOT `startDate`/`endDate`
> - Prod uses `typeList` (not `type`) for measurement type filtering
> - Prod requires `pageInfo: { "pagination": false }` to return all records
> - Prod requires `filter.needStats: true` and `filter.needDataInVisits: true`
> - **The date filter is NOT reliably enforced server-side** — always filter client-side by `day` field
> - Prod response shape: `data.results.content[]` (NOT `data[]` directly)
> - Dev response shape: `data[]` list directly

**Prod response shape:**
```json
{
  "code": 200,
  "data": {
    "results": {
      "totalPage": null,
      "totalSize": null,
      "page": 1,
      "size": 50,
      "content": [ ...measurement records... ]
    },
    "lastMeasurements": [
      { "_id": "BP", "latestMeasurementDate": "2026-04-12T03:26:44.000" }
    ]
  }
}
```

**Prod measurement record field names (differ from dev):**
```json
{
  "type": "BP",
  "date": "2026-04-12T03:26:44.000",   // UTC — device measurement time
  "day":  "2026-04-11",                  // LOCAL date (patient's timezone)
  "timezone": "America/Los_Angeles",
  "systolic_blood_pressure":  { "value": 148, "unit": "mmHg" },
  "diastolic_blood_pressure": { "value": 89,  "unit": "mmHg" },
  "heart_rate":               { "value": 70,  "unit": "beats/min" },
  "blood_glucose":            { "value": 142, "unit": "mg/dL" },
  "bpSeverity": "HYPERTENSION_STAGE_2"
}
```

> Dev uses flat fields: `systolic`, `diastolic`, `blood_glucose` (number). Prod wraps them in `{ value, unit }` objects.

**Measurement types:** `BG` (blood glucose), `BP` (blood pressure), `SpO2`, `WT` (weight), `TMP` (temperature), `HS` (heart rate/pulse), `EX` (exercise)

**Date/time handling:**
- Always use `day` field (local date) for date-range filtering, NOT `date` (UTC)
- Use `date` (UTC) + `timezone` field for time-of-day bucketing — convert to local hour first
- `month_range('2026-03')` in `uc_client.py` generates correct UTC gte/lte for a calendar month in Pacific time

---

## 5. Patient — CGM

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/uc/cgm/rolling-stats` | CGM rolling stats (avg glucose, GMI, TIR) |
| POST | `/v1/uc/cgm/agp` | AGP (Ambulatory Glucose Profile) report |
| POST | `/v1/uc/cgm/agp/excursion-trend` | Excursion trend data |
| POST | `/v1/uc/cgm/reading` | CGM readings history |
| POST | `/v1/uc/cgm/reports/review` | CGM report review list |
| GET | `/v1/uc/cgm/reports/{reportId}` | Single CGM report |
| POST | `/v1/uc/cgm/weekly-summary/generate` | Generate weekly summary |
| GET | `/v1/uc/cgm/tips/patient/{memberId}` | CGM tips for patient |

**cgm/rolling-stats body:**
```json
{
  "memberId": "<memberId>",
  "startDate": "2026-01-01",
  "endDate": "2026-02-28",
  "intervalInDay": 14
}
```

---

## 6. Patient — Care Notes & Visits

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/uc/transcribe/search` | Search care notes / visit notes |
| POST | `/v1/uc/transcribe/search-visit` | Search visit records |
| GET | `/v1/uc/transcribe/a1c-due/{memberId}` | A1C due date |
| PUT | `/v1/uc/transcribe/note/{noteId}` | Update note |
| GET | `/v1/uc/call-summary/notes/{memberId}` | Call summary notes |
| POST | `/v1/uc/call-summary/notes` | Generate AI call summary |
| GET | `/v1/uc/post-its/list/{memberId}` | Sticky notes for patient |
| GET | `/v1/uc/food-log/list/{memberId}` | Food diary entries |
| POST | `/v1/uc/food-log/ai-insight` | AI insight on food log |

**transcribe/search body:**
```json
{
  "memberId": "<memberId>",
  "pagination": { "page": 1, "count": 50 }
}
```

**transcribe/search-visit body:**
```json
{
  "memberId": "<memberId>",
  "startDate": "2026-01-01",
  "endDate": "2026-02-28",
  "pagination": { "page": 1, "count": 20 }
}
```

---

## 7. Patient — Interventions & Goals

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/uc/patient/care-plan/search` | Care plan search |
| POST | `/v1/uc/patient/monthly-review/search` | Monthly review history |
| POST | `/v1/uc/monthly-review/search-monthly-review-refine` | Refined monthly review search |
| GET | `/v1/uc/task-assignment/patient/{memberId}` | Task assignments for patient |
| POST | `/v1/uc/lifestyle-assessment/send` | Send lifestyle assessment |

**care-plan/search body:**
```json
{ "memberId": "<memberId>" }
```

---

## 8. Patient — Medications

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/uc/medication/{memberId}` | Patient's medication list |
| POST | `/v1/uc/medication/dictionary/search` | Search medication dictionary |
| POST | `/v1/uc/medication/remove-medication` | Remove medication |
| POST | `/v1/uc/patient/medication-list/search` | Search UC medication management |
| POST | `/v1/uc/patient/medication-management` | Add medication management entry |

---

## 9. Patient — Alerts

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/uc/medical-alerts/{memberId}` | Open medical alerts (critical vitals) |
| POST | `/v1/uc/medical-alerts/search-alerts` | Search alert history |
| POST | `/v1/uc/medical-alerts/search-history` | Alert history by patient |
| POST | `/v1/uc/medical-alerts/resolve` | Resolve medical alert |
| GET | `/v1/uc/compliance-alert/patient-list/{memberId}` | Compliance alerts |
| PUT | `/v1/uc/compliance-alert/close` | Close compliance alert |
| GET | `/v1/uc/smart-alert-tasks/patient-list/{memberId}` | Smart alert tasks |
| PUT | `/v1/uc/smart-alert-tasks/close/{alertId}` | Close smart alert |

**medical-alerts/search-alerts body:**
```json
{
  "memberId": "<memberId>",
  "status": "OPEN",   // or "RESOLVED"
  "pagination": { "page": 1, "count": 20 }
}
```

---

## 10. Patient — Food Log & Lifestyle

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/uc/food-log/{logId}` | Single food log entry |
| GET | `/v1/uc/food-log/list/{memberId}` | Food log list |
| GET | `/v1/uc/food-log/last-log/{memberId}` | Most recent food log |
| POST | `/v1/uc/food-log/meal-label-trends` | Meal label trend data |
| POST | `/v1/uc/food-log/generate-ai-insight-with-history` | AI-generated food insight |
| PUT | `/v1/uc/food-log/{logId}` | Rate food log entry |
| POST | `/v1/uc/food-log/` | Add comment to food log |
| POST | `/v1/uc/logging-wellness/list` | Wellness activity log |

---

## 11. Patient — Lab Results & Diagnosis

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/uc/labResults/key-lab/{memberId}` | Key lab results (A1C, etc.) |
| GET | `/v1/uc/transcribe/a1c-window/{memberId}` | A1C test window |
| POST | `/v1/uc/icd10-billables/search` | Search ICD-10 codes |
| POST | `/v1/uc/icd-code-configs/classify` | Classify by ICD code |
| POST | `/v1/uc/patient/complexity/icd` | Patient complexity by ICD |

---

## 12. Patient — Devices

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/uc/patient-device/{memberId}` | Patient device info |
| POST | `/v1/uc/patient-device/patient-device-list` | All devices for patient |
| POST | `/v1/uc/patient/{memberId}/available-devices` | Available devices to assign |
| GET | `/v1/uc/phone-report-info/app-info/{memberId}` | Mobile app info |
| GET | `/v1/uc/phone-report-info/list/{memberId}` | Phone report info list |
| POST | `/v1/uc/cgm/patients/{memberId}` | Patient CGM device info |

---

## 13. Patient — Billing & Time

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/uc/billable-monthly-time/current` | Current month billable time |
| POST | `/v1/uc/billable-monthly-time/search-history` | Billable time history |
| POST | `/v1/uc/billable-time/search` | Billable time entries |
| POST | `/v1/uc/billable-time/daily` | Daily time spent |
| GET | `/v1/uc/insurance/all/{memberId}` | Patient insurance info |
| GET | `/v1/uc/insurance/prior-auth/{memberId}` | Prior auth status |

**billable-monthly-time/current body:**
```json
{ "memberId": "<memberId>" }
```

---

## 14. Care Team — Assignments

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/uc/clinic-assignments/list` | List clinic staff assignments |
| POST | `/v1/uc/role-assignments/list/members` | List organization members |
| POST | `/v1/uc/role-assignments/list/staffs` | List clinic staff |
| GET | `/v1/uc/role-assignments/getProviders/{orgId}` | Get providers for org |
| POST | `/v1/uc/patient-care/my-list` | My patient care summary (home page) |

**patient-care/my-list body:**
```json
{ "pagination": { "page": 1, "count": 50 } }
```

---

## 15. Care Team — Tasks

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/uc/task-assignment/search-grouped` | Search tasks grouped by type |
| GET | `/v1/uc/task-assignment/list/{userId}` | Task list for user |
| PUT | `/v1/uc/task-assignment/resolve/{taskId}` | Resolve task |
| GET | `/v1/uc/billable-time-review/todo/count` | Count items needing review |

**task-assignment/search-grouped body:**
```json
{
  "assigneeId": "<userId>",
  "status": "TODO",
  "pagination": { "page": 1, "count": 20 }
}
```

---

## 16. Care Team — Messages & Notifications

| Method | Path | Description |
|--------|------|-------------|
| PUT | `/v1/uc/outstanding/{itemId}` | Resolve outstanding item (message) |
| POST | `/v1/uc/internal-notification/send` | Send internal notification |
| POST | `/v1/uc/push-notification/send-custom-pn` | Send push notification to patient |
| POST | `/v1/uc/announcements/my-feed` | My announcements feed |
| POST | `/v1/uc/announcements/list` | All announcements |

---

## 17. Visits & Calendar

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/uc/clinic-event/list` | List clinic events/visits |
| POST | `/v1/uc/clinic-event/` | Check in patient to visit |
| POST | `/v1/uc/clinic-event/confirm` | Confirm scheduled visit |
| POST | `/v1/uc/clinic-event/cancel` | Cancel visit |
| POST | `/v1/uc/clinic-event/count` | Count clinic events |
| PUT | `/v1/uc/calendar-event/referenceId/{id}` | Update calendar visit |
| DELETE | `/v1/uc/calendar-event/referenceId/{id}` | Delete calendar visit |
| POST | `/v1/uc/calendar-event/search` | Search calendar events |
| PUT | `/v1/uc/visits/{visitId}` | Update visit record |

**clinic-event/list body:**
```json
{
  "organizationId": "<clinicId>",
  "startDate": "2026-01-01",
  "endDate": "2026-02-28",
  "pagination": { "page": 1, "count": 20 }
}
```

---

## 18. Screening

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/uc/screening-patient/list` | Screening patient list |
| POST | `/v1/uc/screening-patient/count` | Count screening patients |
| GET | `/v1/uc/screening-patient/{patientId}` | Screening history |
| POST | `/v1/uc/screening/my-jobs` | My screening jobs |
| POST | `/v1/uc/screening/check-out` | Check out patient |

---

## 19. Insights & Analytics

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/uc/insights/demographics` | Clinic demographics insight |
| GET | `/v1/uc/insights/billable-rate` | Billable rate insight |
| GET | `/v1/uc/insights/active-rate` | Active patient rate |
| GET | `/v1/uc/insights/compliance-rate-bg` | BG compliance rate |
| GET | `/v1/uc/insights/compliance-rate-bp` | BP compliance rate |
| GET | `/v1/uc/insights/total-billable-time` | Total billable time |
| GET | `/v1/uc/insights/clinical-outcome-bg` | BG clinical outcomes |
| GET | `/v1/uc/insights/clinical-outcome-bp` | BP clinical outcomes |
| POST | `/v1/uc/insight/vital` | Vital insight by cohort |
| POST | `/v1/uc/clinic-analytics/get-one` | Single clinic analytics |

**insights endpoints require org query param:**
```
GET /v1/uc/insights/billable-rate?organizationId=<clinicId>&startDate=2026-01-01&endDate=2026-02-28
```

---

## 20. Utilities (Admin)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/uc/transcribe-jobs/presigned-urls` | Get S3 upload URLs for transcription |
| GET | `/v1/uc/transcribe-jobs/{jobId}` | Transcription job status |
| POST | `/v1/uc/monthly-summary-report/generate` | Generate monthly summary report |
| POST | `/v1/uc/icd10-billables/search` | Search billable ICD codes |
| POST | `/v1/uc/articles/search` | Search patient education articles |
| POST | `/v1/uc/patient-upload-job-manager/create-job` | Create bulk patient upload job |
| GET | `/v1/uc/patient-upload-job-manager/latest-job` | Latest upload job status |
| GET | `/v1/uc/translate/languages` | Supported translation languages |

---

## Response Envelope
All endpoints return:
```json
{
  "code": 200,
  "data": { ... },         // or array
  "message": "SUCCESS"
}
```
Pagination responses include:
```json
{
  "data": {
    "patients": [...],
    "total": 150,
    "pageInfo": { "page": 1, "count": 50, "totalPage": 3 }
  }
}
```
