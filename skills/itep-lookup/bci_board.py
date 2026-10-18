#!/usr/bin/env python3
"""Louisiana Board of Commerce & Industry (BCI) agendas, approval lists and minutes.

  meetings  [--year Y] [--kind agenda,minutes,approvals,...]
  search    TERMS... [--from D --to D] [--program QJ,EZ,RTA,ITE] [--yes]
  renewals  [--noncompliant] [--from D --to D] [--yes]
  noncompliance [--from D --to D] [--yes]
  minutes   DATE --grep TERMS... [--context N]

Agendas carry one table per program and rule set (QJ, RTA, EZ, ITEP Pre-EO/2017/2018/
2024 Emergency/2025), plus special-request pages (cancellations, terminations, opt-outs).
ITEP renewal tables give jobs at the first year of exemption against current jobs, and a
per-year compliance code (CP/NC/NCL/N/A); 2018-rules non-compliance tables give required
against actual jobs and payroll for a reporting year, with each local body's recommendation
(DB/DP/RT/RP/RTP/TNA/TE/NR). Minutes are condensed court-reporter transcripts.

Every row carries the agenda PDF URL so findings can be cited.
"""
import argparse
import csv
import datetime
import json
import re
import statistics
import sys
import urllib.error

import incentive_common as c

PAGE = "https://www.opportunitylouisiana.gov/about-led/advisory-boards/louisiana-board-of-commerce-and-industry"
SUB = "bci"

APP_RE = re.compile(r"\b(\d{8}(?:-[A-Z]{1,3})*)\b")
ROW_RE = re.compile(r"^\s{0,6}(\d{8}(?:-[A-Z]{1,3})*)\s+(\S.*)$")
CODES = {"CP", "NC", "NCL", "N/A"}
LIC = {"RE", "RE*", "NR", "DA"}

# Section title fragments, checked in order; the first match names the table that follows.
SECTIONS = [
    (r"Quality Jobs Applications", "QJ", "QJ application"),
    (r"Quality Jobs Renewals", "QJ", "QJ renewal"),
    (r"Quality Jobs Special Requests", "QJ", "QJ special request"),
    (r"Restoration Tax Abatement Renewals", "RTA", "RTA renewal"),
    (r"RESTORATION TAX ABATEMENT", "RTA", "RTA application"),
    (r"Enterprise Zone Applications", "EZ", "EZ application"),
    (r"Industrial Tax Exemption.*\(2025 Rules\) Project Applications", "ITE", "ITE 2025 rules project application"),
    (r"Industrial Tax Exemption.*\(2024 Emergency Rules\) Applications", "ITE", "ITE 2024 emergency rules application"),
    (r"Industrial Tax Exemption.*Rules\) Contracts|Non-Compliance Summary", "ITE", "ITE non-compliance"),
    (r"Industrial Tax Exemption.*Late Renewal", "ITE", "ITE late renewal"),
    (r"Industrial Tax Exemption.*Renewal", "ITE", "ITE renewal"),
    (r"Industrial Tax Exemption.*Applications", "ITE", "ITE application"),
]
SPECIAL = [
    (r"Contract Termination Request", "contract termination"),
    (r"Contracts? for Cancellation|CANCELLATION OF CONTRACT", "contract cancellation"),
    (r"CHANGE IN NAME ONLY", "name change"),
    (r"CHANGE (?:IN|OF PROJECT PHYSICAL) LOCATION", "location change"),
    (r"PARTIAL TRANSFER", "partial transfer"),
    (r"TRANSFER OF TAX EXEMPTION", "transfer"),
    (r"Opt Out", "opt out of jobs/payroll/compliance"),
]
PROGRAM_BANNER = [
    (r"^\s*ENTERPRISE ZONE PROGRAM", "EZ"),
    (r"^\s*INDUSTRIAL TAX EXEMPTION PROGRAM", "ITE"),
    (r"^\s*QUALITY JOBS PROGRAM", "QJ"),
    (r"^\s*RESTORATION TAX ABATEMENT PROGRAM", "RTA"),
]

JOBS4 = ["new_jobs", "new_salaries", "construction_jobs", "construction_salaries"]
LGE = ["lge_parish", "lge_school_board", "lge_sheriff", "lge_municipality"]


def columns(section, header, twenty=None):
    """(column names, how many are required) for a table, read from its header block.

    The same section changes columns between meetings (the 20%-collected column was added
    to 2018-rules tables in 2026, 2024-emergency tables carry no jobs), so the header text
    decides. Rows that do not fit keep their raw text and an unlabelled value list.
    """
    h = " ".join(header.upper().split())
    if twenty is None:
        twenty = "20%" in h
    twenty = ["taxes_collected_20pct_first_year"] if twenty else []
    if section == "QJ application":
        cols = ["investment", "sales_use_rebate_10yr", "payroll_rebate_10yr"] + JOBS4
    elif section == "RTA application":
        cols = ["investment", "first_year_exemption"] + JOBS4
    elif section == "EZ application":
        cols = ["investment", "state_rebate", "local_rebate", "itc", "new_jobs", "salaries_5yr",
                "construction_jobs", "construction_salaries"]
    elif section in ("ITE application", "ITE 2024 emergency rules application", "ITE 2025 rules project application"):
        cols = ["investment", "exemption_first_year"] + twenty
        if "NEW PERMANENT" in h:
            cols += JOBS4
        if re.search(r"\bLIC\b|LOCAL ITEP", h):
            cols += ["lic_decision"]
        need = len(cols)
        return cols + ["naics", "late"], need
    elif section == "ITE non-compliance":
        cols = ["investment", "exemption_first_year"] + twenty + [
            "reporting_period", "required_jobs", "required_salaries", "actual_jobs", "actual_salaries"]
        return cols + LGE + ["compliance_due_date", "compliance_received_date"], len(cols)
    elif section in ("ITE renewal", "ITE late renewal"):
        cols = ["investment", "first_year_renewal_exemption"] + twenty + [
            "jobs_first_year_of_exemption", "jobs_current", "*compliance"]
        need = len(cols) - 1
        cols += ["naics"]
        if section == "ITE late renewal":
            cols += ["initial_contract_expiration", "late_renewal_request"]
        return cols, need
    else:
        return None, 0
    return cols, len(cols)


def fail(msg, code=2):
    print(msg, file=sys.stderr)
    sys.exit(code)


def listing(cache):
    try:
        page = c.fetch_text(PAGE)
    except (urllib.error.URLError, OSError) as e:
        fail("BCI page fetch failed: %s" % e)
    out = []
    for href, text in c.links(page, PAGE):
        if not href.lower().endswith(".pdf"):
            continue
        m = re.match(r"\s*(\d{1,2})\.(\d{1,2})\.(\d{2,4})", text)
        d = None
        if m:
            y = int(m.group(3))
            d = c._mk(y + 2000 if y < 100 else y, int(m.group(1)), int(m.group(2)))
        d = d or c.parse_date(href.rsplit("/", 1)[-1].replace("-", " "))
        low = text.lower()
        if "rules committee" in low or "hearing" in low:
            kind = "rules-committee"
        elif "approval" in low:
            kind = "approvals"
        elif "minutes" in low:
            kind = "minutes"
        elif "agenda" in low:
            kind = "agenda"
        else:
            kind = "other"
        # LED posts International Commerce board minutes under the same heading.
        if kind == "minutes" and re.search(r"LABIC|International", href, re.I):
            kind = "other"
        out.append({"date": d.isoformat() if d else None, "kind": kind, "title": text, "url": href})
    seen, uniq = set(), []
    for r in out:
        if r["url"] in seen or not r["date"]:
            continue
        seen.add(r["url"])
        uniq.append(r)
    return sorted(uniq, key=lambda r: r["date"], reverse=True)


def in_range(r, a):
    d = datetime.date.fromisoformat(r["date"])
    return (not a.date_from or d >= a.date_from) and (not a.date_to or d <= a.date_to)


def parse_agenda(text, url, meeting):
    rows = []
    section, program, special = None, None, None
    paragraph, header, since_row = [], [], False

    def flush():
        if special and paragraph:
            body = c.norm(" ".join(paragraph))
            apps = list(dict.fromkeys(APP_RE.findall(body)))
            if apps:
                rows.append({"meeting": meeting, "program": program, "section": special,
                             "application": apps[0], "applications": apps, "text": body, "url": url})
        paragraph.clear()

    for line in text.replace("\f", "\n").split("\n"):
        hit = False
        for pat, prog, name in SECTIONS:
            if re.search(pat, line):
                flush()
                # A two-line title matches twice; keep the header gathered since the first.
                # Pre-EO and 2018 application tables share a name, so a parsed row also resets.
                if name != section or since_row:
                    header, since_row = [], False
                section, program, special, hit = name, prog, None, True
                break
        if not hit:
            for pat, prog in PROGRAM_BANNER:
                if re.search(pat, line, re.I):
                    flush()
                    program, section, special = prog, None, None
                    hit = True
                    break
        if not hit:
            for pat, name in SPECIAL:
                if re.search(pat, line):
                    flush()
                    special, section, hit = name, None, True
                    break
        if hit:
            continue
        if special:
            if not line.strip():
                flush()
            elif not re.match(r"\s*(Contract|Project No|COMPANY|FORMER|The following|Staff requests|agreements for|Number\s*$)", line.strip(), re.I) \
                    or APP_RE.search(line):
                paragraph.append(line.strip())
            continue
        m = ROW_RE.match(line)
        if not section:
            continue
        if not m:
            if not re.match(r"\s*TOTALS?\b", line):
                header.append(line)
            continue
        since_row = True
        rows.append(table_row(m, section, program, meeting, url, "\n".join(header[-40:])))
    flush()
    return rows


def table_row(m, section, program, meeting, url, header):
    app, rest = m.group(1), m.group(2)
    cells = re.split(r"\s{2,}", rest.strip())
    company = c.norm(cells[0]) if cells else ""
    parish = c.norm(cells[1]) if len(cells) > 1 else ""
    tail = " ".join(cells[2:])
    # "214 *" and "0*" mark jobs shared across projects at one site and "**" a footnote,
    # both kept on the number; a standalone "***" means no annual compliance report was filed.
    tail = re.sub(r"(\d)\s+(\*{1,2})(?!\*)", r"\1\2", tail).replace("Not Received", "Not-Received")
    vals = tail.split()
    row = {"meeting": meeting, "program": program, "section": section, "application": app,
           "company": company, "parish": parish, "url": url, "raw": c.norm(m.group(0))}
    renewal = "renewal" in section
    # Only renewal tables carry yearly compliance codes; elsewhere N/A is an LGE answer.
    codes = [v for v in vals if v in CODES] if renewal else []
    row["compliance"] = codes
    rest_vals = [v for v in vals if v not in CODES] if renewal else vals
    cols, _ = columns(section, header)
    if not cols:
        if vals:
            row["values"] = vals
        return row
    has20 = "taxes_collected_20pct_first_year" in cols
    # Some agendas drop the 20%-collected column from one table but not the next, so a row
    # that fails type checks is retried with the other layout before giving up.
    for twenty in (has20, not has20):
        cols, need = columns(section, header, twenty)
        named = [col for col in cols if col != "*compliance"]
        required = len([col for col in cols[:need] if col != "*compliance"])
        if required <= len(rest_vals) <= len(named) and all(fits(k, v) for k, v in zip(named, rest_vals)):
            row.update(zip(named, rest_vals))
            # In the LATE column "**" cites the late-filing penalty under section 503.
            if row.get("naics", "").endswith("**"):
                row["naics"], row["late"] = row["naics"].rstrip("*"), "** (filed late)"
            return row
    row["values"] = vals
    row["unlabelled"] = True
    return row


MONEY = ("investment", "exemption", "taxes", "rebate", "itc", "salar")


def fits(col, v):
    if v == "***":
        return col.startswith(("actual_",))
    if "jobs" in col:
        return re.fullmatch(r"\d[\d,]*\*{0,2}", v) is not None
    if any(k in col for k in MONEY):
        return v.startswith("$")
    if col in ("naics",):
        return re.fullmatch(r"\d{4,6}\*{0,2}", v) is not None
    if col == "reporting_period":
        return re.fullmatch(r"(19|20)\d\d", v) is not None
    if col == "lic_decision":
        return v in LIC
    return True


def load_agendas(a, kinds=("agenda",)):
    rows = [r for r in listing(a.cache) if r["kind"] in kinds and in_range(r, a)]
    if not rows:
        fail("no %s PDFs in range" % "/".join(kinds), 1)
    try:
        c.guard([r["url"] for r in rows], a.cache, SUB, a.yes)
    except c.GuardStop as e:
        fail(str(e), 3)
    out = []
    for r in rows:
        try:
            path = c.get_pdf(r["url"], a.cache, SUB)
        except (urllib.error.URLError, OSError) as e:
            print("skip %s: %s" % (r["url"], e), file=sys.stderr)
            continue
        out.append((r, c.pdf_text(path)))
    return out


def all_rows(a):
    rows = []
    for meta, text in load_agendas(a):
        rows.extend(parse_agenda(text, meta["url"], meta["date"]))
    if a.program:
        progs = {p.strip().upper() for p in a.program.split(",")}
        rows = [r for r in rows if r.get("program") in progs]
    return rows


def emit(rows, a, fields):
    if a.json:
        json.dump(rows, sys.stdout, indent=1, default=str)
        print()
        return
    if getattr(a, "csv", None):
        with open(a.csv, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=sorted({k for r in rows for k in r}), extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow({k: (";".join(v) if isinstance(v, list) else v) for k, v in r.items()})
        print("wrote %d rows to %s" % (len(rows), a.csv), file=sys.stderr)
    for r in rows:
        bits = [str(r.get(f, "")) for f in fields]
        extra = {k: v for k, v in r.items() if k not in fields + ["url", "raw", "applications", "text", "program"] and v not in ([], None, "")}
        print(" | ".join(bits))
        if r.get("text"):
            print("    " + r["text"])
        if extra:
            print("    " + "; ".join("%s=%s" % (k, "/".join(v) if isinstance(v, list) else v) for k, v in extra.items()))
        print("    " + r["url"])
    print("%d row(s)" % len(rows), file=sys.stderr)


def cmd_meetings(a):
    rows = listing(a.cache)
    if a.year:
        rows = [r for r in rows if r["date"].startswith(str(a.year))]
    if a.kind:
        kinds = set(a.kind.split(","))
        rows = [r for r in rows if r["kind"] in kinds]
    if a.json:
        json.dump(rows, sys.stdout, indent=1)
        print()
        return
    for r in rows:
        print("%s  %-15s %s\n            %s" % (r["date"], r["kind"], r["title"], r["url"]))


def cmd_search(a):
    terms = [t.lower() for t in a.terms]
    rows = []
    for r in all_rows(a):
        hay = " ".join(str(v) for v in r.values()).lower()
        if all(t in hay for t in terms):
            rows.append(r)
    emit(rows, a, ["meeting", "section", "application", "company", "parish"])


def cmd_noncompliance(a):
    rows = [r for r in all_rows(a) if r.get("section") == "ITE non-compliance"]
    emit(rows, a, ["meeting", "application", "company", "parish", "reporting_period",
                   "required_jobs", "actual_jobs", "required_salaries", "actual_salaries"])


def cmd_renewals(a):
    rows = [r for r in all_rows(a) if "renewal" in (r.get("section") or "") and r.get("program") == "ITE"]
    if a.noncompliant:
        rows = [r for r in rows if {"NC", "NCL"} & set(r.get("compliance", []))]
    emit(rows, a, ["meeting", "section", "application", "company", "parish",
                   "jobs_first_year_of_exemption", "jobs_current"])


# --- minutes -------------------------------------------------------------

FOOT = re.compile(r"^\s*Page (\d+)(?:\s+Page (\d+))?\s*$")
LN = re.compile(r"^\s{0,3}(\d{1,2})(?: |$)")


def _split(line, n, hint):
    """Split a two-column line whose columns both start with line number n.

    The right column's number is usually set off by 2+ spaces; when the left text runs
    long there is only one, so fall back to the occurrence nearest the block's usual column.
    """
    lead = LN.match(line).end()
    cands = [m for m in re.finditer(r"(?<=\s)%d(?= |$)" % n, line) if m.start() >= lead]
    if not cands:
        return line[lead:].strip(), None

    def score(m):
        gap = m.start() - len(line[:m.start()].rstrip())
        return (0 if gap >= 2 else 1, abs(m.start() - hint) if hint else 0)
    m = min(cands, key=score)
    return line[lead:m.start()].strip(), line[m.end():].strip()


def parse_minutes(text):
    """{transcript page: [(line no, text)]}, plus a list of pages that did not split cleanly.

    Each PDF sheet holds four transcript pages, two per column, and every block of 25
    numbered lines ends with a 'Page A   Page B' footer naming the left and right page.
    """
    pages, irregular = {}, []
    block, last, sheet = [], 0, 1
    for raw in text.split("\n"):
        sheet += raw.count("\f")
        raw = raw.replace("\f", "")
        f = FOOT.match(raw)
        if f:
            a_pg = int(f.group(1))
            b_pg = int(f.group(2)) if f.group(2) else None
            # The word index after the certificate restarts at Page 1.
            if a_pg < last - 4:
                break
            last = b_pg or a_pg
            nums = [int(LN.match(l).group(1)) for l in block]
            hints = [m.end() for l, n in zip(block, nums)
                     for m in re.finditer(r"\s{2,}%d(?= |$)" % n, l) if m.start() > 10]
            hint = statistics.median(hints) if hints else None
            split = [(n,) + _split(l, n, hint) for l, n in zip(block, nums)] if b_pg else \
                    [(n, l[LN.match(l).end():].strip(), None) for l, n in zip(block, nums)]
            if b_pg and sum(1 for s in split if s[2] is not None) < 0.8 * max(len(split), 1):
                irregular.append({"pages": [a_pg, b_pg], "pdf_page": sheet})
                pages.setdefault(a_pg, []).extend((n, c.norm(l)) for n, l in
                                                  ((n, block[i][LN.match(block[i]).end():]) for i, n in enumerate(nums)))
            else:
                for n, left, right in split:
                    pages.setdefault(a_pg, []).append((n, c.norm(left)))
                    if b_pg and right is not None:
                        pages.setdefault(b_pg, []).append((n, c.norm(right)))
            block = []
            continue
        if LN.match(raw) and raw.strip():
            block.append(raw.rstrip())
    return pages, irregular


def cmd_minutes(a):
    try:
        day = c.arg_date(a.date)
    except ValueError as e:
        fail(str(e))
    cands = [r for r in listing(a.cache) if r["kind"] == "minutes" and r["date"] == day.isoformat()]
    if not cands:
        near = [r["date"] for r in listing(a.cache) if r["kind"] == "minutes"][:8]
        fail("no minutes listed for %s; recent minutes: %s" % (day, ", ".join(near)), 1)
    meta = cands[0]
    try:
        c.guard([meta["url"]], a.cache, SUB, a.yes)
        path = c.get_pdf(meta["url"], a.cache, SUB)
    except c.GuardStop as e:
        fail(str(e), 3)
    except (urllib.error.URLError, OSError) as e:
        fail("download failed: %s" % e)
    pages, irregular = parse_minutes(c.pdf_text(path))
    if not pages:
        fail("no line-numbered transcript found in %s (older minutes are often a summary, not a transcript; read it directly)" % meta["url"], 1)
    flat = [(p, n, t) for p in sorted(pages) for n, t in pages[p]]
    terms = [t.lower() for t in a.grep]
    hits = [i for i, (_, _, t) in enumerate(flat) if any(x in t.lower() for x in terms)]
    spans = []
    for i in hits:
        lo, hi = max(0, i - a.context), min(len(flat), i + a.context + 1)
        if spans and lo <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], hi)
        else:
            spans.append([lo, hi])
    out = [{"page": flat[lo][0], "line": flat[lo][1],
            "lines": [{"page": p, "line": n, "text": t} for p, n, t in flat[lo:hi]]} for lo, hi in spans]
    if a.json:
        json.dump({"minutes": meta, "irregular_pages": irregular, "passages": out}, sys.stdout, indent=1)
        print()
        return
    print("%s  %s" % (meta["date"], meta["url"]))
    for ir in irregular:
        print("  note: transcript pages %s on PDF page %d did not split into columns; check the PDF" % (ir["pages"], ir["pdf_page"]))
    for s in out:
        print("\n-- p.%d:%d" % (s["page"], s["line"]))
        for l in s["lines"]:
            print("%3d:%-2d %s" % (l["page"], l["line"], l["text"]))
    print("%d passage(s), %d hit line(s)" % (len(out), len(hits)), file=sys.stderr)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--cache", default=c.DEFAULT_CACHE)
    p.add_argument("--json", action="store_true")
    p.add_argument("--yes", action="store_true", help="allow downloads over the guard limit")
    sp = p.add_subparsers(dest="cmd", required=True)

    def dates(q):
        q.add_argument("--from", dest="date_from", type=c.arg_date)
        q.add_argument("--to", dest="date_to", type=c.arg_date)

    q = sp.add_parser("meetings")
    q.add_argument("--year", type=int)
    q.add_argument("--kind", help="agenda,minutes,approvals,rules-committee,other")
    q.set_defaults(fn=cmd_meetings)

    q = sp.add_parser("search")
    q.add_argument("terms", nargs="+")
    q.add_argument("--program", help="QJ,EZ,RTA,ITE")
    q.add_argument("--csv")
    dates(q)
    q.set_defaults(fn=cmd_search)

    q = sp.add_parser("renewals")
    q.add_argument("--noncompliant", action="store_true")
    q.add_argument("--csv")
    q.set_defaults(fn=cmd_renewals, program=None)
    dates(q)

    q = sp.add_parser("noncompliance", help="2018-rules ITEP contracts that missed Exhibit A jobs/payroll")
    q.add_argument("--csv")
    q.set_defaults(fn=cmd_noncompliance, program=None)
    dates(q)

    q = sp.add_parser("minutes")
    q.add_argument("date")
    q.add_argument("--grep", nargs="+", required=True)
    q.add_argument("--context", type=int, default=6)
    q.set_defaults(fn=cmd_minutes)

    a = p.parse_args()
    for k in ("date_from", "date_to"):
        if not hasattr(a, k):
            setattr(a, k, None)
    # Without a range, search the last year of agendas so a first run stays small.
    if a.cmd in ("search", "renewals", "noncompliance") and not a.date_from and not a.date_to:
        a.date_from = datetime.date.today() - datetime.timedelta(days=365)
        print("no --from/--to given; searching agendas since %s" % a.date_from, file=sys.stderr)
    a.fn(a)


if __name__ == "__main__":
    main()
