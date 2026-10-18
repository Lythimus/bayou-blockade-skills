#!/usr/bin/env python3
"""LED FastLane public report: ITEP, Quality Jobs, Enterprise Zone and Restoration Tax Abatement.

  search   TERMS [--program ITE,QJ,EZ,RTA] [--parish P] [--report project|advance|application]
                 [--status S] [--approved-from D --approved-to D] [--csv FILE] [--yes]
  project  ID
  compare  TERMS_OR_IDS... [--program ..] [--parish ..] [--yes]

Uses the anonymous DataTables endpoint behind FastLane NextGen's public report page. Records
are 10-70 KB of nested JSON that also hold contact names, emails, phones and signatures, so
output is built from an allowlist of fields; nothing else from a record is ever printed.

Every record carries every program's sub-blocks filled with defaults (an ITEP record has a
QJ "hasCompanyComplied: false"; migrated records carry 0 payroll and 0001-01-01 dates). Only
the block for the record's own program is read, and default-looking values in an unpopulated
block are reported as None ("not reported"), never as 0 or False.
"""
import argparse
import csv
import json
import re
import sys
import urllib.error

import incentive_common as c

API = "https://api.fastlaneng.louisianaeconomicdevelopment.com/api/report/publicReport/datatables/list"
PUBLIC_PAGE = "https://fastlaneng.louisianaeconomicdevelopment.com/public/reports"
REPORTS = {"project": "project", "advance": "advance", "application": "projectApplication"}
PAGE = 100
GUARD_RECORDS = 500
KB_PER_RECORD = 35
ID_RE = re.compile(r"^\d{8}(?:-[A-Z]{1,3})*-(ITE|QJ|EZ|RTA)$", re.I)


def fail(msg, code=2):
    print(msg, file=sys.stderr)
    sys.exit(code)


def body(a, terms, start, length):
    b = {"draw": 1, "start": start, "length": length, "search": {"value": terms},
         "reportType": REPORTS[a.report]}
    if a.program:
        b["incentivePrograms"] = [p.strip().upper() for p in a.program.split(",")]
    if a.parish:
        b["parishes"] = [p.strip() for p in a.parish.split(",")]
    if a.status:
        b["projectStatuses"] = [s.strip() for s in a.status.split(",")]
    if getattr(a, "approved_from", None) or getattr(a, "approved_to", None):
        lo = (a.approved_from.isoformat() if a.approved_from else "1990-01-01") + "T00:00:00.000Z"
        hi = (a.approved_to.isoformat() if a.approved_to else "2100-01-01") + "T23:59:59.000Z"
        b["boardApprovalDateRange"] = [lo, hi]
    return b


def query(a, terms):
    """All matching raw records, after a count-first size guard."""
    try:
        # length 0 makes the API return every match, so the count probe asks for one.
        head = c.post_json(API, body(a, terms, 0, 1))
    except (urllib.error.URLError, OSError, ValueError) as e:
        fail("FastLane query failed: %s" % e)
    n = head.get("recordsFiltered", 0)
    est = n * KB_PER_RECORD / 1000
    msg = "FastLane: %d %s record(s) match %r (~%.0f MB to fetch)" % (n, a.report, terms, est)
    if n > GUARD_RECORDS and not a.yes:
        fail(msg + " -- over the %d-record limit; add --program/--parish/--approved-from or rerun with --yes"
             % GUARD_RECORDS, 3)
    print(msg, file=sys.stderr)
    out = list(head.get("data", []))
    start = len(out)
    while start < n:
        try:
            page = c.post_json(API, body(a, terms, start, PAGE))
        except (urllib.error.URLError, OSError, ValueError) as e:
            fail("FastLane page at %d failed: %s" % (start, e))
        data = page.get("data", [])
        if not data:
            break
        out.extend(data)
        start += len(data)
    seen, uniq = set(), []
    for r in out:
        key = r.get("id") or (r.get("projectInfo") or {}).get("projectId")
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    return uniq


# --- allowlisted extraction ----------------------------------------------

def g(o, path, default=None):
    for k in path.split("."):
        if not isinstance(o, dict) or k not in o:
            return default
        o = o[k]
    return o


def date(s):
    if not s or str(s).startswith("0001"):
        return None
    return str(s)[:10]


def migrated(form):
    return any(s.get("creator") == "migrator" for s in (form or {}).get("statuses", []) or [])


def populated(form):
    """True when a form was actually filed, not just a default-filled placeholder."""
    return bool(form) and bool(date(form.get("receivedDate")) or form.get("statuses"))


def num(v, form, allow_zero=True):
    """A reported number, or None when the value is a default in a migrated or empty form."""
    if v is None:
        return None
    if v == 0 and (not allow_zero or migrated(form) or not populated(form)):
        return None
    return v


def main_form(r):
    for key in ("application", "projectApplication", "advance"):
        if r.get(key):
            return key, r[key]
    return None, {}


def summary(r):
    info = r.get("projectInfo") or {}
    program = (info.get("incentiveProgram") or "").upper()
    kind, form = main_form(r)
    rules = info.get("legislation")
    est_new_jobs = num(g(form, "estimatedJobs.new"), form)
    if est_new_jobs is None and kind == "projectApplication":
        # 2025-rules applications carry no jobs section; zero there is by design.
        est_new_jobs = None
    # Each resubmission appends a recalculated fee entry, so the last nonzero one is current.
    benefit = next((f["estimatedBenefits"] for f in reversed(form.get("fees", []) or [])
                    if f.get("estimatedBenefits")), None)
    meetings = sorted({date(m.get("date")) for k in ("applicationBoardMeetings", "projectApplicationBoardMeetings")
                       for m in r.get(k, []) or [] if date(m.get("date"))})
    renewal_meetings = sorted({date(m.get("date")) for m in r.get("renewalBoardMeetings", []) or [] if date(m.get("date"))})
    log = r.get("projectStatusLog") or {}
    return {
        "id": info.get("projectId"),
        "company": info.get("companyName"),
        "project_name": info.get("projectName"),
        "program": program,
        "rules": rules,
        "parish": g(info, "location.parish"),
        "city": g(info, "location.address.city"),
        "confidential": info.get("isConfidential"),
        "mega_project": info.get("isMegaProject"),
        "status": log.get("status"),
        "status_date": date(log.get("statusDate")),
        "form": kind,
        "received": date(form.get("receivedDate")),
        "board_dates": meetings,
        "renewal_board_dates": renewal_meetings,
        "est_investment": num(g(form, "estimatedInvestments.totalInvestments"), form, allow_zero=False),
        "est_existing_jobs": num(g(form, "estimatedJobs.existing"), form),
        "est_new_jobs": est_new_jobs,
        "est_construction_jobs": num(g(form, "estimatedJobs.construction"), form),
        "est_new_payroll": num(g(form, "estimatedPayroll.new"), form, allow_zero=False),
        "est_benefit": benefit,
        "naics": g(form, "projectDetails.naicsCode"),
        "migrated_record": migrated(form),
    }


def actuals(r, program):
    """Post-award figures from the block that belongs to this record's program only."""
    out = {}
    afc = r.get("afc") or {}
    if populated(afc) and (afc.get("investmentTotal") or 0) > 0:
        out["afc_received"] = date(afc.get("receivedDate"))
        out["afc_investment"] = afc.get("investmentTotal")
        period = [date(afc.get("startDate")), date(afc.get("endDate"))]
        if any(period):
            out["afc_period"] = period
    rnw = r.get("rnw") or {}
    if program == "ITE" and populated(rnw):
        ite = rnw.get("ite") or {}
        if any(ite.get(k) for k in ("priorJobs", "currentJobs", "affidavitInvestmentTotal")):
            out["renewal_received"] = date(rnw.get("receivedDate"))
            out["prior_jobs"] = num(ite.get("priorJobs"), rnw)
            out["current_jobs"] = num(ite.get("currentJobs"), rnw)
            out["new_jobs_reported"] = num(ite.get("newJobs"), rnw)
            out["jobs_reduction_reason"] = ite.get("jobsReductionReason") or None
            out["renewal_affidavit_investment"] = ite.get("affidavitInvestmentTotal")
            out["renewal_application_investment"] = ite.get("applicationInvestmentTotal")
            out["annual_ad_valorem"] = ite.get("annualAdValorem")
            out["annual_ad_valorem_after_depreciation"] = ite.get("annualAdValoremDepreciation")
    if program == "QJ" and populated(rnw):
        qj = rnw.get("qj") or {}
        out["renewal_received"] = date(rnw.get("receivedDate"))
        for k in ("hasCompanyComplied", "hasAllReports", "hasHourlyWageIncreased"):
            # Migrated renewals carry False as a placeholder, not a finding of non-compliance.
            if k in qj and not (qj[k] is False and migrated(rnw)):
                out["qj_" + re.sub(r"(?<!^)([A-Z])", r"_\1", k).lower()] = qj[k]
    if program == "RTA" and populated(afc):
        rd = afc.get("restorationDetails") or {}
        out["rta_actual_jobs"] = g(rd, "actualJobs.totalJobs")
        out["rta_actual_payroll"] = g(rd, "actualPayroll.totalPayroll")
    return out


def detail(r):
    s = summary(r)
    program = s["program"]
    kind, form = main_form(r)
    promised = {k: s[k] for k in ("est_investment", "est_existing_jobs", "est_new_jobs",
                                  "est_construction_jobs", "est_new_payroll", "est_benefit")}
    promised.update({
        "est_existing_payroll": num(g(form, "estimatedPayroll.existing"), form, allow_zero=False),
        "est_construction_payroll": num(g(form, "estimatedPayroll.construction"), form, allow_zero=False),
        "project_type": g(form, "projectDetails.projectType"),
        "project_start": date(g(form, "projectDetails.projectStartDate")),
        "project_end": date(g(form, "projectDetails.projectEndDate")),
        "description": g(form, "projectDetails.projectDescription") or g(form, "projectDetails.projectBenefit"),
        "product": g(form, "ite.productManufactured") if program == "ITE" else None,
        "millage_rate": g(form, "millageRate") or None,
        "annual_ad_valorem_estimate": (g(form, "ite.annualAdValorem") or None) if program == "ITE" else None,
    })
    if program == "QJ":
        sched = [{"year": p.get("year"), "annual_gross_payroll": p.get("annualGrossPayroll"),
                  "cumulative_gross_payroll": p.get("cumulativeGrossPayroll"),
                  "new_direct_jobs": p.get("newDirectJobsCreated")}
                 for p in form.get("grossPayroll", []) or []]
        if sched:
            promised["qj_payroll_schedule_as_filed"] = sched
    if kind == "projectApplication":
        promised["calendar_years"] = g(form, "projectDetails.calendarYears")
        promised["construction_activities"] = g(form, "projectDetails.constructionActivities")
    review = {}
    for k, label in (("localITEPCommitteeContact", "local_itep_committee"),
                     ("revenueDepartment", "revenue_department"), ("workforceComission", "workforce_commission")):
        hist = [{"status": x.get("status"), "date": date(x.get("date"))}
                for x in g(form, "externalReview." + k, []) or []]
        if hist:
            review[label] = hist
    board = [{"status": b.get("status"), "comment": b.get("comment")} for b in form.get("boardStatuses", []) or []]
    dates = {d.get("type"): date(d.get("date")) for d in r.get("projectDates", []) or [] if date(d.get("date"))}
    history = []
    # Signature, payment and resubmission churn hides the milestones.
    clerical = {"Pending", "Pending Signature", "Pending Payment", "Information Required"}
    for key in ("advance", "application", "projectApplication", "afc", "rnw"):
        f = r.get(key) or {}
        for st in f.get("statuses", []) or []:
            if date(st.get("statusDate")) and st.get("status") not in clerical:
                history.append({"form": key, "status": st.get("status"), "date": date(st.get("statusDate"))})
    history.sort(key=lambda h: h["date"])
    history = [h for i, h in enumerate(history)
               if i == 0 or (h["form"], h["status"]) != (history[i - 1]["form"], history[i - 1]["status"])]
    return {"summary": s, "promised": {k: v for k, v in promised.items() if v not in (None, "", [])},
            "actual": actuals(r, program), "external_review": review, "board_actions": board,
            "dates": dates, "status_history": history}


# --- commands ------------------------------------------------------------

def money(v):
    return "" if v is None else "$%s" % format(int(round(v)), ",")


def show(v, key=""):
    if v is None:
        return "not reported"
    if isinstance(v, float) and "rate" not in key:
        return money(v)
    return str(v)


def cmd_search(a):
    rows = [summary(r) for r in query(a, " ".join(a.terms))]
    if a.json:
        json.dump(rows, sys.stdout, indent=1)
        print()
        return
    if a.csv:
        with open(a.csv, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["id"])
            w.writeheader()
            for r in rows:
                w.writerow({k: (";".join(v) if isinstance(v, list) else v) for k, v in r.items()})
        print("wrote %d rows to %s" % (len(rows), a.csv), file=sys.stderr)
    for r in rows:
        print("%-18s %-4s %-14s %-38.38s %-16s %s" % (r["id"], r["program"], r["rules"] or "", r["company"] or "",
                                                       r["parish"] or "", r["status"] or ""))
        print("    received %s  board %s  invest %s  new jobs %s  new payroll %s  est. benefit %s%s" % (
            r["received"] or "-", ",".join(r["board_dates"]) or "-", money(r["est_investment"]) or "-",
            show(r["est_new_jobs"]), money(r["est_new_payroll"]) or "-", money(r["est_benefit"]) or "-",
            "  [migrated record]" if r["migrated_record"] else ""))
    print("%d project(s). Public report: %s" % (len(rows), PUBLIC_PAGE), file=sys.stderr)


def cmd_project(a):
    pid = a.id.upper()
    m = ID_RE.match(pid)
    if not m:
        fail("expected an ID like 20190099-ITE or 20200068-QJ")
    a.program = m.group(1)
    hits = []
    for rep in ("project", "advance"):
        a.report = rep
        hits = [r for r in query(a, pid) if (r.get("projectInfo") or {}).get("projectId", "").upper() == pid]
        if hits:
            break
    if not hits:
        fail("%s not found in the FastLane public report (confidential, withdrawn before migration, or mistyped)" % pid, 1)
    d = detail(hits[0])
    if a.json:
        json.dump(d, sys.stdout, indent=1)
        print()
        return
    s = d["summary"]
    print("%s  %s  (%s, %s)" % (s["id"], s["company"], s["program"], s["rules"]))
    print("  %s, %s parish; status %s (%s)%s" % (s["project_name"] or "", s["parish"], s["status"], s["status_date"],
                                                 "; MIGRATED RECORD: zeros are missing data" if s["migrated_record"] else ""))
    for title, block in (("Promised (as filed)", d["promised"]), ("Actual (as reported by company)", d["actual"])):
        print("\n" + title)
        if not block:
            print("  not reported")
        for k, v in block.items():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                print("  %s:" % k)
                for x in v:
                    print("    " + ", ".join("%s=%s" % (kk, show(vv)) for kk, vv in x.items()))
            elif k == "description" or k == "construction_activities":
                print("  %s: %s" % (k, c.norm(str(v))[:400]))
            else:
                print("  %s: %s" % (k, show(v, k) if not isinstance(v, list) else ", ".join(map(str, v))))
    if d["external_review"]:
        print("\nExternal review")
        for k, hist in d["external_review"].items():
            print("  %s: %s" % (k, "; ".join("%s %s" % (h["status"], h["date"]) for h in hist)))
    print("\nBoard: application %s; renewal %s" % (", ".join(s["board_dates"]) or "-", ", ".join(s["renewal_board_dates"]) or "-"))
    for b in d["board_actions"]:
        print("  %s%s" % (b["status"], (" - " + c.norm(b["comment"])) if b.get("comment") else ""))
    print("\nDates")
    for k, v in sorted(d["dates"].items(), key=lambda kv: kv[1]):
        print("  %s  %s" % (v, k))
    print("\nStatus history")
    for h in d["status_history"]:
        print("  %s  %-12s %s" % (h["date"], h["form"], h["status"]))


SOURCES = {
    "est_existing_jobs": "application.estimatedJobs.existing",
    "est_new_jobs": "application.estimatedJobs.new",
    "prior_jobs": "rnw.ite.priorJobs",
    "current_jobs": "rnw.ite.currentJobs",
    "jobs_delta": "rnw.ite.currentJobs - (estimatedJobs.existing + estimatedJobs.new); a missing est. new counts as 0",
    "est_new_payroll": "application.estimatedPayroll.new",
    "est_investment": "application.estimatedInvestments.totalInvestments",
    "afc_investment": "afc.investmentTotal",
    "jobs_reduction_reason": "rnw.ite.jobsReductionReason",
    "qj_has_company_complied": "rnw.qj.hasCompanyComplied (QJ records only)",
    "rta_actual_jobs": "afc.restorationDetails.actualJobs.totalJobs (RTA records only)",
}


def cmd_compare(a):
    recs = {}
    for t in a.terms:
        m = ID_RE.match(t.upper())
        if m and not a.program:
            a.program = m.group(1)
        for r in query(a, t):
            pid = (r.get("projectInfo") or {}).get("projectId")
            if m and pid and pid.upper() != t.upper():
                continue
            recs[pid] = r
    rows = []
    for pid, r in recs.items():
        s, act = summary(r), actuals(r, (r.get("projectInfo") or {}).get("incentiveProgram", "").upper())
        promised_total = None
        if s["est_existing_jobs"] is not None:
            promised_total = (s["est_existing_jobs"] or 0) + (s["est_new_jobs"] or 0)
        cur = act.get("current_jobs")
        rows.append({
            "id": pid, "company": s["company"], "program": s["program"], "rules": s["rules"],
            "parish": s["parish"], "status": s["status"],
            "est_existing_jobs": s["est_existing_jobs"], "est_new_jobs": s["est_new_jobs"],
            "prior_jobs": act.get("prior_jobs"), "current_jobs": cur,
            "jobs_delta": (cur - promised_total) if (cur is not None and promised_total is not None) else None,
            "est_new_payroll": s["est_new_payroll"], "est_investment": s["est_investment"],
            "afc_investment": act.get("afc_investment"),
            "jobs_reduction_reason": act.get("jobs_reduction_reason"),
            "qj_has_company_complied": act.get("qj_has_company_complied"),
            "rta_actual_jobs": act.get("rta_actual_jobs"),
            "migrated_record": s["migrated_record"],
        })
    rows.sort(key=lambda x: x["id"] or "")
    if a.json:
        json.dump({"rows": rows, "sources": SOURCES}, sys.stdout, indent=1)
        print()
        return
    hdr = "%-18s %-4s %-12s %6s %6s %6s %6s %6s %14s %16s %16s  %s" % (
        "ID", "PROG", "RULES", "EST-EX", "EST-NW", "PRIOR", "CURR", "DELTA", "EST NEW PAY", "EST INVEST", "AFC INVEST", "NOTES")
    print(hdr)
    for x in rows:
        def n(v):
            return "-" if v is None else str(v)
        notes = []
        if x["jobs_reduction_reason"] and x["jobs_reduction_reason"].strip().upper() not in ("N/A", "NA"):
            notes.append("reduction: " + c.norm(x["jobs_reduction_reason"])[:60])
        if x["qj_has_company_complied"] is not None:
            notes.append("QJ complied=%s" % x["qj_has_company_complied"])
        if x["rta_actual_jobs"] is not None:
            notes.append("RTA actual jobs=%s" % x["rta_actual_jobs"])
        if x["migrated_record"]:
            notes.append("migrated")
        print("%-18s %-4s %-12.12s %6s %6s %6s %6s %6s %14s %16s %16s  %s" % (
            x["id"], x["program"], x["rules"] or "", n(x["est_existing_jobs"]), n(x["est_new_jobs"]),
            n(x["prior_jobs"]), n(x["current_jobs"]), n(x["jobs_delta"]), money(x["est_new_payroll"]) or "-",
            money(x["est_investment"]) or "-", money(x["afc_investment"]) or "-", "; ".join(notes)))
    print("\n'-' = not reported. Sources:")
    for k, v in SOURCES.items():
        print("  %-24s %s" % (k, v))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--json", action="store_true")
    p.add_argument("--yes", action="store_true", help="allow pulls over the record guard")
    sp = p.add_subparsers(dest="cmd", required=True)

    def filters(q, report=True):
        q.add_argument("--program", help="ITE,QJ,EZ,RTA")
        q.add_argument("--parish", help="e.g. 'St. Charles' (comma-separate several)")
        q.add_argument("--status", help="FastLane status text, e.g. 'Contract Active'")
        if report:
            q.add_argument("--report", choices=sorted(REPORTS), default="project")
        q.add_argument("--approved-from", type=c.arg_date)
        q.add_argument("--approved-to", type=c.arg_date)

    q = sp.add_parser("search")
    q.add_argument("terms", nargs="*", default=[])
    filters(q)
    q.add_argument("--csv")
    q.set_defaults(fn=cmd_search)

    q = sp.add_parser("project")
    q.add_argument("id")
    q.set_defaults(fn=cmd_project, parish=None, status=None, report="project", approved_from=None, approved_to=None)

    q = sp.add_parser("compare")
    q.add_argument("terms", nargs="+")
    filters(q, report=False)
    q.set_defaults(fn=cmd_compare, report="project")

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
