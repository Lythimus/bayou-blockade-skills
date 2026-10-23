#!/usr/bin/env python3
"""MISO generator interconnection queue, filtered by state, parish, substation
(point of interconnection), fuel, status or project number. Reads MISO's public
queue API (https://www.misoenergy.org/api/giqueue/getprojects, ~2.3 MB JSON, no key)
and MISO's Expedited Resource Addition Study (ERAS) request workbook (~45 KB xlsx,
linked from the Generator Interconnection page), and caches both for a day.

Usage:
  miso_queue.py --state LA --parish "St. Charles"
  miso_queue.py --poi waterford
  miso_queue.py --state LA --fuel gas --status active
  miso_queue.py --project J3871 [--json]

Newer requests are published with a blank state and county. With --state or
--parish, the script also lists blank-location requests whose transmission owner
serves that state, tagged "location not published", instead of silently dropping them.
ERAS requests (E-numbers) are a separate fast-track list that the queue API does not
carry; a unit can be withdrawn from the queue and live on in ERAS. They are filtered
the same way (--owner also matches the interconnection customer). --no-eras skips them.
Exit status: 0 checked, 2 the queue could not be read. An unreadable ERAS workbook is
reported as "ERAS not checked" and does not change the exit status.
Stdlib only.
"""
import argparse
import collections
import datetime
import json
import os
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

URL = "https://www.misoenergy.org/api/giqueue/getprojects"
CACHE = os.path.expanduser("~/.cache/bayou/miso-queue/getprojects.json")
MAX_AGE_HOURS = 24
DATES = ("queueDate", "inService", "negInService", "withdrawnDate", "doneDate")
ERAS_PAGE = "https://www.misoenergy.org/planning/resource-utilization/generator-interconnection/"
ERAS_FALLBACK = "https://cdn.misoenergy.org/ERAS%20Interconnection%20Requests718482.xlsx"
ERAS_CACHE = os.path.expanduser("~/.cache/bayou/miso-queue/eras-requests.xlsx")
XNS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
# ERAS workbook header -> queue API field name, so one filter function serves both lists.
ERAS_FIELDS = {"Project Number": "projectNumber", "Application ID": "applicationId", "GIA Status": "giaStatus",
               "Interconnection Customer": "customer", "Request Status": "applicationStatus",
               "Submission Time": "queueDate", "Date Withdrawn": "withdrawnDate",
               "Application In Service Date": "inService", "Transmission Owner": "transmissionOwner",
               "County": "county", "State": "state", "Study Cycle": "studyCycle", "Service Type": "svcType",
               "POI Name": "poiName", "Max Summer MW": "summerNetMW", "Fuel Type": "fuelType",
               "Generating Facility": "facilityType", "Requested NRIS MW": "nrisMW",
               "MW Range of Need": "needMW", "Location of Need": "needLocation",
               "Carve Out Requested": "carveOut", "Non-Confidential Summary": "summary"}


def load(refresh=False):
    fresh = os.path.exists(CACHE) and time.time() - os.path.getmtime(CACHE) < MAX_AGE_HOURS * 3600
    if fresh and not refresh:
        with open(CACHE) as f:
            return json.load(f), time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(CACHE)))
    try:
        req = urllib.request.Request(URL, headers={"User-Agent": "bayou-miso-queue", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.load(r)
        if not isinstance(data, list) or not data or "projectNumber" not in data[0]:
            raise ValueError("response is not the expected list of queue projects")
    except (OSError, ValueError) as e:
        if os.path.exists(CACHE):
            print(f"warning: queue refresh failed ({e}); using cached copy", file=sys.stderr)
            with open(CACHE) as f:
                return json.load(f), time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(CACHE)))
        raise
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE + ".part", "w") as f:
        json.dump(data, f)
    os.replace(CACHE + ".part", CACHE)
    return data, time.strftime("%Y-%m-%d %H:%M")


def fetch(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": "bayou-miso-queue"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def read_xlsx(data):
    """First sheet as a list of dicts keyed by the header row."""
    import io
    z = zipfile.ZipFile(io.BytesIO(data))
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(XNS + "si"):
            shared.append("".join(t.text or "" for t in si.iter(XNS + "t")))
    out, header = [], None
    for row in ET.fromstring(z.read("xl/worksheets/sheet1.xml")).iter(XNS + "row"):
        cells = {}
        for c in row.iter(XNS + "c"):
            col = re.match(r"[A-Z]+", c.get("r")).group()
            v, t = c.find(XNS + "v"), c.get("t")
            if t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(XNS + "t"))
            elif v is None:
                val = ""
            elif t == "s":
                val = shared[int(v.text)]
            else:
                val = v.text
            cells[col] = val.strip()
        if header is None:
            header = cells
            continue
        out.append({header[k]: v for k, v in cells.items() if k in header})
    return out


def eras_date(v):
    """The workbook mixes Excel serial days, m/d/yyyy text and '2026-07-02-13:46' text."""
    if not v:
        return None
    if re.fullmatch(r"\d+(\.\d+)?", v):
        return (datetime.date(1899, 12, 30) + datetime.timedelta(days=int(float(v)))).isoformat()
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", v)
    if m:
        return f"{m[3]}-{int(m[1]):02d}-{int(m[2]):02d}"
    return v[:10]


def load_eras(refresh=False):
    """ERAS requests normalized to queue API field names, plus the fetch time and source URL."""
    stamp = lambda: time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(ERAS_CACHE)))
    fresh = os.path.exists(ERAS_CACHE) and time.time() - os.path.getmtime(ERAS_CACHE) < MAX_AGE_HOURS * 3600
    url = ERAS_FALLBACK
    if fresh and not refresh:
        with open(ERAS_CACHE, "rb") as f:
            data = f.read()
    else:
        try:
            # The workbook's document number changes when MISO re-posts it; take the live link.
            try:
                m = re.search(r'https://cdn\.misoenergy\.org/ERAS%20Interconnection%20Requests\d+\.xlsx',
                              fetch(ERAS_PAGE, 60).decode("utf-8", "replace"))
                url = m.group() if m else ERAS_FALLBACK
            except OSError:
                pass
            data = fetch(url)
            read_xlsx(data)
        except (OSError, ValueError, KeyError, zipfile.BadZipFile, ET.ParseError) as e:
            if not os.path.exists(ERAS_CACHE):
                raise OSError(str(e))
            print(f"warning: ERAS refresh failed ({e}); using cached copy", file=sys.stderr)
            with open(ERAS_CACHE, "rb") as f:
                data = f.read()
        else:
            os.makedirs(os.path.dirname(ERAS_CACHE), exist_ok=True)
            with open(ERAS_CACHE + ".part", "wb") as f:
                f.write(data)
            os.replace(ERAS_CACHE + ".part", ERAS_CACHE)
    rows = read_xlsx(data)
    if not rows or "POI Name" not in {k.strip() for k in rows[0]}:
        raise ValueError("ERAS workbook does not have the expected columns")
    out = []
    for r in rows:
        x = {ERAS_FIELDS[k.strip()]: v for k, v in r.items() if k.strip() in ERAS_FIELDS}
        if not any(x.values()):
            continue
        for k in ("queueDate", "withdrawnDate", "inService"):
            x[k] = eras_date(x.get(k))
        for k in ("summerNetMW", "nrisMW"):
            try:
                x[k] = float(x.get(k)) if x.get(k) else None
            except ValueError:
                x[k] = None
        x["projectNumber"] = x.get("projectNumber") or f"app {x.get('applicationId')}"
        out.append(x)
    return out, stamp(), url


def norm_place(s):
    """'St. Charles Parish', 'Saint Charles' and 'st charles' compare equal, as do 'De Soto' and 'DeSoto'."""
    s = re.sub(r"\s+(parish|county)$", "", (s or "").strip().lower()).replace("saint ", "st ")
    return re.sub(r"[\s.]", "", s)


def norm_owner(s):
    """'ENTERGY LOUISIANA, LLC ELTO' and 'ENTERGY LOUISIANA, LLC' are one owner."""
    s = re.sub(r"[.,]", "", (s or "").upper())
    s = re.sub(r"\b(LLC|INC|CORP|CO|COMPANY)\b.*$", "", s)
    return re.sub(r"\s+", " ", s).strip()


def row(x, tag=None):
    r = {k: x.get(k) for k in ("projectNumber", "applicationStatus", "fuelType", "facilityType", "summerNetMW",
                               "winterNetMW", "state", "county", "poiName", "transmissionOwner", "studyCycle",
                               "studyGroup", "studyPhase", "svcType", "postGIAStatus")}
    for k in DATES:
        r[k] = (x.get(k) or "")[:10] or None
    if tag:
        r["note"] = tag
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state", help="two-letter state, e.g. LA")
    ap.add_argument("--parish", help="parish or county name; 'Parish'/'County' suffix optional")
    ap.add_argument("--poi", help="substring of the point-of-interconnection (substation) name")
    ap.add_argument("--fuel", help="substring of fuel type: gas, solar, battery, wind, nuclear ...")
    ap.add_argument("--status", help="substring of status: active, withdrawn, done ...")
    ap.add_argument("--owner", help="substring of transmission owner (ERAS: also interconnection customer)")
    ap.add_argument("--project", help="project number, e.g. J3871")
    ap.add_argument("--no-eras", action="store_true", help="skip the ERAS fast-track request list")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    try:
        data, as_of = load(a.refresh)
    except (OSError, ValueError) as e:
        print(f"SOURCE FAILED: MISO queue not read ({e}). Nothing was checked.", file=sys.stderr)
        sys.exit(2)

    def keep(x, located=True):
        if a.project and (x.get("projectNumber") or "").upper() != a.project.upper():
            return False
        if located and a.state and (x.get("state") or "").upper() != a.state.upper():
            return False
        if located and a.parish and norm_place(x.get("county")) != norm_place(a.parish):
            return False
        for flt, key in ((a.poi, "poiName"), (a.fuel, "fuelType"), (a.status, "applicationStatus"),
                         (a.owner, "transmissionOwner")):
            hay = (x.get(key) or "") + (" " + (x.get("customer") or "") if key == "transmissionOwner" else "")
            if flt and flt.lower() not in hay.lower():
                return False
        return True

    hits = [row(x) for x in data if keep(x)]
    unlocated = []
    if a.state or a.parish:
        state = a.state.upper() if a.state else None
        served = {norm_owner(x.get("transmissionOwner")) for x in data
                  if (not state or (x.get("state") or "").upper() == state)
                  and (not a.parish or norm_place(x.get("county")) == norm_place(a.parish))} - {""}
        unlocated = [row(x, "location not published; transmission owner serves this area")
                     for x in data if not x.get("state") and not x.get("county")
                     and norm_owner(x.get("transmissionOwner")) in served and keep(x, located=False)]

    eras, eras_meta = [], None
    if not a.no_eras:
        try:
            eras_rows, eras_as_of, eras_url = load_eras(a.refresh)
            eras = [x for x in eras_rows if keep(x)]
            eras_meta = {"source": eras_url, "as_of": eras_as_of, "records": len(eras_rows)}
        except (OSError, ValueError, KeyError, zipfile.BadZipFile, ET.ParseError) as e:
            eras_meta = {"source_error": str(e)}

    no_history = bool(a.parish) and not any(
        norm_place(x.get("county")) == norm_place(a.parish)
        and (not a.state or (x.get("state") or "").upper() == a.state.upper()) for x in data)
    result = {"source": URL, "queue_as_of": as_of, "records_in_queue": len(data),
              "filters": {k: v for k, v in vars(a).items() if v and k not in ("json", "refresh")},
              "matches": hits, "location_not_published": unlocated,
              "parish_has_no_miso_history": no_history, "eras": eras_meta, "eras_matches": eras}
    if a.json:
        json.dump(result, sys.stdout, indent=2)
        print()
        return

    print(f"MISO interconnection queue, {len(data)} requests, fetched {as_of}. Filters: {result['filters'] or 'none'}")
    for label, group in (("MATCHES", hits), ("LOCATION NOT PUBLISHED (possible matches)", unlocated)):
        if not group:
            if label == "MATCHES" and no_history:
                print(f"\nNo MISO queue request has ever listed {a.parish}. The parish may lie outside MISO: "
                      "SWEPCO's northwest Louisiana territory is in SPP, whose queue this script does not read.")
            elif label == "MATCHES":
                print("\nNo request matches these filters.")
            continue
        mw = collections.defaultdict(float)
        for r in group:
            mw[r["applicationStatus"]] += r["summerNetMW"] or 0
        print(f"\n== {label}: {len(group)} | summer MW by status: "
              + ", ".join(f"{k} {v:,.0f}" for k, v in sorted(mw.items())))
        for r in sorted(group, key=lambda r: r["queueDate"] or "", reverse=True):
            print(f"{r['projectNumber']:<7} {r['applicationStatus']:<26} {r['fuelType'] or '?':<9} "
                  f"{(r['summerNetMW'] or 0):>7,.1f} MW  {r['county'] or '-'}, {r['state'] or '-'}"
                  f"  POI {r['poiName'] or '-'}")
            print(f"        {r['facilityType'] or '-'} | {r['transmissionOwner']} | {r['studyCycle'] or '-'} "
                  f"{r['studyPhase'] or ''} | queued {r['queueDate']} | in-service {r['inService']}"
                  + (f" | withdrawn {r['withdrawnDate']}" if r["withdrawnDate"] else "")
                  + (f" | done {r['doneDate']}" if r["doneDate"] else ""))
    if a.no_eras:
        print("\nERAS not checked (--no-eras).")
    elif "source_error" in eras_meta:
        print(f"\nERAS NOT CHECKED: the ERAS workbook could not be read ({eras_meta['source_error']}). "
              f"Absence of ERAS matches is unknown, not none.")
    else:
        print(f"\n== ERAS (EXPEDITED) REQUESTS: {len(eras)} of {eras_meta['records']} | workbook fetched "
              f"{eras_meta['as_of']} from {eras_meta['source']}")
        if not eras:
            print("No ERAS request matches these filters.")
        for x in sorted(eras, key=lambda x: x.get("queueDate") or "", reverse=True):
            print(f"{x['projectNumber']:<10} {x.get('applicationStatus') or '?':<10} {x.get('fuelType') or '?':<9} "
                  f"{(x.get('summerNetMW') or 0):>7,.1f} MW  {x.get('county') or '-'}, {x.get('state') or '-'}"
                  f"  POI {x.get('poiName') or '-'}")
            print(f"           {x.get('customer') or '-'} | {x.get('studyCycle') or '-'} | GIA {x.get('giaStatus') or '-'}"
                  f" | NRIS {x.get('nrisMW') or '-'} MW | need {x.get('needMW') or '-'} MW | submitted "
                  f"{x.get('queueDate')} | in-service {x.get('inService')}"
                  + (f" | withdrawn {x['withdrawnDate']}" if x.get("withdrawnDate") else ""))
            if x.get("summary"):
                summary = re.sub(r"\s+", " ", x["summary"])
                print(f"           \"{summary[:400]}{'...' if len(summary) > 400 else ''}\"")
    print("\nA withdrawn request is not proof a project was cancelled: developers re-file under new numbers, "
          "move to ERAS (E-numbers, listed above), or keep interconnection rights through MISO's "
          "replacement-generator process at a retiring unit's site, which neither list shows.")


if __name__ == "__main__":
    main()
