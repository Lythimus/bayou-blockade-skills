#!/usr/bin/env bash
# Local OCR_BACKEND: Surya geometry + MinerU reader, both run on this machine. Same
# grid-plus-reader shape as the remote tier, with one reader (m=1) instead of two.
#
# Usage: backend-local.sh <IN_DIR_OR_PDF> <OUT_TXT> <WORK>
# Emits the same [OCR] skip|done|FAIL|ALL DONE vocabulary as ocr-pipeline.sh's own loop.
#
# MinerU backend enum confirmed against a real `mineru --help` on this machine (2026-08-23):
#   pipeline | vlm-engine | hybrid-engine | vlm-http-client | hybrid-http-client
# (CLI default is hybrid-engine.) Published docs disagreed with each other and with this list --
# per the plan, this is what actually ships, not either doc's guess.
#
# MINERU_BACKEND defaults to "pipeline" here, not the CLI's own "hybrid-engine" default:
# hybrid/vlm engines are VLM-backed and unconfirmed on laptop-class hardware, whereas "pipeline"
# was confirmed end-to-end on this machine (Apple Silicon MPS, no dedicated GPU) against a real
# page from the 15308230.pdf test document -- see references/backends.md.
#
# Output directory layout confirmed by that same real run:
#   <OUT>/<stem>/<method>/<stem>_middle.json  (+ _content_list.json, _model.json, .md, ...)
# <method> comes from -m/--method (default "auto"), independent of -b/--backend -- this script
# globs for it rather than hardcoding "auto", since -m is never passed explicitly here.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOC_OCR_DIR="$(dirname "$SCRIPT_DIR")"
RENDERTXT="${RENDERTXT:-$DOC_OCR_DIR/render-txt.py}"
MERGE="$DOC_OCR_DIR/merge-canonical.py"

IN="${1:?Usage: backend-local.sh <IN_DIR_OR_PDF> <OUT_TXT> <WORK>}"
OUT_TXT="${2:?Usage: backend-local.sh <IN_DIR_OR_PDF> <OUT_TXT> <WORK>}"
WORK="${3:?Usage: backend-local.sh <IN_DIR_OR_PDF> <OUT_TXT> <WORK>}"

MINERU_BACKEND="${MINERU_BACKEND:-pipeline}"
SURYA_ENV="${SURYA_ENV:-surya}"
MINERU_ENV="${MINERU_ENV:-mineru}"

# --- conda env resolution -- same pattern as ocr-pipeline.sh's surya-only tool resolution, one
# helper per tool since each may live in its own env. conda_run <ENV_VAR> <bin-name> -> prints
# either the empty string (bin already on PATH, call it directly) or a `conda run -n <env>`
# prefix as a single shell-quoted string; caller expands it with eval/array as appropriate.
find_conda() {
  if [ -n "${CONDA:-}" ]; then
    echo "$CONDA"
    return
  fi
  if [ -n "${CONDA_EXE:-}" ] && [ -x "$CONDA_EXE" ]; then
    echo "$CONDA_EXE"
    return
  fi
  local c
  c="$(command -v conda 2>/dev/null)"
  if [ -n "$c" ]; then
    echo "$c"
    return
  fi
  for c in "$HOME/miniforge3/condabin/conda" "$HOME/miniconda3/condabin/conda" \
           "$HOME/anaconda3/condabin/conda" "$HOME/mambaforge/condabin/conda" \
           /opt/homebrew/Caskroom/miniforge/base/condabin/conda /opt/conda/condabin/conda; do
    [ -x "$c" ] && { echo "$c"; return; }
  done
}

SURYA_RUN=()
if ! command -v surya_ocr >/dev/null 2>&1; then
  CONDA_BIN="$(find_conda)"
  if [ -z "$CONDA_BIN" ]; then
    echo "[OCR] FAIL setup: surya_ocr not on PATH and no conda found." >&2
    echo "[OCR]   Activate the surya env, or set CONDA=/path/to/conda (env: \$SURYA_ENV, default 'surya')." >&2
    exit 1
  fi
  SURYA_RUN=("$CONDA_BIN" run -n "$SURYA_ENV")
fi

MINERU_RUN=()
if ! command -v mineru >/dev/null 2>&1; then
  CONDA_BIN="$(find_conda)"
  if [ -z "$CONDA_BIN" ]; then
    echo "[OCR] FAIL setup: mineru not on PATH and no conda found." >&2
    echo "[OCR]   Install it (e.g. \`conda create -n mineru python=3.12 && conda run -n mineru pip install 'mineru[core]'\`)," >&2
    echo "[OCR]   or set CONDA=/path/to/conda (env: \$MINERU_ENV, default 'mineru'), or re-run with OCR_BACKEND=surya-only." >&2
    exit 1
  fi
  MINERU_RUN=("$CONDA_BIN" run -n "$MINERU_ENV")
fi

mkdir -p "$OUT_TXT" "$WORK/results" "$WORK/canonical" "$WORK/mineru" "$WORK/logs"

# --- Work list -----------------------------------------------------------------------------
FILELIST="$(mktemp)"
trap 'rm -f "$FILELIST"' EXIT
if [ -f "$IN" ]; then
  printf '%s\0' "$IN" >"$FILELIST"
else
  find "$IN" -type f -iname '*.pdf' -print0 >"$FILELIST"
fi

TOTAL=$(tr -cd '\0' <"$FILELIST" | wc -c | tr -d ' ')
if [ "$TOTAL" -eq 0 ]; then
  echo "[OCR] no PDFs found under $IN"
  exit 0
fi

i=0
while IFS= read -r -d '' pdf; do
  i=$((i + 1))
  stem="$(basename "$pdf")"
  stem="${stem%.[Pp][Dd][Ff]}"

  out_file="$OUT_TXT/$stem.txt"
  canonical_json="$WORK/canonical/$stem.json"

  if [ -s "$out_file" ] && python3 -c "import json,sys; json.load(open(sys.argv[1]))" \
      "$canonical_json" >/dev/null 2>&1; then
    echo "[OCR] skip $stem"
    continue
  fi

  # Surya's own output layout has varied across versions: some nest an extra "surya/"
  # directory under --results_dir, some don't (same dual-path check as ocr-pipeline.sh).
  results_json="$WORK/results/surya/$stem/results.json"
  [ -s "$results_json" ] || results_json="$WORK/results/$stem/results.json"

  if [ ! -s "$results_json" ]; then
    surya_log="$WORK/logs/$stem.surya.log"
    if ! PYTORCH_MPS_HIGH_WATERMARK_RATIO=1.6 RECOGNITION_BATCH_SIZE=16 \
        "${SURYA_RUN[@]+"${SURYA_RUN[@]}"}" surya_ocr "$pdf" --results_dir "$WORK/results" \
        >"$surya_log" 2>&1; then
      if grep -qE 'CERTIFICATE_VERIFY_FAILED|self-signed certificate|huggingface\.co' "$surya_log" \
          && PYTORCH_MPS_HIGH_WATERMARK_RATIO=1.6 RECOGNITION_BATCH_SIZE=16 \
             HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
             "${SURYA_RUN[@]+"${SURYA_RUN[@]}"}" surya_ocr "$pdf" --results_dir "$WORK/results" \
             >>"$surya_log" 2>&1; then
        : # offline retry succeeded
      else
        echo "[OCR] FAIL $stem: surya_ocr (see $surya_log)"
        continue
      fi
    fi
    [ -s "$results_json" ] || results_json="$WORK/results/$stem/results.json"
  fi

  if [ ! -s "$results_json" ]; then
    echo "[OCR] FAIL $stem: surya_ocr produced no results.json"
    continue
  fi

  mineru_out="$WORK/mineru/$stem"
  mineru_log="$WORK/logs/$stem.mineru.log"
  if ! "${MINERU_RUN[@]+"${MINERU_RUN[@]}"}" mineru -p "$pdf" -o "$mineru_out" \
      -b "$MINERU_BACKEND" >"$mineru_log" 2>&1; then
    echo "[OCR] FAIL $stem: mineru (reader) -- continuing with Surya geometry only, see $mineru_log" >&2
  fi

  reader_args=()
  mineru_json="$(find "$mineru_out" -name "${stem}_middle.json" -print -quit 2>/dev/null)"
  if [ -n "$mineru_json" ]; then
    reader_args=(--reader "mineru=$mineru_json")
  fi

  if ! python3 "$MERGE" "$results_json" "$canonical_json" --stem "$stem" --backend local \
      "${reader_args[@]}"; then
    echo "[OCR] FAIL $stem: merge-canonical"
    continue
  fi

  if ! python3 "$RENDERTXT" "$results_json" "$out_file" "$canonical_json" >/dev/null 2>&1; then
    echo "[OCR] FAIL $stem: render-txt"
    continue
  fi

  echo "[OCR] done $stem ($i/$TOTAL)"
done <"$FILELIST"

echo "[OCR] ALL DONE ($TOTAL files) -> $OUT_TXT"
