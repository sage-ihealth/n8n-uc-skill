#!/usr/bin/env python3
"""
UnifiedCare API Client
======================
Authenticated HTTP client for the UnifiedCare backend.

Usage (standalone):
    python3 uc_client.py <command> [args...]

Commands:
    token                          - Extract & print current session token from browser
    get    <path>                  - GET /v1/uc/<path>
    post   <path> <json_body>      - POST /v1/uc/<path> with JSON body
    put    <path> <json_body>      - PUT /v1/uc/<path>
    delete <path>                  - DELETE /v1/uc/<path>

    # High-level helpers
    patient     <memberId>         - Full patient profile (demographics + enrolled programs)
    vitals      <memberId> [days]  - Recent vitals (default 30 days)
    care-notes  <memberId>         - Care notes list
    alerts      <memberId>         - Active medical + compliance alerts
    my-patients                    - Patients assigned to current user
    prioritize                     - My patients ranked by urgency
    summary     <memberId>         - Full patient summary (all data)

    # RD skills
    rd-patients  [page] [size]     - My RD patient panel (via assignedToRDIn filter)
    rd-bg        <memberId> [days] - BG + CGM review (TIR, TBR, AT, avg, patterns)
    rd-bp        <memberId> [days] - BP review (avg, AM/PM split, stage breakdown)
    rd-meds      <memberId>        - Medication highlight (by category + flags)
    rd-goals     <memberId>        - Goal tracker (prior MTPR goals + current status)

Examples:
    python3 uc_client.py patient 6705020f443bc6531d6b478c
    python3 uc_client.py my-patients
    python3 uc_client.py rd-patients
    python3 uc_client.py rd-bg  6705020f443bc6531d6b478c 30
    python3 uc_client.py rd-bp  6705020f443bc6531d6b478c 30
    python3 uc_client.py rd-meds  6705020f443bc6531d6b478c
    python3 uc_client.py rd-goals 6705020f443bc6531d6b478c
"""

import sys, os, json, subprocess, urllib.request, urllib.error
from datetime import datetime, timedelta

# ── Config ───────────────────────────────────────────────────────────────────
BASE_URL  = os.environ.get("UC_BASE_URL", "https://dev-uc.ihealth-eng.com/v1/uc")
CDP_URL   = "http://127.0.0.1:18800"
TOKEN_ENV = "UC_SESSION_TOKEN"


# ── Token extraction via Puppeteer ───────────────────────────────────────────
EXTRACT_TOKEN_JS = r"""
const puppeteer = require('puppeteer');
(async () => {
  const browser = await puppeteer.connect({ browserURL: 'http://127.0.0.1:18800' });
  const pages = await browser.pages();
  const page = pages.find(p => p.url().includes('ucfe-dev')) || pages[0];

  // Use CDP directly — no request interception (avoids race conditions)
  const client = await page.createCDPSession();
  let token = null;

  await client.send('Network.enable');
  client.on('Network.requestWillBeSent', event => {
    if (!token && event.request && event.request.url.includes('dev-uc.ihealth-eng.com')) {
      const hdrs = event.request.headers || {};
      const t = hdrs['x-session-token'] || hdrs['X-Session-Token'];
      if (t) token = t;
    }
  });

  await page.reload({ waitUntil: 'networkidle0', timeout: 20000 }).catch(() => {});

  await client.detach().catch(() => {});
  await browser.disconnect();

  if (token) { process.stdout.write(token); }
  else { process.stderr.write('NO_TOKEN'); process.exit(1); }
})().catch(e => { process.stderr.write(String(e)); process.exit(1); });
"""


def get_token() -> str:
    """Get session token: env var → browser extraction."""
    if TOKEN_ENV in os.environ and os.environ[TOKEN_ENV].strip():
        return os.environ[TOKEN_ENV].strip()
    try:
        node_path = "/home/ihealth/.npm-global/lib/node_modules"
        result = subprocess.run(
            ["node", "-e", EXTRACT_TOKEN_JS],
            capture_output=True, text=True, timeout=15,
            env={**os.environ, "NODE_PATH": node_path}
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        raise RuntimeError(result.stderr or "No token returned")
    except Exception as e:
        raise RuntimeError(
            f"Cannot get session token. Set env UC_SESSION_TOKEN or keep DEV portal open.\n{e}"
        )


def get_me(token: str) -> dict:
    """Get current user info (userId, orgId, etc.)."""
    return request("GET", "auth/me", token=token)


# ── HTTP helpers ─────────────────────────────────────────────────────────────
def request(method: str, path: str, body: dict = None, token: str = None) -> dict:
    if token is None:
        token = get_token()
    url = f"{BASE_URL}/{path.lstrip('/')}"
    data = json.dumps(body).encode() if body else None
    # Use prod portal origin when hitting prod, dev origin otherwise
    if "uc-prod" in BASE_URL or "portal.ihealthunifiedcare" in BASE_URL:
        origin = "https://portal.ihealthunifiedcare.com"
    else:
        origin = "https://ucfe-dev.ihealth-eng.com"
    headers = {
        "x-session-token": token,
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": origin,
        "Referer": f"{origin}/",
    }
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body_text = e.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {e.code} {e.reason} → {url}\n{body_text[:500]}")


def GET(path, token=None):    return request("GET",    path, token=token)
def POST(path, body, token=None): return request("POST", path, body, token=token)
def PUT(path, body, token=None):  return request("PUT",  path, body, token=token)
def DELETE(path, token=None): return request("DELETE", path, token=token)


# ── High-level patient helpers ────────────────────────────────────────────────
def date_range(days_back=30):
    end   = datetime.now()
    start = end - timedelta(days=days_back)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def _pacific_utc_offset(month: int) -> int:
    """UTC offset magnitude for Pacific time: 8=PST (Nov–Mar), 7=PDT (Apr–Oct)."""
    return 7 if 4 <= month <= 10 else 8


def _dates_to_iso_range(start_date: str, end_date: str):
    """
    Convert YYYY-MM-DD date strings to (gte, lte) ISO UTC timestamps for Pacific time.

    gte = midnight Pacific on start_date
    lte = 23:59:59.999 Pacific on end_date  (= midnight next day Pacific - 1 ms)

    Example (Feb 2026, PST=UTC-8):
      start='2026-02-01' → gte='2026-02-01T08:00:00.000Z'
      end='2026-02-28'   → lte='2026-03-01T07:59:59.999Z'
    """
    s_off = _pacific_utc_offset(int(start_date[5:7]))
    gte   = f"{start_date}T{s_off:02d}:00:00.000Z"

    # Advance end_date by 1 day, then subtract 1 ms → end-of-day in Pacific
    end_dt    = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
    next_date = end_dt.strftime("%Y-%m-%d")
    n_off     = _pacific_utc_offset(end_dt.month)
    lte       = f"{next_date}T{n_off - 1:02d}:59:59.999Z"
    return gte, lte


def month_range(month_str: str):
    """
    Return (gte, lte) ISO UTC timestamps for a calendar month like '2026-03'.

    Uses Pacific local midnight as boundaries:
      gte = first day of month midnight Pacific
      lte = first day of next month midnight Pacific - 1 ms

    Example (Feb 2026, PST=UTC-8):
      '2026-02' → ('2026-02-01T08:00:00.000Z', '2026-03-01T07:59:59.999Z')
    Example (Apr 2026, PDT=UTC-7):
      '2026-04' → ('2026-04-01T07:00:00.000Z', '2026-05-01T06:59:59.999Z')
    """
    year, mon = int(month_str[:4]), int(month_str[5:7])
    off       = _pacific_utc_offset(mon)
    gte       = f"{year:04d}-{mon:02d}-01T{off:02d}:00:00.000Z"

    # First day of next month, using that month's offset
    ny, nm    = (year, mon + 1) if mon < 12 else (year + 1, 1)
    next_off  = _pacific_utc_offset(nm)
    lte       = f"{ny:04d}-{nm:02d}-01T{next_off - 1:02d}:59:59.999Z"
    return gte, lte


def get_patient(member_id: str, token=None) -> dict:
    """Demographics + enrolled programs + assignees."""
    token = token or get_token()
    profile   = GET(f"patient/{member_id}", token)
    programs  = GET(f"enrolled-programs/{member_id}", token)
    assignees = GET(f"account/get/patient/{member_id}", token)
    return {"profile": profile, "programs": programs, "assignees": assignees}


def measurement_list(member_id: str, gte: str, lte: str, types=None, token=None) -> list:
    """
    Fetch measurements using the exact portal body structure.
    gte/lte: ISO UTC timestamps (from month_range or date_range_iso).
    types: list of type strings e.g. ["BP"], ["BG"] — maps to typeList in body.
    """
    token = token or get_token()
    body = {
        "filter": {
            "memberId": member_id,
            "dateRange": {"gte": gte, "lte": lte},
            "needStats": True,
            "needDataInVisits": True,
        },
        "pageInfo": {"pagination": False},
    }
    if types:
        body["filter"]["typeList"] = types

    resp = POST("measurement/list", body, token)
    raw = resp.get("data") or resp.get("result") or []

    # Prod shape: {"results": {"content": [...]}, ...}
    if isinstance(raw, dict) and "results" in raw:
        records = (raw.get("results") or {}).get("content") or []
    elif isinstance(raw, dict):
        records = raw.get("content") or raw.get("data") or []
    elif isinstance(raw, list):
        records = raw
    else:
        records = []

    # Filter by type client-side as well (belt-and-suspenders)
    if types:
        records = [r for r in records if r.get("type") in types]
    return records


def get_vitals(member_id: str, days=30, token=None) -> dict:
    """Recent vitals: BG, BP, SpO2, Weight, Temp measurements."""
    token = token or get_token()
    start, end = date_range(days)
    measurements = POST("measurement/list", {
        "memberId": member_id,
        "startDate": start,
        "endDate": end,
    }, token)
    cgm_stats = POST("cgm/rolling-stats", {
        "memberId": member_id,
        "startDate": start,
        "endDate": end,
    }, token)
    return {"measurements": measurements, "cgm": cgm_stats}


def get_care_notes(member_id: str, token=None) -> dict:
    """Care notes (visit notes + provider notes)."""
    token = token or get_token()
    return POST("transcribe/search", {
        "memberId": member_id,
        "pagination": {"page": 1, "count": 50},
    }, token)


def get_alerts(member_id: str, token=None) -> dict:
    """Medical alerts + compliance alerts for patient."""
    token = token or get_token()
    medical    = GET(f"medical-alerts/{member_id}", token)
    compliance = GET(f"compliance-alert/patient-list/{member_id}", token)
    smart      = GET(f"smart-alert-tasks/patient-list/{member_id}", token)
    return {"medical": medical, "compliance": compliance, "smart": smart}


def get_my_patients(token=None) -> list:
    """All patients assigned to the current authenticated user."""
    token = token or get_token()
    me = get_me(token)
    data = me.get("data", {}) or {}
    user_id = (data.get("userInfo") or {}).get("id") or data.get("id") or data.get("userId")
    if not user_id:
        raise RuntimeError(f"Cannot determine userId from auth/me. Response keys: {list(data.keys())}")
    resp = POST("patient/assign/list", {
        "assignees": [user_id],
        "pagination": {"page": 1, "count": 100},
    }, token)
    # Response shape varies — unwrap the data envelope
    inner = resp.get("data") or {}
    if isinstance(inner, list):
        return inner
    patients = (inner.get("patients") or inner.get("data") or
                resp.get("patients") or [])
    return patients


def prioritize_patients(token=None) -> list:
    """
    My patients ranked by urgency score.

    Scoring:
      +50  any open medical alert (critical vital)
      +30  any open compliance alert
      +20  any smart alert
      +15  no measurement in past 7 days
      +10  billable time < 20 min this month
      name, memberId returned with score + reasons
    """
    token = token or get_token()
    patients = get_my_patients(token)
    ranked = []

    for pt in patients:
        mid   = pt.get("memberId") or pt.get("id") or pt.get("_id")
        name  = pt.get("firstName","") + " " + pt.get("lastName","")
        score = 0
        reasons = []

        try:
            alerts = get_alerts(mid, token)
            if alerts["medical"] and (alerts["medical"].get("data") or []):
                score += 50; reasons.append("⚠️ Open medical alert")
            if alerts["compliance"] and (alerts["compliance"].get("data") or []):
                score += 30; reasons.append("📋 Compliance alert")
            if alerts["smart"] and (alerts["smart"].get("data") or []):
                score += 20; reasons.append("🔔 Smart alert")
        except Exception:
            pass

        try:
            start7, end7 = date_range(7)
            m = POST("measurement/list", {"memberId": mid, "startDate": start7, "endDate": end7}, token)
            count = len(m.get("data") or m.get("result") or [])
            if count == 0:
                score += 15; reasons.append("📉 No readings in 7 days")
        except Exception:
            pass

        try:
            bt = POST("billable-monthly-time/current", {"memberId": mid}, token)
            minutes = (bt.get("data") or {}).get("totalTime", 9999) / 60
            if minutes < 20:
                score += 10; reasons.append(f"⏱️ Only {int(minutes)}m billable this month")
        except Exception:
            pass

        ranked.append({"name": name.strip(), "memberId": mid, "score": score, "reasons": reasons, "raw": pt})

    return sorted(ranked, key=lambda x: x["score"], reverse=True)


# ── RD Skills ────────────────────────────────────────────────────────────────

MTPR_TAGS = {"MONTHLY_REVIEW", "MONTHLY_REVIEW_RD_HC"}

BG_MEDS = [
    "metformin","jardiance","farxiga","januvia","ozempic","trulicity","rybelsus",
    "insulin","novolog","humalog","glargine","tresiba","lantus","basaglar",
    "victoza","bydureon","mounjaro","zepbound",
]
BP_MEDS = [
    "lisinopril","losartan","amlodipine","metoprolol","carvedilol","diltiazem",
    "furosemide","hydrochlorothiazide","valsartan","sacubitril","olmesartan",
    "atenolol","bisoprolol","spironolactone","torsemide","chlorthalidone",
]
LIPID_MEDS = [
    "atorvastatin","rosuvastatin","simvastatin","pravastatin","lovastatin",
    "pitavastatin","fluvastatin","ezetimibe","fenofibrate","gemfibrozil",
]


def rd_patients(page=1, size=100, token=None) -> dict:
    """
    My RD patient panel — uses patient/home-list with assignedToRDIn filter.
    Returns { totalSize, patients: [{id, name, birthday, doctorId}] }
    """
    token = token or get_token()
    me = get_me(token)
    data = me.get("data") or {}
    user_id = (data.get("userInfo") or {}).get("id") or data.get("id") or data.get("userId")
    if not user_id:
        raise RuntimeError(f"Cannot determine userId from auth/me. Keys: {list(data.keys())}")

    resp = POST("patient/home-list", {
        "filter": {
            "patient": {"profile": {}},
            "needToFilter": True,
            "enrolledProgram": {},
            "enrollmentRequest": {},
            "listType": "ENROLLED",
            "assignee": {"assignedToRDIn": {"in": [user_id]}},
        },
        "pageInfo": {
            "page": page,
            "size": size,
            "sort": [{"property": "patientListInfo.enrollmentDate", "direction": "DESC"}],
        },
    }, token)

    inner = resp.get("data") or {}
    patients = inner.get("content") or []
    return {
        "totalSize": inner.get("totalSize", len(patients)),
        "totalPage": inner.get("totalPage", 1),
        "page": page,
        "patients": [
            {
                "id":       p.get("id"),
                "name":     f"{p.get('profile',{}).get('firstName','')} {p.get('profile',{}).get('lastName','')}".strip(),
                "birthday": (p.get("profile") or {}).get("birthday"),
                "doctorId": (p.get("profile") or {}).get("doctorId"),
            }
            for p in patients
        ],
    }


def _time_bucket(ts: str, timezone: str = "America/Los_Angeles") -> str:
    """
    Classify a UTC timestamp into Overnight/Morning/Afternoon/Evening
    using the patient's local timezone — matching portal logic exactly.

    Boundaries (portal source: timezoneService.getTimeOfDay):
      Overnight  : 0:00 –  3:59  local
      Morning    : 4:00 – 11:59  local
      Afternoon  : 12:00 – 17:59 local
      Evening    : 18:00 – 23:59 local

    Uses zoneinfo (Python 3.9+ stdlib) for DST-correct conversion.
    Falls back to static offsets if the timezone is not found.
    """
    try:
        from datetime import timezone as _tz
        try:
            from zoneinfo import ZoneInfo
            _tz_obj = ZoneInfo(timezone)
        except Exception:
            _tz_obj = None

        # Parse UTC timestamp (handles "2026-03-02T02:02:57" and "2026-03-02T02:02:57Z" etc.)
        ts_clean = ts[:19].replace("T", " ")
        dt_utc = datetime.strptime(ts_clean, "%Y-%m-%d %H:%M:%S").replace(tzinfo=_tz.utc)

        if _tz_obj:
            local_h = dt_utc.astimezone(_tz_obj).hour
        else:
            # Fallback: static offsets (no DST awareness)
            _TZ_OFFSETS = {
                "America/Los_Angeles": -7,
                "America/Denver":      -6,
                "America/Chicago":     -5,
                "America/New_York":    -4,
                "America/Phoenix":     -7,
            }
            offset = _TZ_OFFSETS.get(timezone, -7)
            h_utc = dt_utc.hour
            m_utc = dt_utc.minute
            local_h = (h_utc * 60 + m_utc + offset * 60) // 60 % 24
    except Exception:
        return "Overnight"

    if local_h < 4:   return "Overnight"
    if local_h < 12:  return "Morning"
    if local_h < 18:  return "Afternoon"
    return "Evening"


def rd_bg(member_id: str, days=30, token=None, month: str = None) -> dict:
    """
    BG + CGM review for an RD patient.
    Pulls CGM rolling stats (if on CGM) + raw BG measurements.
    Returns structured summary: AT, TIR, TBR, High, Avg, Est A1c, A1c lab,
    fasting/pre-meal/post-meal breakdown, morning/afternoon/evening split,
    current BG meds, SOP flag.

    Pass month='2026-03' to get a specific calendar month instead of days_back.
    """
    token = token or get_token()
    if month:
        start, end = month_range(month)
        import calendar as _cal
        y, m = int(month[:4]), int(month[5:7])
        display_period = f"{month}-01 → {month}-{_cal.monthrange(y, m)[1]:02d}"
    else:
        start, end = date_range(days)
        display_period = f"{start} → {end}"

    # CGM stats
    cgm = {}
    try:
        cgm_resp = POST("cgm/rolling-stats", {
            "memberId": member_id,
            "startDate": start,
            "endDate": end,
            "intervalInDay": days,
        }, token)
        cgm = cgm_resp.get("data") or {}
    except Exception:
        pass

    # Raw BG measurements
    readings = measurement_list(member_id, start, end, ["BG"], token)

    def avg(lst): return round(sum(lst) / len(lst), 1) if lst else None
    def mn(lst):  return min(lst) if lst else None
    def mx(lst):  return max(lst) if lst else None

    def bg_val(r):
        # prod: blood_glucose.value (obj with unit); dev: blood_glucose (number) or value
        bg = r.get("blood_glucose")
        if isinstance(bg, dict):
            v = bg.get("value") or 0
            # Convert mmol/L → mg/dL if needed
            if bg.get("unit") == "mmol/L":
                v = round(v * 18.0156, 1)
            return v
        return bg or r.get("value") or 0

    # Portal-exact classification (source: BGChartHelper.ts + useBGResultToSummaryTable.ts)
    # Fields: mealType (BgMealTypeEnum), beforeMeal (bool), bgSeverity (BgSeverityEnum)
    def meal(r): return r.get("mealType") or ""
    def before(r): return r.get("beforeMeal") in (True, "true", 1)
    def severity(r): return r.get("bgSeverity") or ""

    all_vals    = [bg_val(r) for r in readings]
    # Fasting = pre-breakfast + overnight
    fasting     = [bg_val(r) for r in readings
                   if (meal(r) == "BREAKFAST" and before(r)) or meal(r) == "OVERNIGHT"]
    # Before Meal = pre-lunch + pre-dinner
    pre_meal    = [bg_val(r) for r in readings
                   if meal(r) in ("LUNCH", "DINNER") and before(r)]
    # After Meal = post-breakfast/lunch/dinner + bedtime
    post_meal   = [bg_val(r) for r in readings
                   if (meal(r) in ("BREAKFAST", "LUNCH", "DINNER") and not before(r))
                   or meal(r) == "BEDTIME"]
    # Bedtime / Overnight as standalone groups
    bedtime     = [bg_val(r) for r in readings if meal(r) == "BEDTIME"]
    overnight   = [bg_val(r) for r in readings if meal(r) == "OVERNIGHT"]
    # Critical severity
    crit_high   = [bg_val(r) for r in readings if severity(r) == "CRITICAL"]
    crit_low    = [bg_val(r) for r in readings if severity(r) == "VERY_LOW"]

    # Overnight / Morning / Afternoon / Evening split — portal-exact boundaries
    _BUCKETS = ("Overnight", "Morning", "Afternoon", "Evening")
    buckets = {k: [] for k in _BUCKETS}
    for r in readings:
        ts  = r.get("date") or r.get("createdAt") or ""
        tz  = r.get("timezone") or "America/Los_Angeles"
        buckets[_time_bucket(ts, tz)].append(bg_val(r))

    # A1c from labs
    a1c_val, a1c_date = None, None
    try:
        labs = GET(f"labResults/key-lab/{member_id}", token)
        a1c_data = (labs.get("data") or {}).get("A1C") or {}
        a1c_val  = a1c_data.get("value")
        a1c_date = (a1c_data.get("date") or "")[:10]
    except Exception:
        pass

    # BG meds
    meds_resp = GET(f"medication/{member_id}", token)
    all_meds  = meds_resp.get("data") or []
    bg_meds   = [m.get("name") for m in all_meds if any(k in (m.get("name") or "").lower() for k in BG_MEDS) and m.get("active", True)]

    # SOP flag
    tir  = cgm.get("timeInRange")
    tbr  = cgm.get("timeBelowRange")
    wear = cgm.get("activeTime")
    sop_flags = []
    if a1c_val and a1c_val >= 8.0:        sop_flags.append(f"A1c ≥ 8.0% ({a1c_val}%)")
    if tir  is not None and tir  < 50:    sop_flags.append(f"TIR < 50% ({tir}%)")
    if tbr  is not None and tbr  > 4:     sop_flags.append(f"TBR > 4% ({tbr}%)")
    if wear is not None and wear < 50:    sop_flags.append(f"Wear < 50% ({wear}%)")
    sop = "UNCONTROLLED (VC.3.1)" if sop_flags else ("CONTROLLED (VC.3.2)" if tir is not None or a1c_val else "UNKNOWN")

    return {
        "period": display_period,
        "cgm": {
            "activeTime":    cgm.get("activeTime"),
            "TIR":           cgm.get("timeInRange"),
            "TBR":           cgm.get("timeBelowRange"),
            "high":          cgm.get("timeAboveRange"),
            "avg":           cgm.get("averageGlucose"),
            "gv":            cgm.get("cv"),
            "estA1c":        cgm.get("gmi"),
        } if cgm else None,
        "bg_readings": {
            "total":        len(readings),
            "all":          {"avg": avg(all_vals),  "min": mn(all_vals),  "max": mx(all_vals)},
            # Portal-exact 7 categories (BGSummaryKey order from useBGResultToSummaryTable.ts)
            "fasting":      {"n": len(fasting),     "avg": avg(fasting),     "min": mn(fasting),     "max": mx(fasting)},
            "before_meal":  {"n": len(pre_meal),    "avg": avg(pre_meal),    "min": mn(pre_meal),    "max": mx(pre_meal)},
            "after_meal":   {"n": len(post_meal),   "avg": avg(post_meal),   "min": mn(post_meal),   "max": mx(post_meal)},
            "bedtime":      {"n": len(bedtime),      "avg": avg(bedtime),     "min": mn(bedtime),     "max": mx(bedtime)},
            "overnight":    {"n": len(overnight),    "avg": avg(overnight),   "min": mn(overnight),   "max": mx(overnight)},
            "critical_high":{"n": len(crit_high),   "avg": avg(crit_high),   "min": mn(crit_high),   "max": mx(crit_high)},
            "critical_low": {"n": len(crit_low),    "avg": avg(crit_low),    "min": mn(crit_low),    "max": mx(crit_low)},
        },
        "time_of_day": {
            k: {"n": len(v), "avg": avg(v), "min": mn(v), "max": mx(v)}
            for k, v in buckets.items()
        },
        "a1c":     {"value": a1c_val, "date": a1c_date},
        "bg_meds": bg_meds,
        "sop":     sop,
        "sop_flags": sop_flags,
    }


def rd_bp(member_id: str, days=30, token=None, month: str = None) -> dict:
    """
    BP review for an RD patient.
    Returns avg SBP/DBP, reading count, morning/afternoon/evening split,
    stage breakdown, trend direction, goal status, current BP meds.

    Pass month='2026-03' to get a specific calendar month instead of days_back.
    """
    token = token or get_token()
    if month:
        start, end = month_range(month)
        import calendar as _cal
        y, m = int(month[:4]), int(month[5:7])
        display_period = f"{month}-01 → {month}-{_cal.monthrange(y, m)[1]:02d}"
    else:
        start, end = date_range(days)
        display_period = f"{start} → {end}"

    readings = measurement_list(member_id, start, end, ["BP"], token)

    def avg(lst): return round(sum(lst) / len(lst), 1) if lst else None

    def sbp_val(r):
        # prod: systolic_blood_pressure.value; dev: systolic or value.systolic
        sbp = r.get("systolic_blood_pressure")
        if isinstance(sbp, dict): return sbp.get("value") or 0
        return r.get("systolic") or (r.get("value") or {}).get("systolic") or 0

    def dbp_val(r):
        dbp = r.get("diastolic_blood_pressure")
        if isinstance(dbp, dict): return dbp.get("value") or 0
        return r.get("diastolic") or (r.get("value") or {}).get("diastolic") or 0

    sbp = [sbp_val(r) for r in readings]
    dbp = [dbp_val(r) for r in readings]

    def stage(s, d):
        if s >= 180 or d >= 120: return "Critical"
        if s >= 160 or d >= 100: return "Stage 2"
        if s >= 140 or d >= 90:  return "Stage 1"
        if s >= 130 or d >= 80:  return "Elevated"
        return "Normal"

    stages = [stage(s, d) for s, d in zip(sbp, dbp)]
    from collections import Counter
    stage_counts = Counter(stages)
    n = len(readings)

    # Overnight / Morning / Afternoon / Evening split — portal-exact boundaries
    BUCKETS = ("Overnight", "Morning", "Afternoon", "Evening")
    tod_sbp = {k: [] for k in BUCKETS}
    tod_dbp = {k: [] for k in BUCKETS}
    for r in readings:
        ts  = r.get("date") or r.get("createdAt") or ""
        tz  = r.get("timezone") or "America/Los_Angeles"
        bkt = _time_bucket(ts, tz)
        tod_sbp[bkt].append(sbp_val(r))
        tod_dbp[bkt].append(dbp_val(r))

    time_of_day = {
        k: {
            "n":       len(tod_sbp[k]),
            "avg_sbp": avg(tod_sbp[k]),
            "avg_dbp": avg(tod_dbp[k]),
        }
        for k in BUCKETS
    }

    # Trend: compare first half vs second half avg SBP
    trend = "insufficient data"
    if n >= 6:
        first_half  = sbp[:n // 2]
        second_half = sbp[n // 2:]
        diff = avg(second_half) - avg(first_half)
        trend = "improving" if diff < -3 else ("worsening" if diff > 3 else "stable")

    # Goal met: avg SBP < 130 AND avg DBP < 80
    avg_sbp, avg_dbp = avg(sbp), avg(dbp)
    goal_met = (avg_sbp is not None and avg_dbp is not None and avg_sbp < 130 and avg_dbp < 80)

    # BP meds
    meds_resp = GET(f"medication/{member_id}", token)
    all_meds  = meds_resp.get("data") or []
    bp_meds   = [m.get("name") for m in all_meds if any(k in (m.get("name") or "").lower() for k in BP_MEDS) and m.get("active", True)]

    # Escalation flag
    critical_count = stage_counts.get("Critical", 0)
    s2_pct = round((stage_counts.get("Stage 2", 0) + critical_count) / n * 100) if n else 0
    if critical_count > 0: escalation = "🔴 Hard — critical readings present"
    elif s2_pct >= 70:     escalation = "🟡 Soft — >70% Stage 2"
    elif not goal_met:     escalation = "🟡 Soft — goal not met"
    else:                  escalation = "🟢 On track"

    return {
        "period":         display_period,
        "total_readings": n,
        "avg":            {"sbp": avg_sbp, "dbp": avg_dbp},
        "time_of_day":    time_of_day,
        "stages":         dict(stage_counts),
        "stage2_pct":     s2_pct,
        "trend":          trend,
        "goal_met":       goal_met,
        "bp_meds":        bp_meds,
        "escalation":     escalation,
    }


def rd_meds(member_id: str, token=None) -> dict:
    """
    Medication highlight for an RD patient.
    Groups meds by category (BG / BP / Lipid / Other),
    surfaces discrepancy flags and suggested CA tasks.
    """
    token = token or get_token()
    resp = GET(f"medication/{member_id}", token)
    all_meds = resp.get("data") or []

    bg, bp, lipid, other = [], [], [], []
    for m in all_meds:
        name  = (m.get("name") or "").lower()
        entry = {
            "name":      m.get("name"),
            "dosage":    m.get("dosage"),
            "frequency": m.get("frequency"),
            "active":    m.get("active", True),
        }
        if   any(k in name for k in BG_MEDS):    bg.append(entry)
        elif any(k in name for k in BP_MEDS):    bp.append(entry)
        elif any(k in name for k in LIPID_MEDS): lipid.append(entry)
        else:                                     other.append(entry)

    # Flags
    flags = []
    if not all_meds:
        flags.append("⚠️  No medications on portal — Tasked CA to complete meds list")
    if lipid and not any("hld" in (m.get("condition") or "").lower() for m in all_meds):
        flags.append("⚠️  On lipid med but HLD diagnosis not confirmed — Tasked CA to verify diagnosis")
    if not bg and not bp:
        flags.append("ℹ️  No BG or BP meds on record — verify with patient at next visit")

    return {
        "bg_meds":    bg,
        "bp_meds":    bp,
        "lipid_meds": lipid,
        "other_meds": other,
        "total":      len(all_meds),
        "flags":      flags,
    }


def rd_goals(member_id: str, token=None) -> dict:
    """
    Goal tracker for an RD patient.
    Reads the most recent MONTHLY_REVIEW note, extracts numbered goals,
    and returns them verbatim for RD review at next visit.
    """
    import re
    token = token or get_token()

    resp = POST("care-note/search", {
        "filter": {"memberId": member_id},
        "pageInfo": {"pagination": False},
    }, token)
    notes = resp.get("data") or []

    mtpr_notes = sorted(
        [n for n in notes if set(n.get("tags") or []) & MTPR_TAGS],
        key=lambda x: x.get("createdAt", ""), reverse=True
    )

    if not mtpr_notes:
        return {"last_mtpr": None, "goals": [], "raw_content": None}

    last = mtpr_notes[0]
    content = (last.get("content") or "").strip()

    # Extract numbered goals (lines starting with "N)")
    goal_blocks = re.findall(r'(\d+\)\s+.+?)(?=\n\d+\)|$)', content, re.DOTALL)
    goals = [g.strip() for g in goal_blocks]

    # Also collect all MTPR dates for history
    history = [
        {
            "date":   (n.get("createdAt") or "")[:10],
            "author": f"{(n.get('createdByUser') or {}).get('firstName','')} {(n.get('createdByUser') or {}).get('lastName','')}".strip(),
            "tag":    (n.get("tags") or [""])[0],
        }
        for n in mtpr_notes[:6]
    ]

    return {
        "last_mtpr": {
            "date":    (last.get("createdAt") or "")[:10],
            "author":  f"{(last.get('createdByUser') or {}).get('firstName','')} {(last.get('createdByUser') or {}).get('lastName','')}".strip(),
            "note_id": last.get("id"),
        },
        "goals":       goals,
        "raw_content": content,
        "history":     history,
    }


# ── Full patient summary ───────────────────────────────────────────────────────
def full_patient_summary(member_id: str, token=None) -> dict:
    """All data for a patient in one call: profile, vitals, care notes, alerts, medications, food log."""
    token = token or get_token()
    return {
        "patient":     get_patient(member_id, token),
        "vitals":      get_vitals(member_id, 30, token),
        "care_notes":  get_care_notes(member_id, token),
        "alerts":      get_alerts(member_id, token),
        "medications": GET(f"medication/{member_id}", token),
        "food_log":    GET(f"food-log/list/{member_id}", token),
        "lab_results": GET(f"labResults/key-lab/{member_id}", token),
        "post_its":    GET(f"post-its/list/{member_id}", token),
    }


# ── CLI ───────────────────────────────────────────────────────────────────────
def pp(data):
    print(json.dumps(data, indent=2, default=str))


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)

    cmd = args[0]
    token = get_token()

    if cmd == "token":
        print(token)

    elif cmd in ("get", "GET"):
        pp(GET(args[1], token))

    elif cmd in ("post", "POST"):
        body = json.loads(args[2]) if len(args) > 2 else {}
        pp(POST(args[1], body, token))

    elif cmd in ("put", "PUT"):
        body = json.loads(args[2]) if len(args) > 2 else {}
        pp(PUT(args[1], body, token))

    elif cmd in ("delete", "DELETE"):
        pp(DELETE(args[1], token))

    elif cmd == "patient":
        pp(get_patient(args[1], token))

    elif cmd == "vitals":
        days = int(args[2]) if len(args) > 2 else 30
        pp(get_vitals(args[1], days, token))

    elif cmd == "care-notes":
        pp(get_care_notes(args[1], token))

    elif cmd == "alerts":
        pp(get_alerts(args[1], token))

    elif cmd == "my-patients":
        patients = get_my_patients(token)
        print(f"Found {len(patients)} patients assigned to you:")
        for p in patients:
            name = f"{p.get('firstName','')} {p.get('lastName','')}".strip()
            mid = p.get('memberId') or p.get('id')
            print(f"  • {name} — {mid}")

    elif cmd == "prioritize":
        print("Ranking your patients by urgency...\n")
        ranked = prioritize_patients(token)
        for i, p in enumerate(ranked, 1):
            print(f"{i}. {p['name']} (score={p['score']})")
            for r in p["reasons"]:
                print(f"   {r}")
            if not p["reasons"]:
                print("   ✅ No urgent flags")
            print()

    elif cmd == "summary":
        pp(full_patient_summary(args[1], token))

    # ── RD skills ──────────────────────────────────────────────────────────
    elif cmd == "rd-patients":
        page = int(args[1]) if len(args) > 1 else 1
        size = int(args[2]) if len(args) > 2 else 100
        result = rd_patients(page, size, token)
        print(f"RD patient panel — {result['totalSize']} total enrolled patients")
        print(f"Page {result['page']} | Showing {len(result['patients'])} patients\n")
        for i, p in enumerate(result["patients"], 1 + (page - 1) * size):
            print(f"  {i:>4}.  {p['name']:<30}  {p['id']}")

    elif cmd == "rd-bg":
        if len(args) < 2:
            print("Usage: rd-bg <memberId> [days|YYYY-MM]"); sys.exit(1)
        month, days = None, 30
        if len(args) > 2:
            if "-" in args[2] and len(args[2]) == 7:
                month = args[2]
            else:
                days = int(args[2])
        result = rd_bg(args[1], days, token, month=month)
        label = f"month {month}" if month else f"last {days} days"
        print(f"BG / CGM Review — {label} ({result['period']})\n")
        if result["cgm"]:
            c = result["cgm"]
            print("CGM:")
            print(f"  Active Time : {c['activeTime']}%")
            print(f"  TIR         : {c['TIR']}%")
            print(f"  TBR         : {c['TBR']}%")
            print(f"  High        : {c['high']}%")
            print(f"  Avg glucose : {c['avg']} mg/dL")
            print(f"  GV (CV)     : {c['gv']}%")
            print(f"  Est A1c     : {c['estA1c']}%")
        else:
            print("CGM: No data (not on CGM or no recent sensor)")
        bg = result["bg_readings"]
        print(f"\nBG readings: {bg['total']} total")
        # All-readings summary
        d = bg["all"]
        print(f"  {'All':<14}: avg={d['avg']}  min={d['min']}  max={d['max']}  (n={bg['total']})")
        # Portal-exact 7 categories
        for label2, key in [
            ("Fasting",       "fasting"),
            ("Before Meal",   "before_meal"),
            ("After Meal",    "after_meal"),
            ("Bedtime",       "bedtime"),
            ("Overnight",     "overnight"),
            ("Critical High", "critical_high"),
            ("Critical Low",  "critical_low"),
        ]:
            d = bg[key]
            if d["n"] > 0:
                print(f"  {label2:<14}: avg={d['avg']}  min={d['min']}  max={d['max']}  (n={d['n']})")
        print(f"\nTime of day:")
        for tod, d in result["time_of_day"].items():
            if d["n"] > 0:
                print(f"  {tod:<12}: avg={d['avg']}  min={d['min']}  max={d['max']}  (n={d['n']})")
        a1c = result["a1c"]
        print(f"\nA1c: {a1c['value']}% ({a1c['date']})" if a1c["value"] else "\nA1c: No recent lab")
        print(f"BG meds: {', '.join(result['bg_meds']) if result['bg_meds'] else 'None on record'}")
        print(f"\nSOP: {result['sop']}")
        if result["sop_flags"]:
            for f in result["sop_flags"]:
                print(f"  ⚠  {f}")

    elif cmd == "rd-bp":
        if len(args) < 2:
            print("Usage: rd-bp <memberId> [days|YYYY-MM]"); sys.exit(1)
        month, days = None, 30
        if len(args) > 2:
            if "-" in args[2] and len(args[2]) == 7:
                month = args[2]
            else:
                days = int(args[2])
        result = rd_bp(args[1], days, token, month=month)
        label = f"month {month}" if month else f"last {days} days"
        print(f"BP Review — {label} ({result['period']})\n")
        print(f"Total readings : {result['total_readings']}")
        av = result["avg"]
        print(f"Average        : {av['sbp']}/{av['dbp']} mmHg")
        print(f"\nTime of day:")
        for tod in ("Overnight", "Morning", "Afternoon", "Evening"):
            d = result["time_of_day"][tod]
            flag = "" if d["n"] > 0 else "  (no readings)"
            val  = f"{d['avg_sbp']}/{d['avg_dbp']} mmHg  (n={d['n']})" if d["n"] > 0 else "—"
            print(f"  {tod:<12}: {val}{flag}")
        print(f"\nStage breakdown:")
        for st, count in sorted(result["stages"].items(), key=lambda x: x[1], reverse=True):
            pct = round(count / result["total_readings"] * 100) if result["total_readings"] else 0
            print(f"  {st:<12}: {count:>3} readings  ({pct}%)")
        print(f"\nTrend          : {result['trend']}")
        print(f"Goal met       : {'✅ Yes' if result['goal_met'] else '❌ No'}")
        print(f"BP meds        : {', '.join(result['bp_meds']) if result['bp_meds'] else 'None on record'}")
        print(f"Escalation     : {result['escalation']}")

    elif cmd == "rd-meds":
        if len(args) < 2:
            print("Usage: rd-meds <memberId>"); sys.exit(1)
        result = rd_meds(args[1], token)
        print(f"Medication Highlight — {result['total']} total medications\n")
        for category, key in [("BG Meds", "bg_meds"), ("BP Meds", "bp_meds"),
                               ("Lipid Meds", "lipid_meds"), ("Other", "other_meds")]:
            meds = result[key]
            if meds:
                print(f"{category}:")
                for m in meds:
                    status = "" if m.get("active", True) else " [inactive]"
                    print(f"  • {m['name']}  {m['dosage'] or ''}  {m['frequency'] or ''}{status}")
        if result["flags"]:
            print("\nFlags:")
            for f in result["flags"]:
                print(f"  {f}")

    elif cmd == "rd-goals":
        if len(args) < 2:
            print("Usage: rd-goals <memberId>"); sys.exit(1)
        result = rd_goals(args[1], token)
        if not result["last_mtpr"]:
            print("No MTPR notes found for this patient.")
        else:
            lm = result["last_mtpr"]
            print(f"Last MTPR: {lm['date']}  by {lm['author']}  (note: {lm['note_id']})\n")
            if result["goals"]:
                print("Goals from last MTPR (verbatim):")
                for g in result["goals"]:
                    print(f"\n  {g}")
            else:
                print("No numbered goals found in last MTPR note.")
                print("\nFull note content:")
                print(result["raw_content"])
            if result["history"]:
                print(f"\nMTPR history (last {len(result['history'])}):")
                for h in result["history"]:
                    print(f"  {h['date']}  {h['author']:<20}  {h['tag']}")

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
