"""CourtListener v4 opinion search for the Louisiana Supreme Court (`la`) and Courts of Appeal (`lactapp`).

CourtListener files all five circuits under the single court ID `lactapp`, so the circuit is
recovered from the docket format and the download domain (court_common.parse_docket).
"""
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import court_common as cc

API = "https://www.courtlistener.com/api/rest/v4/search/"
SITE = "https://www.courtlistener.com"
STORAGE = "https://storage.courtlistener.com/"
# Anonymous access allows 5 requests a minute and 50 an hour; a token raises that to thousands an hour.
ANON_GAP = 13
TOKEN_GAP = 1
# Waiting out the per-minute limit is worth it; waiting out the hourly one (up to 60 min) is not.
MAX_WAIT = 90
RESULT_TTL_DAYS = 1


class RateLimited(Exception):
    pass


def token():
    tok = os.environ.get("COURTLISTENER_TOKEN")
    if tok:
        return tok.strip()
    path = os.path.expanduser("~/.claude/bayou-credentials.md")
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                m = re.match(r"\s*[-*]?\s*CourtListener token\s*:\s*`?([0-9a-f]{20,})`?", line, re.I)
                if m:
                    return m.group(1)
    except OSError:
        pass
    return None


def _throttle(cache, gap):
    # A stamp file so separate script invocations share one rate budget.
    stamp = os.path.join(cc.sub_dir(cache, "cl"), "last_call")
    try:
        wait = gap - (time.time() - os.path.getmtime(stamp))
    except OSError:
        wait = 0
    if wait > 0:
        print("courtlistener: waiting %.0fs for the rate limit" % wait, file=sys.stderr)
        time.sleep(wait)
    with open(stamp, "w") as fh:
        fh.write(str(time.time()))


def search(params, cache=cc.DEFAULT_CACHE, max_results=20):
    """Run one v4 search (type=o) and return (count, [normalized records]).

    Responses are cached for a day: the anonymous hourly budget is small, and reruns of the same
    verify-cite should not spend it.
    """
    tok = token()
    p = {"type": "o", "order_by": "score desc"}
    p.update({k: v for k, v in params.items() if v})
    url = API + "?" + urllib.parse.urlencode(sorted(p.items()))
    hit = os.path.join(cc.sub_dir(cache, "cl"), hashlib.sha1(url.encode()).hexdigest()[:20] + ".json")
    if cc.fresh(hit, RESULT_TTL_DAYS):
        with open(hit) as fh:
            data = json.load(fh)
    else:
        data = _get(url, tok, cache)
        cc.write_atomic(hit, json.dumps(data))
    recs = [record(r) for r in (data.get("results") or [])[:max_results]]
    return data.get("count") or 0, recs


def _get(url, tok, cache):
    headers = {"Authorization": "Token " + tok} if tok else {}
    for attempt in range(4):
        _throttle(cache, TOKEN_GAP if tok else ANON_GAP)
        try:
            return json.loads(cc.fetch(url, headers=headers, timeout=60))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            if e.code != 429 or attempt == 3:
                raise RuntimeError("CourtListener HTTP %d: %s" % (e.code, body[:200]))
            m = re.search(r"available in (\d+) seconds", body)
            wait = int(m.group(1)) + 1 if m else 60
            if wait > MAX_WAIT:
                raise RateLimited("CourtListener rate limit reached (%s); available again in %d min. Results so far are "
                                  "cached. Set COURTLISTENER_TOKEN or add 'CourtListener token: <token>' to "
                                  "~/.claude/bayou-credentials.md to lift it." % (
                                      re.search(r"exceeded: ([^.]+)", body).group(1) if "exceeded:" in body else "429",
                                      wait // 60 + 1))
            print("courtlistener: 429, retrying in %ds" % wait, file=sys.stderr)
            time.sleep(wait)


def record(r):
    op = (r.get("opinions") or [{}])[0]
    pdf = op.get("download_url") or (STORAGE + op["local_path"] if op.get("local_path") else None)
    if pdf and pdf.startswith("http://www.lasc.org"):
        # lasc.org answers plain http with a 522.
        pdf = "https://" + pdf[len("http://"):]
    court = r.get("court_id")
    d = cc.parse_docket(r.get("docketNumber"), court=court, url=op.get("download_url"))
    return {
        "source": "courtlistener",
        "court_id": court,
        "circuit": d["circuit"] if d else (0 if court == "la" else None),
        "court": cc.court_label(d["circuit"] if d else (0 if court == "la" else None)),
        "caption": cc.clean(r.get("caseName")),
        "docket_raw": r.get("docketNumber"),
        "docket": d,
        "key": d["key"] if d else "cl:%s" % r.get("cluster_id"),
        "decision_date": (r.get("dateFiled") or "")[:10] or None,
        "citations": r.get("citation") or [],
        "cluster_id": r.get("cluster_id"),
        "cite_count": r.get("citeCount"),
        "panel": r.get("judge") or None,
        "url": SITE + r["absolute_url"] if r.get("absolute_url") else None,
        "pdf": pdf,
    }


def courts_for(circuit):
    """`court` parameter for a --court choice."""
    if circuit == "la":
        return "la"
    if circuit == "all":
        return "la lactapp"
    return "lactapp"


def cite_query(cite):
    """`citation:("452 So. 2d 1152")` -- the citation-lookup endpoint needs a token, search does not."""
    m = re.match(r"\s*(\d+)\s+(So\.?)\s*(2d|3d)?\s*(\d+)", cite, re.I)
    if not m:
        return None
    vol, rep, ser, page = m.groups()
    norm = "%s So. %s%s" % (vol, (ser + " ") if ser else "", page)
    return 'citation:("%s")' % norm, norm
