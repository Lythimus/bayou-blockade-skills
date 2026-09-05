#!/usr/bin/env bash
# Remote OCR_BACKEND: Surya geometry + olmOCR/Chandra readers, run on holos via SSH, never
# locally. See remote/ocr-node.sh for what runs on the box and references/remote-setup.md for
# how it gets provisioned. This script needs zero local model access -- no reportlab, no
# poppler, no conda env -- only ssh/rsync and stdlib-only python3 (merge-canonical.py prefers
# rapidfuzz if installed, falls back to difflib otherwise).
#
# Usage: backend-remote.sh <IN_DIR_OR_PDF> <OUT_TXT> <WORK>
# Emits the same [OCR] skip|done|FAIL|ALL DONE vocabulary as ocr-pipeline.sh's local loop.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOC_OCR_DIR="$(dirname "$SCRIPT_DIR")"
PROBE="$SCRIPT_DIR/probe.sh"
NODE_SCRIPT="$DOC_OCR_DIR/remote/ocr-node.sh"
MERGE="$DOC_OCR_DIR/merge-canonical.py"
VALIDATE="$DOC_OCR_DIR/validate-surya-json.py"
RENDERTXT="$DOC_OCR_DIR/render-txt.py"
COVERAGE="$DOC_OCR_DIR/check-reader-coverage.py"

IN="${1:?Usage: backend-remote.sh <IN_DIR_OR_PDF> <OUT_TXT> <WORK>}"
OUT_TXT="${2:?Usage: backend-remote.sh <IN_DIR_OR_PDF> <OUT_TXT> <WORK>}"
WORK="${3:?Usage: backend-remote.sh <IN_DIR_OR_PDF> <OUT_TXT> <WORK>}"

CREDFILE="${BAYOU_CREDENTIALS:-$HOME/.claude/bayou-credentials.md}"
cred() {
  [ -f "$CREDFILE" ] || return 1
  grep "^$1:" "$CREDFILE" | head -1 | cut -d' ' -f2-
}
OCR_SSH_HOST="${OCR_SSH_HOST:-$(cred OCR_SSH_HOST)}"
OCR_REMOTE_ROOT="${OCR_REMOTE_ROOT:-$(cred OCR_REMOTE_ROOT)}"
OCR_REMOTE_ROOT="${OCR_REMOTE_ROOT:-ocr}"

# --- Probe first -- fail loudly and distinguishably rather than let rsync/ssh time out weirdly.
if ! "$PROBE" >&2; then
  exit 1
fi

mkdir -p "$OUT_TXT" "$WORK/canonical" "$WORK/results" "$WORK/remote" "$WORK/remote-out"

# --- Work list: skip a stem when .txt is non-empty AND canonical/<stem>.json parses -----------
FILELIST="$(mktemp)"
trap 'rm -f "$FILELIST"' EXIT
if [ -f "$IN" ]; then
  printf '%s\0' "$IN" >"$FILELIST"
else
  find "$IN" -type f -iname '*.pdf' -print0 >"$FILELIST"
fi

STEMS=()
PDFS=()
declare -A PDF_FOR_STEM
while IFS= read -r -d '' pdf; do
  stem="$(basename "$pdf")"
  stem="${stem%.[Pp][Dd][Ff]}"
  out_file="$OUT_TXT/$stem.txt"
  canonical_json="$WORK/canonical/$stem.json"
  if [ -s "$out_file" ] && python3 -c "import json,sys; json.load(open(sys.argv[1]))" \
      "$canonical_json" >/dev/null 2>&1; then
    echo "[OCR] skip $stem"
    continue
  fi
  STEMS+=("$stem")
  PDFS+=("$pdf")
  PDF_FOR_STEM["$stem"]="$pdf"
done <"$FILELIST"

TOTAL="${#STEMS[@]}"
if [ "$TOTAL" -eq 0 ]; then
  echo "[OCR] ALL DONE (0 files) -> $OUT_TXT"
  exit 0
fi

# --- Resume-or-launch a remote run -------------------------------------------------------------
RUN_ID_FILE="$WORK/remote/run_id"
CURSOR_FILE="$WORK/remote/cursor"

launch_new_run() {
  RUN_ID="$(date +%Y%m%d-%H%M%S)-$$"
  echo "$RUN_ID" >"$RUN_ID_FILE"
  echo 0 >"$CURSOR_FILE"
  REMOTE_RUN_DIR="$OCR_REMOTE_ROOT/runs/$RUN_ID"

  echo "[OCR] remote: starting run $RUN_ID on $OCR_SSH_HOST"
  ssh "$OCR_SSH_HOST" "mkdir -p '$REMOTE_RUN_DIR/in' '$REMOTE_RUN_DIR/out' '$OCR_REMOTE_ROOT/bin'"
  rsync -az --partial "$NODE_SCRIPT" "$OCR_SSH_HOST:$OCR_REMOTE_ROOT/bin/ocr-node.sh"
  rsync -az --partial "${PDFS[@]}" "$OCR_SSH_HOST:$REMOTE_RUN_DIR/in/"
  # No `cd` here -- these paths are relative to remote $HOME, and a `cd` into $REMOTE_RUN_DIR
  # before referencing them (as an earlier version did) makes them resolve doubly-nested under
  # itself instead (reproduced: "ocr/bin/ocr-node.sh: No such file or directory" because it
  # became ocr/runs/<id>/ocr/bin/ocr-node.sh). $OCR_REMOTE_ROOT/$REMOTE_RUN_DIR are constructed
  # locally (fixed root name + date-based run id), never contain spaces, so no quoting needed.
  ssh "$OCR_SSH_HOST" \
    "setsid nohup bash \$HOME/$OCR_REMOTE_ROOT/bin/ocr-node.sh \$HOME/$REMOTE_RUN_DIR >\$HOME/$REMOTE_RUN_DIR/node.stdout 2>&1 & echo \$! >\$HOME/$REMOTE_RUN_DIR/PID"
}

resume_run() {
  RUN_ID="$(cat "$RUN_ID_FILE")"
  REMOTE_RUN_DIR="$OCR_REMOTE_ROOT/runs/$RUN_ID"

  # A prior run's directory is deleted from the remote box once its results are confirmed landed
  # locally (data-hygiene policy -- see references/remote-setup.md). If this local run_id points at
  # a directory that's gone entirely, that's not "died without finishing" -- there is nothing to
  # resume into. Without this check, the branch below rsyncs into a nonexistent .../in/ (fails),
  # launches ocr-node.sh against a directory with no status.log, and the poll loop's `tail` on that
  # missing file returns nonzero forever -- an infinite "[OCR] reconnecting..." loop that never
  # actually reconnects to anything (reproduced: 3+ hours stuck this way).
  if ! ssh "$OCR_SSH_HOST" "test -d '$REMOTE_RUN_DIR'"; then
    echo "[OCR] remote: run $RUN_ID no longer exists on $OCR_SSH_HOST (already cleaned up) -- starting a new run"
    launch_new_run
    return
  fi

  if ssh "$OCR_SSH_HOST" "test -f '$REMOTE_RUN_DIR/DONE'"; then
    echo "[OCR] remote: run $RUN_ID already finished on $OCR_SSH_HOST, picking up artifacts"
    return
  fi

  local pid
  pid="$(ssh "$OCR_SSH_HOST" "cat '$REMOTE_RUN_DIR/PID' 2>/dev/null")"
  if [ -n "$pid" ] && ssh "$OCR_SSH_HOST" "kill -0 $pid 2>/dev/null"; then
    echo "[OCR] remote: re-attaching to live run $RUN_ID (pid $pid) on $OCR_SSH_HOST"
    return
  fi

  echo "[OCR] remote: run $RUN_ID died without finishing -- resuming it (already-complete stems are skipped remotely)"
  rsync -az --partial "${PDFS[@]}" "$OCR_SSH_HOST:$REMOTE_RUN_DIR/in/"
  ssh "$OCR_SSH_HOST" \
    "setsid nohup bash \$HOME/$OCR_REMOTE_ROOT/bin/ocr-node.sh \$HOME/$REMOTE_RUN_DIR >>\$HOME/$REMOTE_RUN_DIR/node.stdout 2>&1 & echo \$! >\$HOME/$REMOTE_RUN_DIR/PID"
}

if [ -s "$RUN_ID_FILE" ]; then
  resume_run
else
  launch_new_run
fi

CURSOR="$(cat "$CURSOR_FILE" 2>/dev/null || echo 0)"

# --- Pull one finished/skipped stem's artifacts down, validate, merge, render -----------------
# `=()` matters: a bare `declare -A STEM_DONE` leaves the array in a state where
# `${#STEM_DONE[@]}` trips `set -u`'s unbound-variable check while still empty (reproduced on
# bash 5.3.15) -- and because this script has no `set -e`, that failure doesn't abort the script,
# it just makes the `while` loop below execute zero iterations and fall through to a false
# "ALL DONE" with no stem ever polled or landed. The explicit empty initializer avoids this.
DONE_COUNT=0
declare -A STEM_DONE=()
declare -a DEGRADED_STEMS=()
EXPECTED_READERS=(olmocr chandra)

land_stem() {
  local stem="$1"
  local remote_dir="$REMOTE_RUN_DIR/out/$stem"
  local local_dir="$WORK/remote-out/$stem"
  mkdir -p "$local_dir"
  if ! rsync -az --partial "$OCR_SSH_HOST:$remote_dir/" "$local_dir/" >/dev/null 2>&1; then
    echo "[OCR] FAIL $stem: rsync down from $OCR_SSH_HOST failed"
    return
  fi

  local manifest="$local_dir/manifest.tsv"
  if [ ! -f "$manifest" ]; then
    echo "[OCR] FAIL $stem: no manifest.tsv landed from $OCR_SSH_HOST (surya likely failed remotely)"
    return
  fi

  local surya_rel
  surya_rel="$(awk -F'\t' '$1=="surya"{print $2}' "$manifest")"
  if [ -z "$surya_rel" ]; then
    echo "[OCR] FAIL $stem: manifest has no surya entry"
    return
  fi
  local surya_json="$local_dir/$surya_rel"

  if ! python3 "$VALIDATE" "$surya_json"; then
    echo "[OCR] FAIL $stem: validate-surya-json rejected the remote results.json"
    return
  fi

  mkdir -p "$WORK/results/$stem"
  cp "$surya_json" "$WORK/results/$stem/results.json"

  local reader_args=()
  local landed_readers=()
  local olmocr_rel chandra_rel
  olmocr_rel="$(awk -F'\t' '$1=="olmocr"{print $2}' "$manifest")"
  chandra_rel="$(awk -F'\t' '$1=="chandra"{print $2}' "$manifest")"
  if [ -n "$olmocr_rel" ]; then
    reader_args+=(--reader "olmocr=$local_dir/$olmocr_rel")
    landed_readers+=("olmocr")
  fi
  if [ -n "$chandra_rel" ]; then
    reader_args+=(--reader "chandra=$local_dir/$chandra_rel")
    landed_readers+=("chandra")
  fi

  if ! python3 "$MERGE" "$WORK/results/$stem/results.json" "$WORK/canonical/$stem.json" \
      --stem "$stem" --backend remote "${reader_args[@]}"; then
    echo "[OCR] FAIL $stem: merge-canonical"
    return
  fi

  python3 "$COVERAGE" "$WORK" --stem "$stem"

  if ! python3 "$RENDERTXT" "$WORK/results/$stem/results.json" "$OUT_TXT/$stem.txt" \
      "$WORK/canonical/$stem.json"; then
    echo "[OCR] FAIL $stem: render-txt"
    return
  fi

  DONE_COUNT=$((DONE_COUNT + 1))
  STEM_DONE["$stem"]=1
  local reader_list
  reader_list="$(IFS=,; echo "${landed_readers[*]}")"
  echo "[OCR] done $stem ($DONE_COUNT/$TOTAL) [readers: $reader_list]"

  if [ "${#landed_readers[@]}" -lt "${#EXPECTED_READERS[@]}" ]; then
    local missing=()
    local r found l
    for r in "${EXPECTED_READERS[@]}"; do
      found=0
      for l in "${landed_readers[@]}"; do
        [ "$r" = "$l" ] && found=1
      done
      [ "$found" -eq 0 ] && missing+=("$r")
    done
    local missing_list
    missing_list="$(IFS=,; echo "${missing[*]}")"
    echo "[OCR] WARN $stem: ${#landed_readers[@]} of ${#EXPECTED_READERS[@]} expected readers landed (missing: $missing_list) -- agreement.m will be ${#landed_readers[@]}"
    DEGRADED_STEMS+=("$stem")
  fi
}

# --- Poll status.log with a locally-held cursor; back off on connectivity failure, not on
# per-file OCR failure. FINISHED/SKIP records for a stem trigger land_stem immediately -- "done"
# fires on local artifacts existing, never on remote loop exit. -------------------------------
BACKOFF=10
while [ "${#STEM_DONE[@]}" -lt "$TOTAL" ]; do
  NEW_LINES="$(ssh -o ConnectTimeout=10 "$OCR_SSH_HOST" \
    "tail -n +$((CURSOR + 1)) '$REMOTE_RUN_DIR/status.log' 2>/dev/null")"
  RC=$?

  if [ "$RC" -ne 0 ]; then
    echo "[OCR] reconnecting..." >&2
    sleep "$BACKOFF"
    BACKOFF=$((BACKOFF < 60 ? BACKOFF * 3 : (BACKOFF < 300 ? BACKOFF + 60 : 300)))
    continue
  fi
  BACKOFF=10

  if [ -n "$NEW_LINES" ]; then
    LINE_COUNT=$(printf '%s\n' "$NEW_LINES" | wc -l | tr -d ' ')
    CURSOR=$((CURSOR + LINE_COUNT))
    echo "$CURSOR" >"$CURSOR_FILE"

    while IFS=$'\t' read -r _ts type stem stage detail; do
      case "$type" in
        FINISHED)
          if [ "$stage" = "no-geometry" ]; then
            echo "[OCR] FAIL $stem: surya (remote)"
            STEM_DONE["$stem"]=1
          elif [ -z "${STEM_DONE[$stem]:-}" ]; then
            land_stem "$stem"
          fi
          ;;
        SKIP)
          [ -z "${STEM_DONE[$stem]:-}" ] && land_stem "$stem"
          ;;
        FAIL)
          echo "[OCR] FAIL $stem: $stage -- $detail"
          ;;
      esac
    done <<<"$NEW_LINES"
  fi

  if [ "${#STEM_DONE[@]}" -lt "$TOTAL" ] && ssh -o ConnectTimeout=10 "$OCR_SSH_HOST" \
      "test -f '$REMOTE_RUN_DIR/DONE'" 2>/dev/null; then
    # Remote loop exited but not every requested stem produced a FINISHED/SKIP we saw --
    # drain whatever status.log has one more time before giving up on the rest.
    TAIL="$(ssh "$OCR_SSH_HOST" "tail -n +$((CURSOR + 1)) '$REMOTE_RUN_DIR/status.log' 2>/dev/null")"
    if [ -n "$TAIL" ]; then
      while IFS=$'\t' read -r _ts type stem stage detail; do
        case "$type" in
          FINISHED|SKIP) [ -z "${STEM_DONE[$stem]:-}" ] && land_stem "$stem" ;;
          FAIL) echo "[OCR] FAIL $stem: $stage -- $detail" ;;
        esac
      done <<<"$TAIL"
    fi
    break
  fi

  [ "${#STEM_DONE[@]}" -lt "$TOTAL" ] && sleep 10
done

if [ "${#DEGRADED_STEMS[@]}" -gt 0 ]; then
  DEGRADED_LIST="$(IFS=,; echo "${DEGRADED_STEMS[*]}")"
  echo "[OCR] ALL DONE ($DONE_COUNT/$TOTAL files landed, ${#DEGRADED_STEMS[@]} degraded: $DEGRADED_LIST) -> $OUT_TXT"
else
  echo "[OCR] ALL DONE ($DONE_COUNT/$TOTAL files landed) -> $OUT_TXT"
fi
