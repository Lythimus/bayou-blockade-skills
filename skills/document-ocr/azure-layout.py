"""Submit a PDF to Azure Document Intelligence `prebuilt-layout` and save the raw analyzeResult.

Direct REST against the Document Intelligence v4.0 GA API -- no SDK. The plan considered the
third-party `asklokesh/azure-mcp-server` MCP connector and rejected it: a third-party server means
inheriting someone else's output shape (the one thing worth controlling tightly for this merge),
and its tool surface can't be verified up front. SKILL.md documents that decision and the raw-key
fallback for a user who does have a real Azure MCP connector wired.

Pinned to api-version=2024-11-30 (GA). Do not bump without re-checking the response shape against
adapt_azure() in merge-canonical.py, which this script's output feeds directly and unmodified --
this script does no reshaping of its own.

Usage: azure-layout.py <pdf> <out.json> [--endpoint URL] [--key KEY]

--endpoint/--key default to the AZURE_DOCINTEL_ENDPOINT / AZURE_DOCINTEL_KEY environment
variables (read from ~/.claude/bayou-credentials.md by the caller, same idiom as
adsb-flight-search's RAPIDAPI_KEY).

POSTs the raw PDF bytes to documentModels/prebuilt-layout:analyze, reads the Operation-Location
header from the 202 response, polls it until status == "succeeded", and writes the full response
body (which carries analyzeResult) to <out.json> verbatim.

This script performs no cost confirmation of its own -- it submits whatever PDF it is given,
unconditionally, and Azure bills per page on submission. That confirmation is a separate gate one
layer up, in SKILL.md's `--azure` handling (AskUserQuestion, the pacer-case-search house pattern),
which must always run before this script is invoked.

**Resumable by design, because Azure bills at submission, not at poll completion.** The
Operation-Location from the 202 is persisted to `<out.json>.operation` before polling starts. If
polling is interrupted for any reason (timeout, network blip, killed process), re-running this exact
command resumes from that saved URL instead of submitting -- and billing -- again; the result stays
retrievable from that URL for ~24h. Only delete `<out.json>.operation` if a fresh submission is
actually intended.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

API_VERSION = "2024-11-30"
POLL_INTERVAL_SECONDS = 10
POLL_TIMEOUT_SECONDS = 3600


def submit(endpoint, key, pdf_bytes):
    endpoint = endpoint.rstrip("/")
    url = (
        f"{endpoint}/documentintelligence/documentModels/prebuilt-layout:analyze"
        f"?api-version={API_VERSION}"
    )
    print(f"[OCR] azure submitting {len(pdf_bytes)/1e6:.1f} MB ...", file=sys.stderr, flush=True)
    req = urllib.request.Request(
        url,
        data=pdf_bytes,
        method="POST",
        headers={
            "Ocp-Apim-Subscription-Key": key,
            "Content-Type": "application/pdf",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            operation_location = resp.headers.get("Operation-Location")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise SystemExit(f"[OCR] azure submit failed: HTTP {e.code}\n{body}")
    if not operation_location:
        raise SystemExit("[OCR] azure submit succeeded but no Operation-Location header was returned")
    return operation_location


def poll(operation_location, key, timeout_seconds):
    headers = {"Ocp-Apim-Subscription-Key": key}
    deadline = time.monotonic() + timeout_seconds
    start = time.monotonic()
    while time.monotonic() < deadline:
        req = urllib.request.Request(operation_location, headers=headers)
        try:
            with urllib.request.urlopen(req) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            raise SystemExit(f"[OCR] azure poll failed: HTTP {e.code}\n{err_body}")
        status = body.get("status")
        elapsed = int(time.monotonic() - start)
        print(f"[OCR] azure status={status} ({elapsed}s)", file=sys.stderr, flush=True)
        if status == "succeeded":
            return body
        if status == "failed":
            raise SystemExit(f"[OCR] azure analysis failed: {json.dumps(body.get('error', body))}")
        time.sleep(POLL_INTERVAL_SECONDS)
    raise SystemExit(
        f"[OCR] azure analysis did not complete within {timeout_seconds}s. NOT re-submitting -- "
        f"re-run this same command to resume polling the saved operation (already billed)."
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf")
    parser.add_argument("out_json")
    parser.add_argument("--endpoint", default=os.environ.get("AZURE_DOCINTEL_ENDPOINT"))
    parser.add_argument("--key", default=os.environ.get("AZURE_DOCINTEL_KEY"))
    parser.add_argument(
        "--timeout",
        type=int,
        default=POLL_TIMEOUT_SECONDS,
        help=f"poll timeout in seconds (default {POLL_TIMEOUT_SECONDS})",
    )
    args = parser.parse_args()

    if not args.endpoint or not args.key:
        print(
            "[OCR] FAIL setup: Azure endpoint/key not provided (--endpoint/--key or "
            "AZURE_DOCINTEL_ENDPOINT/AZURE_DOCINTEL_KEY env vars). See "
            "~/.claude/bayou-credentials.md.",
            file=sys.stderr,
        )
        sys.exit(1)

    op_path = args.out_json + ".operation"
    if os.path.exists(op_path):
        operation_location = open(op_path, encoding="utf-8").read().strip()
        print("[OCR] azure resuming saved operation (no re-submit, no re-bill)", file=sys.stderr)
    else:
        with open(args.pdf, "rb") as f:
            pdf_bytes = f.read()
        operation_location = submit(args.endpoint, args.key, pdf_bytes)
        os.makedirs(os.path.dirname(op_path) or ".", exist_ok=True)
        with open(op_path, "w", encoding="utf-8") as f:
            f.write(operation_location)
        print(f"[OCR] azure billed; operation saved -> {op_path}", file=sys.stderr, flush=True)

    result = poll(operation_location, args.key, args.timeout)

    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(result, f)

    ar = result.get("analyzeResult", {})
    print(
        f"[OCR] azure done -> {args.out_json} "
        f"(pages={len(ar.get('pages', []))} tables={len(ar.get('tables', []))})",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
