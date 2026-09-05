#!/usr/bin/env bash
# Self-contained node script, rsync'd to the OCR box and run there (never on the Mac).
# Processes every PDF under <run_dir>/in/ into <run_dir>/out/<stem>/{surya,olmocr,chandra}/,
# writing progress to <run_dir>/status.log in an append-only, machine-readable format that the
# local wrapper (lib/backend-remote.sh) translates into [OCR] lines.
#
# Usage: ocr-node.sh <run_dir>
# Launched detached by the local wrapper via `setsid nohup ocr-node.sh <run_dir> & echo $! >PID`
# so it survives a dropped SSH session.
#
# status.log line format (tab-delimited, one record per line, always appended, never rewritten):
#   <epoch>\t<TYPE>\t<stem>\t<stage>\t<detail>
# TYPE is one of: START STAGE OK FAIL SKIP FINISHED
#   START    <stem>  -        -                    stem processing begins
#   SKIP     <stem>  -        already-complete      stem already has out/<stem>/.complete
#   STAGE    <stem>  <stage>  -                     entering a stage (surya|olmocr|chandra)
#   OK       <stem>  <stage>  -                     stage succeeded
#   FAIL     <stem>  <stage>  <message>              stage failed -- stem continues to the next
#                                                     stage; a reader failing does not block Surya
#                                                     geometry or the other reader
#   FINISHED <stem>  -        ok|partial|no-geometry  stem done: ok = surya + both readers,
#                                                      partial = surya + <2 readers, no-geometry =
#                                                      surya itself failed (fatal for this stem)
# A run_dir-level DONE file (not a status.log line) marks the whole batch as attempted -- written
# only after every input PDF has produced either a FINISHED or a terminal SKIP record.
#
# Per-file failures never stop the batch: one bad PDF must not prevent the rest from OCRing.

set -uo pipefail

RUN_DIR="${1:?Usage: ocr-node.sh <run_dir>}"
IN_DIR="$RUN_DIR/in"
OUT_DIR="$RUN_DIR/out"
STATUS_LOG="$RUN_DIR/status.log"
NODE_LOG="$RUN_DIR/node.log"

mkdir -p "$OUT_DIR"
exec >>"$NODE_LOG" 2>&1

log_status() {
  # log_status <TYPE> <stem> <stage> <detail>
  printf '%s\t%s\t%s\t%s\t%s\n' "$(date +%s)" "$1" "$2" "$3" "$4" >>"$STATUS_LOG"
}

# --- GPU pin for Surya -------------------------------------------------------
# olmOCR and Chandra are served persistently (see references/remote-setup.md -- provisioning
# starts one `vllm serve` per reader, each pinned to its own GPU, before any ocr-node.sh run).
# Surya runs directly in this process per batch, so it needs its own GPU pin chosen at launch
# from *current* occupancy -- never assume all 8 GPUs are free, this is a shared machine.
pick_surya_gpu() {
  if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo ""
    return
  fi
  # Compute utilization.gpu alone is not a valid "free" signal: a persistent inference server
  # (e.g. this same run's own olmOCR/Chandra vLLM servers) idles at ~0% util while still holding
  # >100GB of memory. Picking by util first, as an earlier version did, chose exactly that GPU
  # and Surya OOM'd instantly (reproduced: chose the GPU under our own olmOCR server, which had
  # only ~300MiB free of 140GB). Rank by actual free memory instead.
  local min_free_mib=20000
  local best
  best="$(nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader,nounits \
    | awk -F', *' -v min="$min_free_mib" '{free=$3-$2; if (free>=min) print $1, free}' \
    | sort -k2 -n -r | head -1 | cut -d' ' -f1)"
  if [ -n "$best" ]; then
    echo "$best"
    return
  fi
  # Nothing clears the threshold -- fall back to whichever GPU has the most free memory so we
  # don't land on the single worst one.
  nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader,nounits \
    | awk -F', *' '{free=$3-$2; print $1, free}' | sort -k2 -n -r | head -1 | cut -d' ' -f1
}

SURYA_GPU="$(pick_surya_gpu)"
if [ -n "$SURYA_GPU" ]; then
  export CUDA_VISIBLE_DEVICES="$SURYA_GPU"
  echo "[ocr-node] pinned Surya to GPU $SURYA_GPU"
fi

# Reader endpoints -- ports are provisioning-time choices, see references/remote-setup.md.
# CLI shapes confirmed against `olmocr --help` / `chandra --help` on holos (2026-08-25):
# olmocr takes a workspace dir as its positional arg (not the pdf) plus --pdfs/--model/--server;
# chandra takes positional INPUT_PATH OUTPUT_PATH plus --method, and points at the vLLM server
# via the VLLM_API_BASE env var -- there is no --server flag on chandra.
OLMOCR_PORT="${OLMOCR_PORT:-8000}"
CHANDRA_PORT="${CHANDRA_PORT:-8001}"
OLMOCR_MODEL="${OLMOCR_MODEL:-allenai/olmOCR-2-7B-1025-FP8}"
# olmocr's own default (1/250 = 0.004) discards the *entire* document once that fraction of pages
# hits its per-page retry ceiling -- fine for a short document, but on a large one (thousands of
# pages) a handful of transient per-page failures (network blip to the vLLM server, a single bad
# rasterization) becomes near-certain, and the whole document is thrown away rather than landing
# with a few pages of fallback text. Each page already gets 8 retries before counting as failed, so
# raising this only changes what happens after that -- keep-with-some-fallback-pages vs.
# discard-everything -- not how hard a single page is retried.
OLMOCR_MAX_PAGE_ERROR_RATE="${OLMOCR_MAX_PAGE_ERROR_RATE:-0.02}"

# manifest_put <stem> <key> <relpath>
# Records where a stage's output actually landed, relative to out/<stem>/, so the local wrapper
# (which builds merge-canonical.py's --reader NAME=PATH flags) never has to guess a CLI's exact
# output filename -- it reads this manifest instead. One line per key; last write wins.
manifest_put() {
  local stem="$1" key="$2" relpath="$3"
  local manifest="$OUT_DIR/$stem/manifest.tsv"
  { [ -f "$manifest" ] && grep -v "^$key	" "$manifest"; printf '%s\t%s\n' "$key" "$relpath"; } \
    >"$manifest.tmp" && mv "$manifest.tmp" "$manifest"
}

process_stem() {
  local pdf="$1" stem="$2"
  local out="$OUT_DIR/$stem"
  mkdir -p "$out/surya" "$out/olmocr" "$out/chandra"

  log_status START "$stem" - -

  log_status STAGE "$stem" surya -
  if surya_ocr "$pdf" --results_dir "$out/surya" >"$out/surya/surya.log" 2>&1; then
    # Surya's own output layout has varied across versions -- some nest an extra "surya/"
    # directory under --results_dir, some don't (same dual-path check as ocr-pipeline.sh).
    local surya_json="$out/surya/surya/$stem/results.json"
    [ -s "$surya_json" ] || surya_json="$out/surya/$stem/results.json"
    if [ -s "$surya_json" ]; then
      manifest_put "$stem" surya "${surya_json#"$out"/}"
      log_status OK "$stem" surya -
    else
      log_status FAIL "$stem" surya "surya_ocr ran but no results.json found under out/$stem/surya/"
      log_status FINISHED "$stem" - no-geometry
      return
    fi
  else
    log_status FAIL "$stem" surya "surya_ocr failed, see out/$stem/surya/surya.log"
    log_status FINISHED "$stem" - no-geometry
    return
  fi

  local readers_ok=0

  log_status STAGE "$stem" olmocr -
  # workspace dir is positional; the actual pdf is passed via --pdfs, not as the positional arg.
  if olmocr "$out/olmocr" --pdfs "$pdf" --model "$OLMOCR_MODEL" \
      --server "http://127.0.0.1:$OLMOCR_PORT/v1" \
      --max_page_error_rate "$OLMOCR_MAX_PAGE_ERROR_RATE" \
      >"$out/olmocr/olmocr.log" 2>&1; then
    local olmocr_jsonl
    olmocr_jsonl="$(find "$out/olmocr" -name '*.jsonl' -print -quit)"
    if [ -s "$olmocr_jsonl" ]; then
      manifest_put "$stem" olmocr "${olmocr_jsonl#"$out"/}"
      log_status OK "$stem" olmocr -
      readers_ok=$((readers_ok + 1))
    else
      log_status FAIL "$stem" olmocr "olmocr ran but produced no .jsonl under out/$stem/olmocr/"
    fi
  else
    log_status FAIL "$stem" olmocr "olmocr failed, see out/$stem/olmocr/olmocr.log"
  fi

  log_status STAGE "$stem" chandra -
  # chandra has no --server flag -- it reads the vLLM endpoint from VLLM_API_BASE, which
  # defaults to :8000 (olmOCR's port), so this must always be set explicitly or chandra
  # silently talks to the wrong model server instead of failing.
  if VLLM_API_BASE="http://127.0.0.1:$CHANDRA_PORT/v1" chandra "$pdf" "$out/chandra" \
      --method vllm >"$out/chandra/chandra.log" 2>&1; then
    local chandra_json chandra_md
    chandra_json="$(find "$out/chandra" -name '*_metadata.json' -print -quit)"
    chandra_md="${chandra_json%_metadata.json}.md"
    # chandra exits 0 even when every page's vLLM generation call failed (observed: repeated
    # "Connection error", then "Saved: ...md (2 page(s))" with a genuinely 0-byte file) -- the
    # metadata json still gets written either way, so its mere existence doesn't prove real
    # content landed. Require the co-located .md to be non-empty too.
    if [ -n "$chandra_json" ] && [ -s "$chandra_md" ]; then
      manifest_put "$stem" chandra "${chandra_json#"$out"/}"
      log_status OK "$stem" chandra -
      readers_ok=$((readers_ok + 1))
    else
      log_status FAIL "$stem" chandra "chandra ran but produced no non-empty .md under out/$stem/chandra/ (metadata json alone doesn't prove success)"
    fi
  else
    log_status FAIL "$stem" chandra "chandra failed, see out/$stem/chandra/chandra.log"
  fi

  if [ "$readers_ok" -eq 2 ]; then
    log_status FINISHED "$stem" - ok
  else
    log_status FINISHED "$stem" - partial
  fi
  touch "$out/.complete"
}

shopt -s nullglob
for pdf in "$IN_DIR"/*.pdf "$IN_DIR"/*.PDF; do
  stem="$(basename "$pdf")"
  stem="${stem%.[Pp][Dd][Ff]}"

  if [ -f "$OUT_DIR/$stem/.complete" ]; then
    log_status SKIP "$stem" - already-complete
    continue
  fi

  process_stem "$pdf" "$stem"
done

date +%s >"$RUN_DIR/DONE"
