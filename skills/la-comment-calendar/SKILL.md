---
name: la-comment-calendar
description: Find currently open Louisiana public comment periods on draft permits (LDEQ) and state agency rulemaking notices (Louisiana Register), with deadlines
allowed-tools: Bash, AskUserQuestion
---

# Louisiana Public Comment Calendar

Combines two sources into one "what's open for comment right now" view: LDEQ's live draft-permit public-notice list, and the Louisiana Register's monthly rulemaking notices (Notice of Intent / Emergency Rule filings, which carry their own comment windows under the state Administrative Procedure Act). No API key required for either.

The bookmarked DCE ("Dockets/hearing calendar") URL from the original bookmark list returned a 404 and no live replacement was found on `doa.la.gov` — LDEQ's public-notices page below is the actual live, structured source for permit comment periods and supersedes that bookmark.

## Parsing arguments

The user may provide:
- A **facility/company name** or **parish** to filter for (e.g. "Shell Norco", "St. Charles Parish")
- A **medium** filter (air, water, waste)
- Nothing — in which case, list everything currently open

## Step 1: LDEQ draft-permit public notices (the primary, fastest-moving source)

```bash
curl -s "https://www.deq.louisiana.gov/public-notices" 2>/dev/null | python3 -c "
import sys, re, html
from urllib.parse import urlparse, parse_qs

page = sys.stdin.read()
urls = re.findall(r'https://internet\.deq\.louisiana\.gov/portal/DIVISIONS/PPPSD/PUBLIC-COMMENTS\?[^\"\\x27]+', page)

for u in urls:
    q = parse_qs(urlparse(u).query)
    name = html.unescape(q.get('AIName', [''])[0]).strip()
    subject = html.unescape(q.get('Subject', [''])[0]).strip()
    ai = q.get('AI', [''])[0]
    permit = q.get('PermitNumber', [''])[0]
    media = q.get('Media', [''])[0]
    deadline = q.get('DL', [''])[0]
    print(f'{deadline} | {media} | {name} | {subject} | AI {ai} | Permit {permit}')
    print(f'  {u}')
"
```

This page lists **currently open** LDEQ draft-permit comment periods directly — it is not paginated/JS-driven, so a single fetch captures everything live at request time. Each entry's `AI` number cross-references directly into `bayou:ldeq-edms-search` (search by AI number) and `bayou:ldeq-permit-status` for the underlying permit application. `DL` is the comment deadline (MM/DD/YYYY, format is inconsistent in the source — sometimes zero-padded, sometimes not; normalize before sorting). The comment-submission URL itself (`internet.deq.louisiana.gov/portal/.../PUBLIC-COMMENTS?...`) is where the user would actually submit a comment — hand it to them directly rather than trying to automate submission.

Filter client-side on `AIName`/parish/media after fetching — there is no server-side query parameter on this page.

## Step 2: Louisiana Register rulemaking notices (monthly, broader scope)

The Register publishes monthly as a single DOCX per issue containing every agency's Notices of Intent, Emergency Rules, and adopted Rules for that month — including comment-period language and deadlines in the notice text itself (LDEQ NOIs, but also LDWF, DNR, and other agencies).

```bash
curl -s "https://www.doa.la.gov/doa/osr/louisiana-register/" 2>/dev/null | python3 -c "
import sys, re
html_src = sys.stdin.read()
for m in re.finditer(r'href=\"(/media/[^\"]+\.docx)\"[^>]*>([^<]{0,60})', html_src, re.I):
    href, text = m.groups()
    print(f'https://www.doa.la.gov{href}  |  {text.strip()}')
"
```

Download the current month's issue and extract text the same way `bayou:lac33-search` handles LAC DOCX files (convert via `docx2txt`/`python-docx`, or `pandoc` if available), then search for the agency/facility/topic of interest and any "comments will be accepted through" / "the public comment period ends" language in the surrounding paragraph.

```bash
curl -s -L "https://www.doa.la.gov/media/lfhpaf4e/2607.docx" -o /tmp/la-register-current.docx 2>/dev/null

# python-docx is not installed by default — use pandoc instead:
pandoc -t plain /tmp/la-register-current.docx | python3 -c "
import sys, re
text = sys.stdin.read()
for m in re.finditer(r'.{200}(comment period|comments will be accepted|comments must be received).{200}', text, re.I):
    print(m.group())
    print('---')
"
```

If `command -v pandoc` comes up empty, probe `/opt/homebrew/bin`, `/usr/local/bin`, `/usr/bin`
before concluding it is absent — a non-interactive shell's `PATH` often omits Homebrew.

If `pandoc` genuinely isn't available, unzip the `.docx` directly and strip tags from `word/document.xml` (verified working fallback):

```bash
cd /tmp && unzip -o -q la-register-current.docx -d la-register-extract
python3 -c "
import re
with open('/tmp/la-register-extract/word/document.xml', encoding='utf-8') as f:
    xml = f.read()
text = re.sub(r'<[^>]+>', ' ', xml)
text = re.sub(r'\s+', ' ', text)
for m in re.finditer(r'comment period|comments will be accepted|comments must be received', text, re.I):
    print(text[max(0, m.start()-150):m.start()+150])
    print('---')
"
```

---

## Presenting the results

1. **Sort by deadline ascending** — nearest deadline first, across both sources combined.
2. **Table**: Deadline | Source (LDEQ / LA Register) | Facility/Agency | Subject | Link
3. Flag anything closing within 14 days prominently — that's the actionable urgency window.
4. For LDEQ entries, note the AI number and suggest the cross-reference: "Run `bayou:ldeq-edms-search` on AI [N] for the underlying permit file."
5. State the retrieval timestamp — this list changes daily as LDEQ posts and closes notices.

### Citation format

> **LDEQ Public Notice**, AI [N], [facility], "[subject]", comment deadline [DL], source: [LDEQ Public Notices](https://www.deq.louisiana.gov/public-notices) (retrieved 2026-07-21).
>
> **Louisiana Register**, [Month Year] issue, [agency] Notice of Intent, source: [LA Office of State Register](https://www.doa.la.gov/doa/osr/louisiana-register/) (retrieved 2026-07-21).

$ARGUMENTS
