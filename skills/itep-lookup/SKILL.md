---
name: itep-lookup
description: Look up Louisiana Industrial Tax Exemption Program (ITEP) awards and applications
allowed-tools: WebFetch, WebSearch, Bash, AskUserQuestion
---

# Louisiana ITEP Lookup

Research Industrial Tax Exemption Program (ITEP) awards and applications in Louisiana. ITEP grants up to 80% property tax abatement for up to 10 years on new manufacturing investments. Managed by Louisiana Economic Development (LED).

## What ITEP data reveals

- Which industrial facilities have received or applied for tax exemptions
- The dollar value of investment being exempted
- Which parishes and school boards are giving up property tax revenue
- Whether local government bodies (parish council, school board) approved the exemption
- Renewal and modification history

## Primary sources

ITEP data is **not available through a single searchable API**. Use the following approaches in order:

---

### 1. LED FastLane (official application portal)

New-format ITEP applications (post-2016 rules) go through FastLane NextGen:

```
WebFetch url="https://fastlaneng.louisianaeconomicdevelopment.com/public/itep" prompt="List any publicly searchable ITEP applications or awards. What search fields are available?"
```

If that doesn't load, try:
```
WebFetch url="https://fastlaneng.louisianaeconomicdevelopment.com/" prompt="Find ITEP-related search or lookup tools. What public data is available?"
```

---

### 2. Louisiana Legislative Auditor public reports

The LLA publishes ITEP fiscal impact reports with company-level data:

```bash
curl -s "https://app2.lla.state.la.us/publicreports.nsf/0/cc7686f9911ead8b862588d80069d4bb/\$file/00028368d.pdf" \
  -o /tmp/itep_report.pdf 2>/dev/null && echo "Downloaded"
```

Or use WebSearch to find the most recent LLA ITEP report:
```
WebSearch query="Louisiana ITEP industrial tax exemption program statistics fiscal impact site:lla.state.la.us"
```

---

### 3. LED public data and press releases

Search for specific company ITEP awards:
```
WebSearch query="Louisiana ITEP 'industrial tax exemption' COMPANY_NAME award site:opportunitylouisiana.gov"
```

Or search the LED website directly:
```
WebFetch url="https://www.opportunitylouisiana.gov/incentive/industrial-tax-exemption" prompt="List any searchable database links, public data downloads, or ITEP application records mentioned on this page."
```

---

### 4. Parish tax records and board minutes

For specific parish-level ITEP decisions (local governing authority approval is required post-2016):
- Search parish council meeting minutes for ITEP votes
- Check parish assessor offices for exemption certificates

Example: Search for St. Charles Parish ITEP approvals:
```
WebSearch query="St. Charles Parish ITEP 'industrial tax exemption' approval 2020 2021 2022 2023 2024"
```

---

### 5. News and investigative sources

Useful databases for ITEP coverage:
- **The Lens** (New Orleans): extensive ITEP coverage — `thelensnola.org`
- **ProPublica / IPUMS**: may have structured ITEP data
- **Louisiana Budget Project**: policy analysis with ITEP breakdowns

```
WebSearch query="Louisiana ITEP COMPANY_NAME site:thelensnola.org"
```

---

## What to ask for

When the user asks about ITEP for a specific company or facility:

1. **What they want**: Award amount? Years remaining? Parish impact? Renewal status?
2. **Company name and location**: Needed to search FastLane and news sources
3. **Time period**: Recent award vs. historical data

---

## How to present results

- **Award summary**: Company | Parish | Investment $ | Exemption % | Years | Status
- Flag whether **local governing bodies approved** (required post-2016 for new applications)
- Note the **jobs created** and **capital investment** figures (required for application)
- Highlight the **foregone tax revenue** to schools and parishes if reported
- Link to source documents (FastLane record, LLA report, news article)

---

## Key facts about ITEP

- Program: Up to **80% property tax abatement** on new manufacturing investment
- Duration: Up to **10 years** (5-year initial + 5-year renewal)
- Eligibility: Manufacturers (NAICS codes 31–33)
- Post-2016 rules: Local governing authorities (parish council, school board, sheriff) must approve; each can independently deny
- Application: Must be filed **before construction begins**
- Parish relevance: St. Charles Parish contains Waterford 3 (nuclear) and several chemical plants; these are major ITEP recipients

$ARGUMENTS
