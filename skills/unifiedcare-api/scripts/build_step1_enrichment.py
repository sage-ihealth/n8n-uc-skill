"""
Step-1 enrichment for the MTPR table: compute the derived BP metrics that
mtpr.md says the skill must pre-compute (zoom-out funnel + PP trend +
stage mismatch + ISH + variability + extreme readings) and put each in its
own column.

Usage
-----
    export UC_SESSION_TOKEN="<jwt>"             # required (or PROD_TOKEN)
    export UC_BASE_URL="https://uc-prod.ihealth-eng.com/v1/uc"   # optional, defaults to prod
    python3 build_step1_enrichment.py [INPUT_CSV] [OUTPUT_CSV]

Defaults: INPUT_CSV  = ./mtpr_table_10patients_step2.csv
          OUTPUT_CSV = ./mtpr_table_10patients_step1full.csv

New columns (added between Step-1 raw and Step-2 columns):

  Pulse Pressure
    PP_Curr, PP_Prev, PP_Delta, PP_Class, PP_Trend

  Stage labels (ACC/AHA, applied to current avg)
    Stage_SBP_Curr, Stage_DBP_Curr, Stage_Overall_Curr,
    Stage_SBP_Prev, Stage_DBP_Prev,
    Stage_Mismatch (numeric, SBP_rank − DBP_rank), ISH_Flag

  Variability (over the last 30 days of raw BP readings)
    BP_SBP_SD, BP_DBP_SD, Variability_Flag (High if SD>15)

  Extreme reading counts (over the last 30 days)
    Count_SBP_180plus, Count_DBP_120plus,
    Count_SBP_under90, Count_DBP_under60,
    Extreme_Flag (Suspect if any of the above >0)

  Zoom-out funnel — weekly BP averages (6 weeks ending on MTPR Date)
    BP_W1, BP_W2, BP_W3, BP_W4, BP_W5, BP_W6  (W1 = most recent week)

  2-week vs 2-week
    BP_2W_Curr, BP_2W_Prev
"""

import csv
import os
import re
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

TOKEN = os.environ.get("UC_SESSION_TOKEN") or os.environ.get("PROD_TOKEN")
if not TOKEN:
    sys.exit(
        "error: set UC_SESSION_TOKEN (or PROD_TOKEN) before running. "
        "Use the /gen-jwt skill or export a fresh token from the portal."
    )

BASE_URL = os.environ.get("UC_BASE_URL", "https://uc-prod.ihealth-eng.com/v1/uc").rstrip("/")
LIST_URL = f"{BASE_URL}/measurement/list"
ORIGIN = "https://portal.ihealthunifiedcare.com" if "uc-prod" in BASE_URL else "https://ucfe-dev.ihealth-eng.com"

HDRS = {
    "x-session-token": TOKEN,
    "Origin": ORIGIN,
    "Content-Type": "application/json",
}

DEFAULT_IN = Path.cwd() / "mtpr_table_10patients_step2.csv"
DEFAULT_OUT = Path.cwd() / "mtpr_table_10patients_step1full.csv"

NEW_COLS = [
    "PP_Curr", "PP_Prev", "PP_Delta", "PP_Class", "PP_Trend",
    "Stage_SBP_Curr", "Stage_DBP_Curr", "Stage_Overall_Curr",
    "Stage_SBP_Prev", "Stage_DBP_Prev",
    "Stage_Mismatch", "ISH_Flag",
    "BP_SBP_SD", "BP_DBP_SD", "Variability_Flag",
    "Count_SBP_180plus", "Count_DBP_120plus",
    "Count_SBP_under90", "Count_DBP_under60", "Extreme_Flag",
    "BP_W1", "BP_W2", "BP_W3", "BP_W4", "BP_W5", "BP_W6",
    "BP_2W_Curr", "BP_2W_Prev",
]

STAGE_RANK = {"Normal": 0, "Elevated": 1, "Stage 1": 2, "Stage 2": 3, "Crisis": 4}


# ---------- pure helpers ----------

def parse_avg(s):
    """Parse '114.3/73.7 (n=47)' → (114.3, 73.7, 47); empty/None → None."""
    if not s:
        return None
    m = re.match(r"\s*(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)\s*\(n=(\d+)\)", s)
    if not m:
        return None
    return float(m.group(1)), float(m.group(2)), int(m.group(3))


def stage_sbp(sbp):
    if sbp is None: return ""
    if sbp >= 180:  return "Crisis"
    if sbp >= 140:  return "Stage 2"
    if sbp >= 130:  return "Stage 1"
    if sbp >= 120:  return "Elevated"
    return "Normal"


def stage_dbp(dbp):
    if dbp is None: return ""
    if dbp >= 120: return "Crisis"
    if dbp >= 90:  return "Stage 2"
    if dbp >= 80:  return "Stage 1"
    return "Normal"


def overall_stage(s, d):
    if not s: return ""
    if not d: return s
    return s if STAGE_RANK[s] >= STAGE_RANK[d] else d


def pp_class(pp):
    if pp is None: return ""
    if pp < 25: return "Low (<25)"
    if pp > 60: return "High (>60)"
    if pp < 40: return "Low-Normal (25-40)"
    return "Normal (40-60)"


def pp_trend(curr, prev):
    if curr is None or prev is None: return ""
    delta = curr - prev
    if abs(delta) < 2: return "Stable"
    if delta > 0:
        return "Worsening" if curr > 60 or curr < 25 else "Widening"
    return "Improving" if prev > 60 or prev < 25 else "Narrowing"


# ---------- API ----------

def fetch_bp_readings(member_id, gte, lt):
    """Page through measurement/list and return list of (datetime, sbp, dbp)."""
    out = []
    page = 0
    while True:
        body = {
            "filter": {
                "memberId": member_id,
                "typeList": ["BP"],
                "dateRange": {"gte": gte.isoformat().replace("+00:00", "Z"),
                              "lt": lt.isoformat().replace("+00:00", "Z")},
            },
            "pageInfo": {"page": page, "size": 200, "pagination": True},
        }
        try:
            r = requests.post(LIST_URL, headers=HDRS, json=body, timeout=20)
            r.raise_for_status()
            j = r.json()
            if j.get("code") != 200:
                break
            content = (j.get("data") or {}).get("results", {}).get("content") or []
        except Exception:
            break
        for m in content:
            sbp = (m.get("systolic_blood_pressure") or {}).get("value")
            dbp = (m.get("diastolic_blood_pressure") or {}).get("value")
            ds = m.get("date") or m.get("day")
            if sbp is None or dbp is None or not ds:
                continue
            try:
                if "T" in ds:
                    dt = datetime.fromisoformat(ds.replace("Z", "")).replace(tzinfo=timezone.utc)
                else:
                    dt = datetime.fromisoformat(ds).replace(tzinfo=timezone.utc)
            except Exception:
                continue
            out.append((dt, float(sbp), float(dbp)))
        if len(content) < 200:
            break
        page += 1
        if page > 30:
            break
    return out


# ---------- per-row enrichment ----------

def fmt_bp(readings):
    if not readings:
        return ""
    sbp = [r[1] for r in readings]
    dbp = [r[2] for r in readings]
    return f"{sum(sbp)/len(sbp):.1f}/{sum(dbp)/len(dbp):.1f} (n={len(sbp)})"


def enrich_row(row):
    out = {c: "" for c in NEW_COLS}

    curr = parse_avg(row.get("BP Curr (avg)"))
    prev = parse_avg(row.get("BP Prev (avg)"))

    if curr is None and prev is None:
        return out  # not a BP patient

    # ---- PP & Stage from existing avg cells (no API call needed) ----
    if curr:
        s, d, _ = curr
        pp_c = s - d
        out["PP_Curr"] = f"{pp_c:.1f}"
        out["PP_Class"] = pp_class(pp_c)
        out["Stage_SBP_Curr"] = stage_sbp(s)
        out["Stage_DBP_Curr"] = stage_dbp(d)
        out["Stage_Overall_Curr"] = overall_stage(out["Stage_SBP_Curr"], out["Stage_DBP_Curr"])
        mismatch = STAGE_RANK[out["Stage_SBP_Curr"]] - STAGE_RANK[out["Stage_DBP_Curr"]]
        out["Stage_Mismatch"] = str(mismatch)
        out["ISH_Flag"] = "Yes" if (out["Stage_SBP_Curr"] in ("Stage 2", "Crisis") and out["Stage_DBP_Curr"] == "Normal") else "No"
    if prev:
        s, d, _ = prev
        pp_p = s - d
        out["PP_Prev"] = f"{pp_p:.1f}"
        out["Stage_SBP_Prev"] = stage_sbp(s)
        out["Stage_DBP_Prev"] = stage_dbp(d)
    if curr and prev:
        out["PP_Delta"] = f"{(curr[0]-curr[1]) - (prev[0]-prev[1]):+.1f}"
        out["PP_Trend"] = pp_trend(curr[0]-curr[1], prev[0]-prev[1])

    # ---- Raw readings (last 6 weeks ending MTPR Date) ----
    pid = row["Patient ID"]
    mtpr_str = (row.get("MTPR Date") or "").strip()
    if not mtpr_str:
        return out
    try:
        mtpr_dt = datetime.strptime(mtpr_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return out

    six_weeks_ago = mtpr_dt - timedelta(days=42)
    print(f"  fetching BP for {row['Patient']}…", flush=True)
    readings = fetch_bp_readings(pid, six_weeks_ago, mtpr_dt)
    if not readings:
        return out

    # Variability + extremes over last 30 days (matches BP Curr (avg) window)
    thirty_ago = mtpr_dt - timedelta(days=30)
    last30 = [r for r in readings if r[0] >= thirty_ago]
    if len(last30) >= 2:
        sbps = [r[1] for r in last30]
        dbps = [r[2] for r in last30]
        sd_s = statistics.stdev(sbps)
        sd_d = statistics.stdev(dbps)
        out["BP_SBP_SD"] = f"{sd_s:.1f}"
        out["BP_DBP_SD"] = f"{sd_d:.1f}"
        out["Variability_Flag"] = "High" if (sd_s > 15 or sd_d > 10) else "Normal"
    if last30:
        out["Count_SBP_180plus"] = str(sum(1 for r in last30 if r[1] >= 180))
        out["Count_DBP_120plus"] = str(sum(1 for r in last30 if r[2] >= 120))
        out["Count_SBP_under90"] = str(sum(1 for r in last30 if r[1] < 90))
        out["Count_DBP_under60"] = str(sum(1 for r in last30 if r[2] < 60))
        any_extreme = any(int(out[k]) > 0 for k in
                          ("Count_SBP_180plus", "Count_DBP_120plus", "Count_SBP_under90", "Count_DBP_under60"))
        out["Extreme_Flag"] = "Suspect" if any_extreme else "Normal"

    # Weekly buckets W1..W6 (W1 = most recent 7 days ending MTPR Date)
    for i in range(6):
        w_end = mtpr_dt - timedelta(days=7 * i)
        w_start = w_end - timedelta(days=7)
        in_week = [r for r in readings if w_start <= r[0] < w_end]
        out[f"BP_W{i+1}"] = fmt_bp(in_week)

    # 2W vs 2W
    cur2w_start = mtpr_dt - timedelta(days=14)
    prev2w_start = mtpr_dt - timedelta(days=28)
    out["BP_2W_Curr"] = fmt_bp([r for r in readings if cur2w_start <= r[0] < mtpr_dt])
    out["BP_2W_Prev"] = fmt_bp([r for r in readings if prev2w_start <= r[0] < cur2w_start])

    return out


def main():
    csv_in = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_IN
    csv_out = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUT
    if not csv_in.exists():
        sys.exit(f"error: input CSV not found: {csv_in}")

    with csv_in.open() as f:
        rdr = csv.DictReader(f)
        rows = list(rdr)
        in_fields = rdr.fieldnames

    # Insert new columns after Step-1 raw cols and before Step-2 cols
    step2_set = {"Goals", "Lifestyle", "Nutrition", "LifestyleAssessment",
                 "FoodLogCount", "ExerciseLogCount"}
    out_fields = []
    inserted = False
    for f in in_fields:
        if f in step2_set and not inserted:
            out_fields.extend(NEW_COLS)
            inserted = True
        out_fields.append(f)
    if not inserted:
        out_fields.extend(NEW_COLS)

    enriched = []
    for row in rows:
        extras = enrich_row(row)
        new_row = dict(row)
        new_row.update(extras)
        enriched.append(new_row)

    with csv_out.open("w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=out_fields)
        wr.writeheader()
        for r in enriched:
            wr.writerow(r)
    print(f"\nWrote {csv_out}")


if __name__ == "__main__":
    main()
