#!/usr/bin/env python3
"""Louisiana Supreme Court and Court of Appeal opinions, and Division of Administrative Law records.

  search <terms...> [--court la|1|2|3|4|5|all] [--from YYYY] [--to YYYY] [--fulltext]
  docket <docket> [--court la|lactapp]        every document under one docket, both sources
  fetch <docket|pdf-url> [--find REGEX]       download, then decision date, disposition, panel, pages
  grep <regex> (--docket D | --cached)         search downloaded opinion text, by page
  verify-cite "<citation or caption>"          found / conflicting / not found, later history, gaps
  dal-docket [--agency DEQ DCE DENR] [--grep company]
  dal-ethics <terms...>

Add --json for machine-readable output and --yes to allow a large download.
Sources: CourtListener v4 (court IDs `la`, `lactapp`) and the First Circuit's own opinion index.
"""
import argparse
import datetime
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import court_common as cc  # noqa: E402
import courtlistener as cl  # noqa: E402
import dal  # noqa: E402
import fcca_index as fcca  # noqa: E402

THIS_YEAR = datetime.date.today().year
# Sampled 2019-2026: every lactapp opinion CourtListener added came from the 2nd or 4th Circuit scrapers.
CL_CIRCUIT_END = {1: 2018, 3: 2018, 5: 2018}
CIRCUIT_SITES = {1: "la-fcca.org/decisions", 2: "la2nd.org", 3: "la3circuit.org", 4: "la4th.org",
                 5: "fifthcircuit.org", 0: "lasc.org/opinions"}


# ---------------------------------------------------------------- merge + render

def merge(records):
    """One row per normalized docket; each row keeps every document and names its sources."""
    rows = {}
    for r in records:
        row = rows.setdefault(r["key"], {"key": r["key"], "docket": r["docket"], "court": r["court"],
                                         "caption": r["caption"], "decision_date": None, "citations": [],
                                         "sources": [], "documents": [], "cluster_id": None, "url": None})
        if r["source"] not in row["sources"]:
            row["sources"].append(r["source"])
        if r.get("decision_date") and not row["decision_date"]:
            row["decision_date"] = r["decision_date"]
        for c in r.get("citations") or []:
            if c not in row["citations"]:
                row["citations"].append(c)
        if r["source"] == "courtlistener":
            row["cluster_id"] = row["cluster_id"] or r["cluster_id"]
            row["url"] = row["url"] or r["url"]
            row["caption"] = r["caption"] or row["caption"]
        row["documents"].append({k: r.get(k) for k in ("source", "title", "document", "pdf", "uploaded", "folder", "bytes")})
    return sorted(rows.values(), key=lambda x: (x["decision_date"] or "", x["docket"]["year"] if x["docket"] and x["docket"]["year"] else 0),
                  reverse=True)


def show_rows(rows):
    if not rows:
        print("(no matches)")
    for r in rows:
        dk = cc.docket_display(r["docket"]) if r["docket"] else "?"
        date = r["decision_date"] or "decision date: in PDF (run fetch)"
        print("%s  %s  %s" % (dk, r["court"], date))
        print("  %s" % r["caption"])
        if r["citations"]:
            print("  cites: %s" % "; ".join(r["citations"]))
        print("  sources: %s%s" % (", ".join(r["sources"]), ("  " + r["url"]) if r["url"] else ""))
        for d in r["documents"]:
            if not d["pdf"]:
                continue
            extra = ("  doc %s" % d["document"]) if d.get("document") and d["document"] > 1 else ""
            up = ("  (uploaded %s, folder %s)" % (d["uploaded"], d["folder"])) if d.get("uploaded") else ""
            print("    %s%s%s" % (d["pdf"], extra, up))


def year_range(a):
    y_to = int(a.date_to) if a.date_to else THIS_YEAR
    y_from = int(a.date_from) if a.date_from else y_to - 4
    return y_from, y_to


# ---------------------------------------------------------------- commands

def cmd_search(a):
    y_from, y_to = year_range(a)
    recs, notes = [], []
    if a.court in ("1", "all"):
        # Docket-year folders: a case decided in Y is usually docketed in Y-1.
        recs += fcca.search(a.cache, a.terms, y_from - 1, y_to, a.yes)
    field = "" if a.fulltext else "caseName:"
    q = " AND ".join('%s"%s"' % (field, t) for t in a.terms)
    count, found = cl.search({"q": q, "court": cl.courts_for(a.court), "order_by": "dateFiled desc",
                              "filed_after": "%d-01-01" % y_from, "filed_before": "%d-12-31" % y_to}, a.cache)
    if count > len(found):
        notes.append("CourtListener matched %d; fetched the newest %d" % (count, len(found)))
    if a.court in "12345":
        # lactapp mixes all five circuits, so the circuit filter can only run after the fetch.
        kept = [r for r in found if r["circuit"] == int(a.court)]
        if len(kept) < len(found):
            notes.append("%d CourtListener hit(s) from other circuits dropped" % (len(found) - len(kept)))
        found = kept
    recs += found
    for c, end in CL_CIRCUIT_END.items():
        if a.court in (str(c), "all") and y_to > end:
            if c == 1:
                notes.append("CourtListener has no First Circuit opinions after %d; the First Circuit's own index covers that." % end)
            else:
                notes.append("CourtListener has no %s Circuit opinions after %d and this skill has no %s index: "
                             "search %s with WebSearch (site:%s)." % (("Third", "Fifth")[c == 5], end, CIRCUIT_SITES[c],
                                                                       CIRCUIT_SITES[c], CIRCUIT_SITES[c]))
    notes.append("A party-name match is not a case match: confirm the docket and the agency before treating a hit as history.")
    rows = merge(recs)
    cc.emit({"rows": rows, "notes": notes}, a.json, lambda o: (show_rows(o["rows"]), [print("note: " + n) for n in o["notes"]]))


def lookup_docket(d, cache, yes, court=None):
    recs = []
    if d["circuit"] == 1:
        recs += fcca.by_docket(cache, d, yes)
    if d["type"]:
        q = 'docketNumber:"%s"' % cc.docket_display(d)
    else:
        # Letterless uniform form: match the year and serial tokens, whatever case-type letters sit between.
        q = 'docketNumber:"%s" AND docketNumber:"%s"' % tuple(re.search(r"(\d{2,4})-(\d{3,5})", d["text"]).groups())
    _, found = cl.search({"q": q, "court": court or d["court"]}, cache)
    kk = "key" if d["type"] else "loose"
    recs += [r for r in found if r["docket"] and r["docket"][kk] == d[kk]]
    return recs


def cmd_docket(a):
    d = cc.parse_docket(a.docket, court=a.court)
    if not d:
        sys.exit("unrecognised docket format: %r" % a.docket)
    rows = merge(lookup_docket(d, a.cache, a.yes, a.court))
    notes = []
    if d["circuit"] in CL_CIRCUIT_END and (d["year"] or 0) > CL_CIRCUIT_END[d["circuit"]] and d["circuit"] != 1:
        notes.append("not covered by CourtListener after %d; check %s" % (CL_CIRCUIT_END[d["circuit"]], CIRCUIT_SITES[d["circuit"]]))
    cc.emit({"docket": d, "rows": rows, "notes": notes}, a.json,
            lambda o: (show_rows(o["rows"]), [print("note: " + n) for n in o["notes"]]))


def read_opinion(url, cache, meta, find=None):
    path = cc.get_pdf(url, cache, meta)
    text = cc.pdf_text(path, layout=True)
    out = dict(meta, pdf=url, local=path, **cc.opinion_meta(text))
    if find:
        out["find"] = {"regex": find, "pages": cc.page_of(text, find)}
    return out


def cmd_fetch(a):
    if re.match(r"https?://", a.target):
        targets = [(a.target, {"caption": None, "docket": None, "source": "url"})]
    else:
        d = cc.parse_docket(a.target, court=a.court)
        if not d:
            sys.exit("unrecognised docket format: %r" % a.target)
        rows = merge(lookup_docket(d, a.cache, a.yes, a.court))
        if not rows:
            sys.exit("docket %s not found in the First Circuit index or CourtListener" % cc.docket_display(d))
        targets = [(doc["pdf"], {"caption": r["caption"], "docket": cc.docket_display(r["docket"]), "court": r["court"],
                                 "source": doc["source"], "document": doc.get("document"),
                                 "decision_date_source": r["decision_date"], "citations": r["citations"]})
                   for r in rows for doc in r["documents"] if doc["pdf"]]
    cc.guard_pdfs([t[0] for t in targets], a.cache, a.yes)
    out = [read_opinion(u, a.cache, m, a.find) for u, m in targets]
    for o in out:
        d = cc.parse_docket(o.get("docket") or "")
        date = o["decision_date"] or o.get("decision_date_source")
        # A rehearing or writ action is history of the opinion, not a citable decision date for it.
        o["citation"] = (cc.format_cite(o["caption"], d, date, (o.get("citations") or [None])[0])
                         if o.get("caption") and d and o["kind"] == "opinion" else None)

    def show(rows):
        for o in rows:
            print("%s  doc %s  %s" % (o.get("docket") or o["pdf"], o.get("document") or 1, o.get("caption") or ""))
            print("  pages: %d   text layer: %s" % (o["pages"], "yes" if o["text_layer"] else "NO (scanned; OCR before quoting)"))
            print("  decision: %s   [%s]" % (o["decision_date"] or "not found in text", o["decision_date_line"] or "-"))
            print("  disposition: %s" % (o["disposition"] or "not found"))
            print("  panel: %s" % (o["panel"] or "not found"))
            for x in o["actions"]:
                print("  %s filed %s by %s: %s %s" % (x["application"], x["filed"], x["by"], x["result"], x["date"] or ""))
            if o.get("find"):
                print("  /%s/ on page(s): %s" % (o["find"]["regex"], o["find"]["pages"] or "none"))
            if o.get("citation"):
                print("  cite as: %s" % o["citation"])
            print("  text: %s" % (o["local"] + ".layout.txt"))
    cc.emit(out, a.json, show)


def cmd_grep(a):
    files = []
    for meta_path in glob.glob(os.path.join(a.cache, "pdf", "*.pdf.json")):
        with open(meta_path) as fh:
            m = json.load(fh)
        if a.docket:
            want = cc.parse_docket(a.docket)
            got = cc.parse_docket(m.get("docket") or "")
            if not (want and got and want["key"] == got["key"]):
                continue
        files.append((meta_path[:-5], m))
    if a.docket and not files:
        sys.exit("nothing cached for %s; run fetch first" % a.docket)
    rx = re.compile(a.regex, re.I)
    hits = []
    for pdf, m in files:
        text = cc.pdf_text(pdf, layout=True)
        for pn, page in enumerate(text.split("\f"), 1):
            lines = page.splitlines()
            covered = -1
            for i, line in enumerate(lines):
                # A match inside the previous hit's context window is already shown.
                if rx.search(line) and i > covered:
                    covered = i + a.context
                    ctx = " ".join(l.strip() for l in lines[max(0, i - a.context): i + a.context + 1])
                    hits.append({"docket": m.get("docket"), "caption": m.get("caption"), "document": m.get("document"),
                                 "page": pn, "text": cc.clean(ctx)})
    cc.emit(hits, a.json, lambda hs: [print("%s doc %s p.%d: %s" % (h["docket"], h["document"] or 1, h["page"], h["text"]))
                                      for h in hs] or print("(no matches in %d cached opinion(s))" % len(files)))


def _claims(text):
    """What a citation string asserts: reporter cite, year, court, docket, caption."""
    c = {"reporter": None, "year": None, "circuit": None, "docket": None, "caption": None}
    q = cl.cite_query(re.sub(r"^.*?,\s*(?=\d+\s+So)", "", text)) if re.search(r"\d+\s+So\.?\s*(2d|3d)?\s*\d+", text) else None
    if q:
        c["reporter"] = q[1]
    m = re.search(r"\((La\.(?:\s*App\.\s*(\d)\s*Cir\.)?)[^)]*?(\d{4}|\d{1,2}/\d{1,2}/\d{2,4})\)", text)
    if m:
        c["circuit"] = int(m.group(2)) if m.group(2) else 0
        tail = m.group(3)
        c["year"] = int(tail) if len(tail) == 4 else cc._yr(tail.rsplit("/", 1)[1])
    c["docket"] = cc.parse_docket(re.sub(r"\(.*?\)", "", text), court="la" if c["circuit"] == 0 else None,
                                  circuit=c["circuit"])
    cap = re.split(r",\s*(?:No\.|\d)", text)[0].strip()
    if cap and not re.match(r"^\d", cap) and len(cap) > 3:
        c["caption"] = cap
    return c


STOP = set("""v vs in re matter of the and state louisiana la department dept inc ind industries co corp company llc
l.l.c ltd et al app parish city secretary through by its on behalf for""".split())


def _short_party(caption, n=2):
    """The first `n` distinctive caption words -- enough to find the same case under the different
    caption forms LASC and the circuits use ("Matter of Browning-Ferris Ind." vs "In re Browning-Ferris Industries")."""
    words = re.findall(r"[A-Za-z][A-Za-z'\-]{2,}", caption or "")
    return [w for w in words if w.lower().strip(".") not in STOP][:n]


def cmd_verify(a):
    claims = _claims(a.citation)
    recs, how = [], None
    if claims["reporter"]:
        how = "reporter citation"
        _, recs = cl.search({"q": cl.cite_query(claims["reporter"])[0], "court": "la lactapp"}, a.cache)
    if not recs and claims["docket"]:
        how = "docket"
        recs = lookup_docket(claims["docket"], a.cache, a.yes)
    if not recs and claims["caption"]:
        how = "caption"
        terms = _short_party(claims["caption"])
        if terms:
            _, recs = cl.search({"q": " AND ".join('caseName:"%s"' % t for t in terms), "court": "la lactapp"}, a.cache)
            if claims["circuit"] in (1, None):
                y = claims["year"] or THIS_YEAR
                recs += fcca.search(a.cache, terms, max(1988, y - 2), min(THIS_YEAR, y + 1), a.yes)
    rows = merge(recs)
    shared = []
    if len(rows) > 1 and how == "reporter citation" and (claims["caption"] or claims["year"]):
        # CourtListener sometimes gives two cases the same reporter cite; the citation's own
        # caption and year pick between them, and the other is reported, not hidden.
        words = [w.lower() for w in _short_party(claims["caption"] or "", 3)]
        fit = [r for r in rows if (not words or any(w in r["caption"].lower() for w in words))
               and (not claims["year"] or (r["decision_date"] or "")[:4] == str(claims["year"]))]
        if len(fit) == 1:
            shared = [r for r in rows if r is not fit[0]]
            rows = fit
    if len(rows) == 1 and not rows[0]["decision_date"]:
        # The First Circuit index has no decision dates; the year check needs the one in the PDF.
        r = rows[0]
        cc.guard_pdfs([d["pdf"] for d in r["documents"] if d["pdf"]], a.cache, a.yes)
        for doc in r["documents"]:
            m = read_opinion(doc["pdf"], a.cache, {"caption": r["caption"], "docket": cc.docket_display(r["docket"]),
                                                   "court": r["court"], "source": doc["source"], "document": doc.get("document")})
            if m["kind"] == "opinion" and m["decision_date"]:
                r["decision_date"] = m["decision_date"]
                r["disposition"] = m["disposition"]
    conflicts, gaps, history = [], [], []
    if not rows:
        status = "not found in either source"
    elif len(rows) > 1 and how != "docket":
        status = "ambiguous: %d cases match; pick by docket" % len(rows)
    else:
        status = "found"
        r = rows[0]
        circ = r["docket"]["circuit"] if r["docket"] else None
        year = int(r["decision_date"][:4]) if r["decision_date"] else None
        if claims["year"] and year and claims["year"] != year:
            conflicts.append("year: citation says %d, opinion was decided %s" % (claims["year"], r["decision_date"]))
        if claims["circuit"] is not None and circ is not None and claims["circuit"] != circ:
            conflicts.append("court: citation says %s, record says %s" % (cc.court_label(claims["circuit"]), cc.court_label(circ)))
        if claims["reporter"] and r["citations"] and not any(claims["reporter"].replace(" ", "") == c.replace(" ", "") for c in r["citations"]):
            conflicts.append("reporter: citation says %s, record lists %s" % (claims["reporter"], "; ".join(r["citations"])))
        for o in shared:
            conflicts.append("reporter cite %s is also assigned on CourtListener to %s, %s (%s); one of the two is a "
                             "data error, so confirm the first page in the reporter" % (
                                 claims["reporter"], o["caption"], cc.docket_display(o["docket"]) if o["docket"] else "?", o["decision_date"]))
        if conflicts:
            status = "conflicting"
        if not a.no_history:
            history, hgaps = later_history(r, a.cache)
            gaps += hgaps
    late = rows and rows[0]["docket"] and rows[0]["docket"]["circuit"] in (1, 3, 5) and (rows[0]["decision_date"] or "9999") > "2018"
    if (not rows and claims["circuit"] in (None, 1, 3, 5)) or late:
        gaps.append("CourtListener carries no First, Third or Fifth Circuit opinions after 2018; the First Circuit index "
                    "covers the First, and the Third and Fifth need WebSearch on la3circuit.org / fifthcircuit.org.")
    if not rows and claims["circuit"] == 1 and (claims["year"] or THIS_YEAR) < 2006:
        gaps.append("The First Circuit's own site holds only 35 documents for 1988-2005.")
    if rows:
        gaps.append("This confirms the case exists and its metadata. It does not show the opinion supports the proposition "
                    "it is cited for: read the pin page (fetch <docket> --find REGEX).")
    out = {"input": a.citation, "claims": claims, "matched_by": how, "status": status, "matches": rows,
           "conflicts": conflicts, "later_history": history, "gaps": gaps}

    def show(o):
        print("status: %s%s" % (o["status"], (" (matched by %s)" % o["matched_by"]) if o["matched_by"] else ""))
        show_rows(o["matches"])
        for c in o["conflicts"]:
            print("CONFLICT  " + c)
        for h in o["later_history"]:
            print("history   " + h)
        for g in o["gaps"]:
            print("gap       " + g)
    cc.emit(out, a.json, show)


def later_history(r, cache):
    """Possible LASC writ actions (by name, after the decision date) and citing opinions."""
    lines, gaps = [], []
    terms = _short_party(r["caption"])
    after = r["decision_date"]
    if r["docket"] and r["docket"]["circuit"] != 0 and terms and after:
        _, writs = cl.search({"q": " AND ".join('caseName:"%s"' % t for t in terms), "court": "la",
                              "filed_after": after, "order_by": "dateFiled asc"}, cache)
        for w in writs[:8]:
            lines.append("LASC %s %s %s %s  (name match only; confirm the writ names this docket)" % (
                w["decision_date"], w["docket_raw"], w["caption"], "; ".join(w["citations"])))
        if not writs:
            gaps.append("No LASC opinion on CourtListener names these parties after %s. That is not proof of no writ: "
                        "one-line writ denials are often missing; check lasc.org actions for the docket." % after)
    if r.get("cluster_id"):
        n, citing = cl.search({"q": "cites:(%s)" % r["cluster_id"], "court": "la lactapp", "order_by": "dateFiled desc"}, cache, 5)
        lines.append("cited by %d Louisiana opinion(s) on CourtListener (which lacks 1st/3rd/5th Cir. after 2018)%s" % (n, (": newest " + "; ".join(
            "%s %s" % (c["decision_date"], c["caption"][:60]) for c in citing[:3])) if citing else ""))
    else:
        gaps.append("Not on CourtListener, so citing opinions cannot be counted here.")
    return lines, gaps


def cmd_dal_docket(a):
    rows = dal.docket(a.cache, a.agency, a.grep)
    note = ("DAL's docket is the current hearing schedule only, and DAL calls it non-exhaustive. Decisions in DEQ, DCE "
            "and DENR matters are not published online: request them with bayou:la-public-records-request.")
    cc.emit({"rows": rows, "note": note}, a.json, lambda o: (
        [print("%s %-11s %-16s %-45s %s, %s" % (r["date"], r["time"], r["matter"], (r["case"] or "")[:45], r["event"], r["location"]))
         for r in o["rows"]] or print("(no matching hearings on the current docket)"), print("note: " + o["note"])))


def cmd_dal_ethics(a):
    total, rows = dal.ethics(" ".join(a.terms), a.page)
    cc.emit({"total": total, "rows": rows}, a.json, lambda o: (
        print("%d document(s) found; page %d" % (o["total"], a.page)),
        [print("%s\n  %s\n  %s" % (r["title"], r["pdf"], r["snippet"] or "")) for r in o["rows"]]))


def main():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true")
    common.add_argument("--yes", action="store_true", help="allow downloads over the size guard")
    common.add_argument("--cache", default=cc.DEFAULT_CACHE)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("search", parents=[common])
    s.add_argument("terms", nargs="+")
    s.add_argument("--court", default="all", choices=["la", "1", "2", "3", "4", "5", "all"])
    s.add_argument("--from", dest="date_from", help="decision year (default: four years back)")
    s.add_argument("--to", dest="date_to", help="decision year (default: this year)")
    s.add_argument("--fulltext", action="store_true", help="match CourtListener opinion text, not just the caption")
    d = sp.add_parser("docket", parents=[common])
    d.add_argument("docket")
    d.add_argument("--court", choices=["la", "lactapp"], help="break a format tie (LASC vs 4th/5th Cir.)")
    f = sp.add_parser("fetch", parents=[common])
    f.add_argument("target", help="docket number or PDF URL")
    f.add_argument("--court", choices=["la", "lactapp"])
    f.add_argument("--find", help="regex; report the opinion pages it appears on")
    g = sp.add_parser("grep", parents=[common])
    g.add_argument("regex")
    gg = g.add_mutually_exclusive_group(required=True)
    gg.add_argument("--docket")
    gg.add_argument("--cached", action="store_true")
    g.add_argument("--context", type=int, default=1)
    v = sp.add_parser("verify-cite", parents=[common])
    v.add_argument("citation")
    v.add_argument("--no-history", action="store_true", help="skip the writ and citing-opinion searches (saves ~30s)")
    k = sp.add_parser("dal-docket", parents=[common])
    k.add_argument("--agency", nargs="+", help="matter suffix: DEQ DCE DENR ...")
    k.add_argument("--grep")
    e = sp.add_parser("dal-ethics", parents=[common])
    e.add_argument("terms", nargs="+")
    e.add_argument("--page", type=int, default=1)
    a = ap.parse_args()
    try:
        {"search": cmd_search, "docket": cmd_docket, "fetch": cmd_fetch, "grep": cmd_grep, "verify-cite": cmd_verify,
         "dal-docket": cmd_dal_docket, "dal-ethics": cmd_dal_ethics}[a.cmd](a)
    except cc.GuardStop as ex:
        print(str(ex), file=sys.stderr)
        sys.exit(3)
    except cl.RateLimited as ex:
        print(str(ex), file=sys.stderr)
        sys.exit(4)


if __name__ == "__main__":
    main()
