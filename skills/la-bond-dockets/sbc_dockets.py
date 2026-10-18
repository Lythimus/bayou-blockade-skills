#!/usr/bin/env python3
"""Louisiana State Bond Commission (SBC) meetings, agenda dockets, and recorded outcomes.

    sbc_dockets.py meetings [--year 2026] [--archive]
    sbc_dockets.py agenda 09/17/2026 [--stage preliminary|posted|final]
    sbc_dockets.py agenda next                       # the next meeting's newest agenda, if posted
    sbc_dockets.py search Hyundai "Port of South Louisiana" [--from 2026-01-01] [--to 2026-12-31]
    sbc_dockets.py search --docket S26-027
    sbc_dockets.py outcome 09/17/2026                # minutes → outcome per agenda item
    add --json for machine-readable output, --yes to allow a large download

Source: https://www.treasury.la.gov/state-bond-commission (current year) and
/bond-commission-meetings-archive (2023 onward). Agendas and minutes are text-layer PDFs.
Standard library plus poppler's pdftotext.
"""
import argparse
import datetime
import json
import os
import html
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bond_common as bc  # noqa: E402

CURRENT = "https://www.treasury.la.gov/state-bond-commission"
ARCHIVE = "https://treasury.la.gov/bond-commission-meetings-archive"
STAGES = ("final", "posted", "preliminary")
DATE_RE = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")
DOCKET_RE = r"[LS]\d{2}-\d{3}[A-Z]?"
STAMP_RE = re.compile(r"^(WITHDRAWN|DEFERRED|REMOVED|ADDED|PULLED|TABLED|APPROVED|DISAPPROVED)\b[A-Z ,/()-]*$")
OUTCOME_WORDS = r"conditionally approved|approved|disapproved|deferred|withdrawn|denied|rejected|tabled"


# ---------------------------------------------------------------- meetings table

def link_label(text):
    t = text.lower()
    if "prelim" in t:
        return "preliminary"
    if "posted" in t:
        return "posted"
    if "final" in t or "sap" in t:
        # "(*SAP)" fills the post-meeting column; its PDF is headed FINAL AGENDA.
        return "final"
    if "minute" in t:
        return "minutes"
    return "other"


def parse_meetings(page_html, base):
    """Meeting rows from the SBC schedule table(s).

    The page is a Wix table flattened into a token stream: per row, the meeting date, the
    application deadline, the 10-day deadline, an optional election date, then document links.
    Future rows have dates only, so meeting boundaries there are inferred from date order.
    """
    body = re.sub(r"<script.*?</script>|<style.*?</style>", "", page_html, flags=re.S | re.I)
    tokens = []
    pos = 0
    anchor = re.compile(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S | re.I)
    for m in anchor.finditer(body):
        tokens += _date_tokens(body[pos:m.start()])
        text = bc.norm(re.sub(r"<[^>]+>", " ", bc.html.unescape(m.group(2))))
        href = bc.urllib.parse.urljoin(base, bc.html.unescape(m.group(1)))
        if href.lower().endswith(".pdf") and text:
            tokens.append(("link", href, text))
        pos = m.end()
    tokens += _date_tokens(body[pos:])

    rows, cur, after_link = [], None, False
    for tok in tokens:
        if tok[0] == "date":
            d = tok[1]
            new_row = cur is None or after_link
            if not new_row:
                gap = (d - cur["meeting_date"]).days
                if gap < 0 and cur["apps_due"] is None:
                    cur["apps_due"] = d
                elif gap < 0 and cur["deadline"] is None:
                    cur["deadline"] = d
                elif gap > 0 and cur["deadline"] is not None and not 14 <= gap <= 45 and cur["election_date"] is None:
                    # Monthly meetings are 3-6 weeks apart; a later date outside that is the election date.
                    cur["election_date"] = d
                else:
                    new_row = True
            if new_row:
                cur = {"meeting_date": d, "apps_due": None, "deadline": None, "election_date": None,
                       "preliminary": None, "posted": None, "final": None, "minutes": None, "other": []}
                rows.append(cur)
                after_link = False
        else:
            if cur is None:
                continue
            label = link_label(tok[2])
            if label == "other":
                if not re.match(r"^(LOC|RES)\d*$", tok[2]):
                    continue  # page-wide links (ADA forms) that follow the table
                cur["other"].append({"label": tok[2], "url": tok[1]})
            elif cur[label] is None:
                cur[label] = tok[1]
            after_link = True
    # Rows are repeated when a year appears in more than one table; keep the one with documents.
    best = {}
    for r in rows:
        k = r["meeting_date"]
        score = (sum(bool(r[s]) for s in ("preliminary", "posted", "final", "minutes")),
                 sum(r[s] is not None for s in ("apps_due", "deadline", "election_date")))
        if k not in best or score > best[k][0]:
            best[k] = (score, r)
    return [best[k][1] for k in sorted(best)]


def _date_tokens(chunk):
    text = bc.html.unescape(re.sub(r"<[^>]+>", " ", chunk))
    out = []
    for m in DATE_RE.finditer(text):
        d = bc._mk(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        if d:
            out.append(("date", d))
    return out


def load_meetings(archive=False):
    rows = parse_meetings(bc.fetch_text(CURRENT), CURRENT)
    if not rows:
        sys.exit("SBC page layout changed: no dated meeting rows found at %s" % CURRENT)
    if archive:
        seen = {r["meeting_date"] for r in rows}
        rows += [r for r in parse_meetings(bc.fetch_text(ARCHIVE), ARCHIVE) if r["meeting_date"] not in seen]
        rows.sort(key=lambda r: r["meeting_date"])
    return rows


def pick_meeting(rows, spec):
    today = datetime.date.today()
    if spec == "next":
        fut = [r for r in rows if r["meeting_date"] >= today]
        if not fut:
            sys.exit("no upcoming SBC meeting on the schedule")
        return fut[0]
    if spec == "latest":
        have = [r for r in rows if any(r[s] for s in STAGES)]
        return have[-1]
    d = bc.arg_date(spec)
    for r in rows:
        if r["meeting_date"] == d:
            return r
    sys.exit("no SBC meeting on %s in the schedule (try --archive for 2023-2025)" % d)


def stage_url(row, stage=None):
    order = [stage] if stage else list(STAGES)
    for s in order:
        if row.get(s):
            return s, row[s]
    return None, None


# ---------------------------------------------------------------- agenda parsing

def parse_agenda(text):
    """Numbered agenda items with docket, caption, amounts, section header, and status stamp."""
    # Some agendas set every hyphen as a soft hyphen or dash ("S24\u00ad020B \u00ad State of ...").
    text = re.sub("[\u00ad\u2010\u2011\u2012\u2013\u2014]", "-", text).replace("\u037e", ";")
    lines = text.replace("\f", "\n").split("\n")
    head = bc.norm(" ".join(lines[:8]))
    items, cur, section, expect = [], None, None, 1
    pending = []  # stamps stacked on one item in reading order that belong to the items after it
    for raw in lines:
        s = raw.strip()
        if not s:
            continue
        if re.match(r"^\d{1,3}$", s):
            continue  # page number
        if s.startswith("If you have a disability"):
            break
        if STAMP_RE.match(s):
            if cur is not None:
                if cur["status_stamp"]:
                    pending.append(s)
                else:
                    cur["status_stamp"] = s
            continue
        m = re.match(r"^(\d{1,3})\.(?:\s+(.*))?$", s)
        if m and int(m.group(1)) == expect:
            cur = _new_item(int(m.group(1)), None, m.group(2) or "", section)
            if pending:
                cur["status_stamp"] = pending.pop(0)
            items.append(cur)
            expect += 1
            sub = re.match(r"^\(([a-z])\)\s+(.*)$", m.group(2) or "")
            if sub:
                cur["sub_item"], cur["_lines"] = sub.group(1), [sub.group(2)]
            if re.match(r"^Adjourn\b", m.group(2) or ""):
                break
            continue
        sub = re.match(r"^\(([a-z])\)\s+(.*)$", s)
        if sub and cur is not None and cur["sub_item"]:
            cur = _new_item(cur["item_no"], sub.group(1), sub.group(2), section)
            items.append(cur)
            continue
        if not re.search(r"[a-z]", s) and len(s) >= 6 and not re.match(DOCKET_RE, s) and not re.match(r"^[\d$(]", s):
            section = bc.norm(s)
            cur = None
            continue
        if cur is not None:
            cur["_lines"].append(s)
    return {"header": head, "public_comment": _public_comment(text), "items": [_finish(i) for i in items]}


def _new_item(no, sub, first, section):
    return {"item_no": no, "sub_item": sub, "section": section, "status_stamp": None, "_lines": [first]}


def _finish(item):
    text = ""
    lines = [ln for ln in item.pop("_lines") if ln]
    first = lines[0] if lines else ""
    for ln in lines:
        if text.endswith("-") and ln[:1].isalnum():
            text += ln  # rejoin a word or year range hyphenated across lines
        else:
            text += (" " if text else "") + ln
    text = bc.norm(text)
    item["raw_text"] = text
    m = re.match(r"^(%s)\s+-\s+(.*)$" % DOCKET_RE, text)
    item["docket"] = m.group(1) if m else None
    rest = m.group(2) if m else text
    # Issuer names can contain " - " ("Ernest N. Morial - New Orleans Exhibition Hall Authority"),
    # so split where the description's characteristic opening starts.
    # Older agendas put "docket - issuer" alone on the first line and the description below it.
    fm = re.match(r"^(%s)\s+-\s+(.*)$" % DOCKET_RE, first)
    if m and fm and " - " not in fm.group(2) and len(lines) > 1 and not re.search(r"Not exceeding|mills|sales tax", fm.group(2)):
        rest = fm.group(2) + " - " + rest[len(fm.group(2)):].lstrip()
    dm = re.search(r" - (?=(?:\(\d\)\s*)?(?:Not exceeding|Amendment|Amend|Reporting|Discussion|Approval|Request|"
                   r"Consideration|Authoriz|Ratif|Line|\$|[\d½¼¾]))", rest)
    issuer_part, desc = (rest[:dm.start()], rest[dm.end():]) if dm else (rest.partition(" - ")[0], rest.partition(" - ")[2])
    cap = re.search(r"\(([^()]*)\)\s*$", issuer_part)
    item["issuer"] = (issuer_part[:cap.start()].strip() if cap else issuer_part.strip()) if m else None
    item["project_caption"] = cap.group(1) if (cap and m) else None
    item["description"] = desc if m else None
    # Par is the cap on a debt instrument; "Not exceeding $75 service charge" is a fee, not par.
    par = re.search(r"Not exceeding \$([\d,]+(?:\.\d+)?)\s+((?:[A-Z(][\w&()/-]*\s+){0,7}?"
                    r"(?:Bonds?|Notes?|Certificates?(?: of Indebtedness)?|Obligations?|Loans?|Warrants?))\b", text)
    item["par_amount"] = int(float(par.group(1).replace(",", ""))) if par else None
    amounts = [a for a in re.findall(r"\$([\d,]+(?:\.\d+)?)", text)]
    if par and par.group(1) in amounts:
        amounts.remove(par.group(1))
    item["other_amounts"] = [int(float(a.replace(",", ""))) for a in amounts if a.strip(",")]
    item["bond_type"] = re.sub(r"\s*\([^)]*\)", "", par.group(2)).strip() if par else None
    item["volume_cap"] = "volume cap" in text.lower()
    return item


def _public_comment(text):
    t = bc.norm(text.replace("\f", " "))
    m = re.search(r"(?:The public may submit comments|Persons who do not feel comfortable giving testimony).*?(?:for this meeting\.|$)", t)
    return m.group(0)[:600] if m else None


def stamp_positions(pdf):
    """{item_no: stamp text} from where each stamp is drawn on the page.

    Stamps are large overlay text. In reading order one can fall between two items, or be split
    so the text parse misses it, so the item is the last item heading at or above the stamp's
    vertical centre.
    """
    try:
        out = subprocess.run(["pdftotext", "-bbox", pdf, "-"], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return {}
    heads, found = [], {}
    stamps = []
    for pno, page in enumerate(out.split("<page")[1:]):
        words = [(float(a), float(b), float(c), float(d), html.unescape(w)) for a, b, c, d, w in
                 re.findall(r'xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)<', page)]
        for x0, y0, x1, y1, w in words:
            if re.fullmatch(r"\d{1,3}\.", w) and x0 < 75:
                heads.append((pno, y0, int(w[:-1])))
            elif re.fullmatch(r"WITHDRAWN|DEFERRED|REMOVED|PULLED|TABLED|DISAPPROVED", w) and y1 - y0 > 20:
                yc = (y0 + y1) / 2
                line = sorted((wx0, ww) for wx0, wy0, _, wy1, ww in words
                              if abs((wy0 + wy1) / 2 - yc) < 6 and wy1 - wy0 > 20 and wx0 >= x0)
                stamps.append((pno, yc, " ".join(ww for _, ww in line)))
    for pno, yc, text in stamps:
        above = [h for h in heads if (h[0], h[1]) <= (pno, yc)]
        if above:
            found[above[-1][2]] = text
    return found


def agenda_for(row, stage, cache, yes):
    st, url = stage_url(row, stage)
    if not url:
        return None
    if yes is not None:  # None: the caller already ran the guard over its whole batch
        bc.guard([url], cache, "sbc", yes)
    # Raw (reading-order) text: -layout mode can move a WITHDRAWN stamp onto the neighbouring item.
    pdf = bc.get_pdf(url, cache, "sbc")
    text = bc.pdf_text(pdf, layout=False)
    parsed = parse_agenda(text)
    placed = stamp_positions(pdf)
    if placed:
        for it in parsed["items"]:
            it["status_stamp"] = placed.get(it["item_no"]) if not it["sub_item"] or it["sub_item"] == "a" else None
    parsed.update({"meeting_date": row["meeting_date"].isoformat(), "stage": st, "url": url})
    # An empty parse must never read as "no matching dockets" downstream.
    if not bc.has_text_layer(text):
        parsed["parse_problem"] = "no text layer (scanned); OCR with bayou:document-ocr"
    elif not any(i["raw_text"].startswith("Adjourn") for i in parsed["items"]):
        # Special meetings legitimately have no dockets, but every agenda ends with "Adjourn".
        parsed["parse_problem"] = "item numbering never reached Adjourn; agenda format may have changed"
    else:
        parsed["parse_problem"] = None
    if parsed["parse_problem"]:
        print("warning: %s %s agenda: %s (%s)" % (parsed["meeting_date"], st, parsed["parse_problem"], url), file=sys.stderr)
    for it in parsed["items"]:
        it.update({"meeting_date": parsed["meeting_date"], "stage": st, "url": url})
    return parsed


# ---------------------------------------------------------------- minutes parsing

_ABBR = re.compile(r"\b(Mr|Ms|Mrs|Dr|No|St|Jr|Sr|Inc|Co|Corp|Rep|Sen|Lt|Ft|vs|A\.M|P\.M)\.")
# "Speaker DeVillier moved" names a person; "Clay Schexnayder, Speaker of the House moved" and
# "Jay Morris III, Senator at Large, was recused" name an office.
_TITLE = r"(?:Representative(?! at Large)|Senator(?! at Large)|Treasurer|Commissioner(?! of)|Secretary(?! of)|Chairman|Honorable|Speaker(?! of)|Mr\.|Ms\.|Mrs\.|Dr\.)"
# What "the item was approved" may be about; older minutes record each item this way.
_THING = (r"(?:[\w'\u2019-]+ (?:and )?){0,3}?(?:item|resolution|report|rule|request|amendment|matter|motion|"
          r"recommendation|selection|policy|dates)s?")
_ITEM_HEAD = re.compile(r"^ {0,2}(\d{1,3})\.\s+(\S.*)$")


def _sentences(par):
    p = _ABBR.sub(lambda m: m.group(1) + "\u2024", par)
    p = re.sub(r"\b([A-Z])\.(?=[A-Z]\.|\s[A-Z][a-z]|\s[\"\u201c])", "\\1\u2024", p)
    out = re.split(r"(?<=[.;])\s+(?=[A-Z\"\u201c])", p)
    return [s.replace("\u2024", ".") for s in out]


def _person(before):
    """The person named just before a verb: from the last title word up to the first comma."""
    # "Ms. Nancy Landry, representing Secretary of State R. Kyle Ardoin moved": the mover is Ms. Landry.
    starts = [m.start() for m in re.finditer(r"\b%s\s" % _TITLE, before)
              if not re.search(r"representing\s+(?:the\s+)?$", before[:m.start()])]
    if not starts:
        return None
    return before[starts[-1]:].split(",")[0].strip()


def item_refs(s):
    """{(item_no, sub)} referenced in a phrase. sub is None when the whole item is meant."""
    refs, excluded = set(), set()
    for m in re.finditer(r"\b[Ii]tems?\s+((?:\d{1,3}(?:\s*\([a-z]\))?(?:\s*(?:,|and|through|&|-)\s*(?:Items?\s+)?)?)+)", s):
        chunk = m.group(1)
        # "Items 17 through 28, excluding Item 21"
        dest = excluded if re.search(r"\b(?:excluding|except(?: for)?|other than)\s+$", s[:m.start()]) else refs
        parts = re.findall(r"(\d{1,3})(?:\s*\(([a-z])\))?|(through)", chunk)
        last = None
        pending_range = False
        for num, sub, thr in parts:
            if thr:
                pending_range = True
                continue
            n = int(num)
            if pending_range and last is not None:
                dest.update((k, None) for k in range(last + 1, n + 1))
            else:
                dest.add((n, sub or None))
            pending_range, last = False, n
    return refs - excluded


def _paragraphs(raw_lines):
    """[(text, item)] where item is the agenda item a block belongs to, or None.

    Two layouts exist. Minutes through early 2025 repeat each agenda item as a flush-left
    "N. <docket> - <issuer>" heading followed by its own outcome sentence ("the item was approved"),
    so the item number comes from the heading. Later minutes are indented narrative paragraphs that
    name their items ("Items 3 through 47 were approved").
    """
    heads, expect = [], None
    for i, ln in enumerate(raw_lines):
        m = _ITEM_HEAD.match(ln)
        if m and (expect is None or int(m.group(1)) == expect):
            heads.append(i)
            expect = int(m.group(1)) + 1
    out, cur, item = [], [], None

    def flush():
        if cur:
            out.append((bc.norm(" ".join(cur)), item))
        cur.clear()

    # Special meetings have only two or three items, so a short run counts if it starts at item 1.
    if len(heads) >= 5 or (len(heads) >= 2 and _ITEM_HEAD.match(raw_lines[heads[0]]).group(1) == "1"):
        heads = set(heads)
        for i, ln in enumerate(raw_lines):
            if i in heads:
                flush()
                item = int(_ITEM_HEAD.match(ln).group(1))
            elif re.match(r"^\s{12,}\S", ln) and len(ln.strip()) < 90 and not re.search(r"[.,;]$", ln.strip()):
                # A centred section heading ends the previous item; what follows it until the next
                # heading ("Ms. Folse provided a synopsis on Items 85 and 86.") names its own items.
                flush()
                item = None
                continue
            cur.append(ln.strip())
        flush()
        return out
    for ln in raw_lines:
        if re.match(r"^\s{4,}\S", ln):
            flush()
        cur.append(ln.strip())
    flush()
    return out


def parse_minutes(text):
    text = re.sub("[\u00ad\u2010\u2011\u2012\u2013\u2014]", "-", text)
    raw_lines = [ln for ln in text.replace("\f", "\n").split("\n")
                 if ln.strip() and not re.match(r"^\s*Page \d+ of \d+\s*$", ln)]
    pars = _paragraphs(raw_lines)

    full = bc.norm(" ".join(raw_lines))
    attendance = []
    mp = re.search(r"MEMBERS PRESENT:(.*?)MEMBERS ABSENT:", full)
    if mp:
        members = re.split(r"\s(?=(?:Ms|Mr|Mrs|Dr)\. |Senator |Representative |Commissioner |Honorable )", mp.group(1))
        for chunk in members:
            m = re.search(r"^(.*?)\s*\(([^)]*\bItems?\b[^)]*)\)", chunk.strip())
            if not m:
                continue
            attendance.append({"member": m.group(1).strip(), "note": m.group(2), "refs": item_refs(m.group(2))})

    records = {}  # (no, sub) -> dict

    def rec(ref):
        return records.setdefault(ref, {"outcome": None, "motion": None, "conditions": [], "recusals": [],
                                        "speakers": [], "attendance": [], "discussed": False, "note": None})

    generic_om = re.compile(r"\b(?:was|were|would be|will be|is|are|to be)\s+(?:voluntarily\s+)?(%s)\b" % OUTCOME_WORDS)
    # In an item block the caption itself can say "which was approved by the voters", so only a
    # sentence about "the item" (or naming items) counts as the Commission's disposition there.
    thing_om = re.compile(r"\bthe %s\s+(?:was|were|would be|will be|is|are)\s+(?:voluntarily\s+)?(%s|adopted)\b" % (_THING, OUTCOME_WORDS))

    for par, block_item in pars:
        sents = _sentences(par)
        if not sents:
            continue
        if block_item is not None:
            subject = {(block_item, None)}
        else:
            subject = item_refs(sents[0]) if re.search(r"synopsis|status update|information|provided", sents[0]) else set()
        decided = set()
        motion = None
        motion_refs = set()
        unvoted = set()  # disposed without a motion: withdrawn, voluntarily deferred, no action
        for s in sents:
            mv = re.search(r"\s+moved\s+([^,]*)", s)
            mover = _person(s[:mv.start()]) if mv else None
            if mover:
                # Initials ("Senator J. Cameron Henry") must not end the name.
                par_i = re.sub(r"\b([A-Z])\.(?=\s)", "\\1\u2024", par)
                sec = re.search(r"[Ss]econded\s+by\s+(%s\s+[^,.;]+?)(?:,|\s+and\s+without|\s+and\s+the|\.|;|$)" % _TITLE, par_i)
                vote = "without objection" if "without objection" in s else (re.search(r"by a vote of [^,.;]+", s) or [None])[0]
                motion = {"moved_by": mover, "motion": mv.group(1).strip(), "seconded_by": sec.group(1).replace("\u2024", ".") if sec else None, "vote": vote}
                motion_refs = item_refs(s[mv.start():])
            if motion:
                rv = re.search(r"[Rr]oll [Cc]all [Vv]ote and the results were (.+?)(?:,? and the motion|[.;]|$)", s)
                if rv:
                    motion["vote"] = "roll call: " + rv.group(1).strip()
                ob = re.search(r"\bthere was an objection to the motion by (.+?)\.?$", s, re.I)
                if ob:
                    motion["objection"] = ob.group(1).strip()
            mp_ = re.search(r"\b[Tt]he motion (passed|carried)\b", s)
            if mp_ and motion:
                verb = re.match(r"(?:to )?(approv|defer|adopt|withdr|disapprov)", motion["motion"])
                word = {"approv": "approved", "defer": "deferred", "adopt": "adopted", "withdr": "withdrawn",
                        "disapprov": "disapproved"}.get(verb.group(1) if verb else None, "motion passed")
                for r in motion_refs or subject:
                    rec(r)["outcome"] = word
                    decided.add(r)
            # Older minutes copy the agenda stamp into the item block as a sentence of its own.
            st = re.search(r"\b((?:withdrawn|deferred|removed) (?:before|at|prior to) (?:the )?meeting)\b", s, re.I)
            if st and block_item is not None:
                for r in subject:
                    rec(r)["outcome"] = st.group(1).lower()
                    decided.add(r)
                    unvoted.add(r)
            if re.search(r"\bno action (?:was )?taken\b", s, re.I):
                for r in item_refs(s) or subject:
                    if r not in decided:
                        rec(r)["outcome"] = "no action taken"
                        decided.add(r)
                        unvoted.add(r)
            om = thing_om.search(s) or (None if block_item is not None and not item_refs(s) else generic_om.search(s))
            if om and motion and not motion["vote"]:
                motion["vote"] = "without objection" if "without objection" in s else (re.search(r"by a vote of [^,.;]+", s) or [None])[0]
            if re.search(r"\bthe minutes (?:of [^,]*? )?were approved", s, re.I):
                records["minutes"] = True
                continue
            if om:
                before = s[:om.start()]
                tgt = item_refs(before) or subject
                for r in tgt:
                    rec(r)["outcome"] = om.group(1)
                    decided.add(r)
                    (unvoted.add if motion is None else unvoted.discard)(r)
                for wm in re.finditer(r"(?:with (Items? [^,;]*?) being|(Items? \d[^,;]*?) which (?:was|were)) (%s)" % OUTCOME_WORDS, s):
                    for r in item_refs(wm.group(1) or wm.group(2)):
                        rec(r)["outcome"] = wm.group(3)
                        decided.add(r)
                        if wm.group(2):
                            unvoted.add(r)
            if re.search(r"\bmotion (?:failed|did not pass)", s):
                for r in subject:
                    rec(r)["outcome"] = "motion failed"
                    decided.add(r)
            if re.search(r"contingent|subject to|conditioned", s) and "moved" in s:
                cw = re.search(r"\bwith ([Ii]tems? .+?) being (?:contingent|subject|conditioned)", s)
                tgt = (item_refs(cw.group(1)) if cw else item_refs(s)) or subject
                for r in tgt:
                    rec(r)["conditions"].append(s)
            rc = re.search(r"\s+(?:was|were)\s+recused\s+from\s+(the [Ii]tems?|Items? .+?)(?:\.|$)", s)
            if rc:
                who = _person(s[:rc.start()]) or s[:rc.start()].strip()
                tgt = subject if rc.group(1).lower().startswith("the item") else item_refs(rc.group(1))
                for r in tgt:
                    rec(r)["recusals"].append(who)
            if re.search(r"spoke in (?:support|opposition)|read in cards|cards in (?:support|opposition)|information was provided by|Additional information", s):
                for r in subject:
                    rec(r)["speakers"].append(s)
        info_text = par if block_item is not None else sents[0]
        for r in subject:
            rec(r)["discussed"] = True
            if r not in decided and records[r]["outcome"] is None:
                if re.search(r"status update|provided information|information relative", info_text, re.I):
                    records[r]["outcome"] = "no vote (information only)"
        for r in decided - unvoted:
            if motion:
                rec(r)["motion"] = motion

    for a in attendance:
        for r in a["refs"]:
            rec(r)["attendance"].append("%s (%s)" % (a["member"], a["note"]))

    transcript = "verbatim transcript" in full and "available with the Bond Commission" in full
    return records, transcript


def _lookup(records, no, sub):
    r = records.get((no, sub))
    whole = records.get((no, None))
    if sub and whole:
        merged = dict(whole)
        if r:
            for k, v in r.items():
                if v:
                    merged[k] = v
        return merged
    return r or whole


def outcome_for(row, cache, yes):
    if not row.get("minutes"):
        sys.exit("no minutes posted for the %s meeting" % row["meeting_date"])
    st, url = stage_url(row, None)
    if st == "preliminary":
        print("warning: only the Preliminary agenda is posted; item numbers may not match the minutes", file=sys.stderr)
    bc.guard([u for u in (url, row["minutes"]) if u], cache, "sbc", yes)
    agenda = agenda_for(row, st, cache, None)
    mtext = bc.pdf_text(bc.get_pdf(row["minutes"], cache, "sbc"))
    if not bc.has_text_layer(mtext):
        sys.exit("the %s minutes have no text layer (scanned): OCR %s with bayou:document-ocr" % (row["meeting_date"], row["minutes"]))
    records, transcript = parse_minutes(mtext)
    if not any(v.get("outcome") for k, v in records.items() if k != "minutes"):
        print("warning: no outcome sentences parsed from the minutes; read them directly: %s" % row["minutes"], file=sys.stderr)
    out = []
    minutes_ok = records.pop("minutes", False)
    for it in agenda["items"]:
        r = _lookup(records, it["item_no"], it["sub_item"])
        if minutes_ok and it["raw_text"].startswith("Approval of the minutes"):
            r = {"outcome": "approved", "discussed": True}
        status = (r or {}).get("outcome")
        stamp = it["status_stamp"]
        # The Final agenda's stamp and the minutes can disagree (2024-05-16: stamped WITHDRAWN AT
        # MEETING, minutes say "would be deferred"). The minutes are the adopted record, so they win,
        # but both are reported so the reader can check the PDF.
        conflict = bool(status and stamp and stamp.split()[0].lower() not in status)
        if not status:
            if it["status_stamp"]:
                status = it["status_stamp"].lower()
            elif r and r.get("discussed"):
                status = "discussed, no vote recorded"
            else:
                status = "not recorded in minutes"
        out.append(dict(it, outcome=status, agenda_stamp=stamp, stamp_conflict=conflict, motion=(r or {}).get("motion"), conditions=(r or {}).get("conditions", []),
                        recusals=(r or {}).get("recusals", []), speakers=(r or {}).get("speakers", []),
                        attendance=(r or {}).get("attendance", []), minutes_url=row["minutes"]))
    return {"meeting_date": row["meeting_date"].isoformat(), "agenda_stage": st, "agenda_url": url,
            "minutes_url": row["minutes"], "verbatim_transcript_held_by_sbc": transcript, "items": out}


# ---------------------------------------------------------------- output

def money(n):
    return "$%s" % format(n, ",") if n is not None else ""


def label(it):
    return "%d%s" % (it["item_no"], "(%s)" % it["sub_item"] if it["sub_item"] else "")


def md_items(items, extra=None):
    cols = ["Meeting", "Item", "Docket", "Issuer", "Project caption", "Par (not exceeding)", "Bond type", "Vol. cap", "Stamp"] + (extra or [])
    print("| " + " | ".join(cols) + " |")
    print("|" + "---|" * len(cols))
    for it in items:
        vals = [it["meeting_date"], label(it), it["docket"] or "", it["issuer"] or it["raw_text"][:60], it["project_caption"] or "",
                money(it["par_amount"]), it["bond_type"] or "", "yes" if it["volume_cap"] else "", it["status_stamp"] or ""]
        for e in extra or []:
            vals.append(str(it.get(e.lower(), "")))
        print("| " + " | ".join(v.replace("|", "/") for v in vals) + " |")


def jdump(obj):
    print(json.dumps(obj, indent=2, default=lambda o: o.isoformat() if hasattr(o, "isoformat") else sorted(o)))


def main():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true")
    common.add_argument("--yes", action="store_true", help="allow downloads over the size guard")
    common.add_argument("--cache", default=bc.DEFAULT_CACHE)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    m = sp.add_parser("meetings", parents=[common])
    m.add_argument("--year", type=int)
    m.add_argument("--archive", action="store_true", help="include 2023-2025 from the archive page")
    a = sp.add_parser("agenda", parents=[common])
    a.add_argument("date", help="MM/DD/YYYY, YYYY-MM-DD, latest, or next")
    a.add_argument("--stage", choices=STAGES)
    a.add_argument("--archive", action="store_true")
    a.add_argument("--all", action="store_true", help="include non-docket items (roll call, lines of credit, ...)")
    s = sp.add_parser("search", parents=[common])
    s.add_argument("terms", nargs="*")
    s.add_argument("--docket")
    s.add_argument("--from", dest="date_from")
    s.add_argument("--to", dest="date_to")
    o = sp.add_parser("outcome", parents=[common])
    o.add_argument("date")
    o.add_argument("--archive", action="store_true")
    args = ap.parse_args()

    try:
        if args.cmd == "meetings":
            rows = load_meetings(args.archive)
            if args.year:
                rows = [r for r in rows if r["meeting_date"].year == args.year]
            if args.json:
                return jdump(rows)
            print("| Meeting | Apps due | 10-day deadline | Election | Preliminary | Posted | Final | Minutes |")
            print("|---|---|---|---|---|---|---|---|")
            for r in rows:
                f = lambda k: ("[pdf](%s)" % r[k]) if r[k] else ""  # noqa: E731
                d = lambda k: r[k].isoformat() if r[k] else ""  # noqa: E731
                print("| %s | %s | %s | %s | %s | %s | %s | %s |" % (d("meeting_date"), d("apps_due"), d("deadline"), d("election_date"),
                                                                     f("preliminary"), f("posted"), f("final"), f("minutes")))
            return
        if args.cmd == "agenda":
            row = pick_meeting(load_meetings(args.archive), args.date)
            ag = agenda_for(row, args.stage, args.cache, args.yes)
            if ag is None:
                sys.exit("no %sagenda posted yet for %s; the Preliminary usually appears about one week before"
                         % (args.stage + " " if args.stage else "", row["meeting_date"]))
            if not args.all:
                ag["items"] = [i for i in ag["items"] if i["docket"]]
            if args.json:
                return jdump(ag)
            print("SBC meeting %s, %s agenda: %s\n" % (ag["meeting_date"], ag["stage"], ag["url"]))
            md_items(ag["items"])
            if ag["public_comment"]:
                print("\nPublic comment (from the agenda): " + ag["public_comment"])
            return
        if args.cmd == "search":
            if not args.terms and not args.docket:
                sys.exit("give search terms or --docket")
            today = datetime.date.today()
            d0 = bc.arg_date(args.date_from) if args.date_from else datetime.date(today.year, 1, 1)
            d1 = bc.arg_date(args.date_to) if args.date_to else today + datetime.timedelta(days=60)
            rows = [r for r in load_meetings(d0.year < today.year) if d0 <= r["meeting_date"] <= d1]
            urls = [stage_url(r)[1] for r in rows if stage_url(r)[1]]
            bc.guard(urls, args.cache, "sbc", args.yes)
            hits, searched, unparsed = [], [], []
            pats = [re.compile(re.escape(t), re.I) for t in args.terms]
            for r in rows:
                ag = agenda_for(r, None, args.cache, None)
                if ag is None:
                    continue
                if ag["parse_problem"]:
                    unparsed.append("%s (%s): %s %s" % (ag["meeting_date"], ag["stage"], ag["parse_problem"], ag["url"]))
                    continue
                searched.append("%s (%s)" % (ag["meeting_date"], ag["stage"]))
                for it in ag["items"]:
                    if args.docket and (it["docket"] or "").upper() != args.docket.upper():
                        continue
                    if pats and not any(p.search(it["raw_text"]) for p in pats):
                        continue
                    hits.append(it)
            if args.json:
                return jdump({"searched": searched, "not_searched": unparsed, "hits": hits})
            print("Searched %d SBC agendas: %s\n" % (len(searched), ", ".join(searched) or "none"))
            if unparsed:
                print("NOT searched (could not parse, so silence here means nothing):\n" + "\n".join("- " + u for u in unparsed) + "\n")
            if not hits:
                print("No matching docket items in these agendas. That is not evidence the bond was never submitted:"
                      " it may be on a later agenda, under another name, or never routed to the SBC.")
                return
            md_items(hits)
            print()
            for it in hits:
                print("- %s item %s (%s agenda, %s): %s" % (it["meeting_date"], label(it), it["stage"], it["url"], it["raw_text"]))
            return
        if args.cmd == "outcome":
            row = pick_meeting(load_meetings(args.archive), args.date)
            res = outcome_for(row, args.cache, args.yes)
            if args.json:
                return jdump(res)
            print("SBC meeting %s. Items numbered from the %s agenda (%s); outcomes from the minutes (%s).\n"
                  % (res["meeting_date"], res["agenda_stage"], res["agenda_url"], res["minutes_url"]))
            print("| Item | Docket | Issuer (caption) | Outcome | Motion | Recusals |")
            print("|---|---|---|---|---|---|")
            for it in res["items"]:
                mo = it["motion"]
                mtxt = "%s / %s, %s" % (mo["moved_by"], mo["seconded_by"] or "?", mo["vote"] or "vote not stated") if mo else ""
                who = (it["issuer"] or it["raw_text"][:50]) + (" (%s)" % it["project_caption"] if it["project_caption"] else "")
                otxt = it["outcome"] + (" (minutes; Final agenda stamp: %s)" % it["agenda_stamp"] if it["stamp_conflict"] else "")
                if mo and it["outcome"] == "motion passed":
                    mtxt += "; motion: " + mo["motion"]
                if mo and mo.get("objection"):
                    mtxt += "; objection by " + mo["objection"]
                print("| %s | %s | %s | %s | %s | %s |" % (label(it), it["docket"] or "", who.replace("|", "/"), otxt, mtxt,
                                                          ", ".join(it["recusals"])))
            notes = [it for it in res["items"] if it["speakers"] or it["conditions"] or it["attendance"]]
            if notes:
                print("\n## Discussion recorded in the minutes\n")
                for it in notes:
                    print("**Item %s %s**" % (label(it), it["docket"] or ""))
                    for x in it["conditions"]:
                        print("- condition: " + x)
                    for x in it["attendance"]:
                        print("- attendance: " + x)
                    for x in it["speakers"]:
                        print("- " + x)
                    print()
            if res["verbatim_transcript_held_by_sbc"]:
                print("The minutes summarise; they state a verbatim transcript is held by the Bond Commission"
                      " (request it with bayou:la-public-records-request).")
    except bc.GuardStop as e:
        print(str(e), file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
