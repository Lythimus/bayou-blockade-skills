#!/usr/bin/env bash
# Resumable batch OCR: scanned PDF -> searchable .txt via Surya (+ optional readers).
# Usage: ocr-pipeline.sh <INPUT_DIR_OR_PDF> <OUTPUT_TXT_DIR> [WORK_DIR] [--backend <name>] [--rerender]
#
# Source-agnostic: works on any scanned/image PDF (LDEQ EDMS, USACE, FAA, ...).
#
# --backend <name> is a thin CLI alias for OCR_BACKEND (below) -- an explicit --backend wins over
# any OCR_BACKEND already in the environment, matching how a CLI flag normally overrides an env
# var. Omit it to use OCR_BACKEND (or its "auto" default) unchanged.
#
# --azure is accepted here only so it doesn't get misparsed as a positional arg -- it's consumed
# and ignored, with a one-line stderr note. The actual --azure escalation is orchestrated by
# SKILL.md, not this script, because it needs AskUserQuestion for the cost confirmation.
#
# OCR_BACKEND selects the geometry+reader tier (env var, default "auto"):
#   remote      Surya + olmOCR + Chandra, run on holos via lib/backend-remote.sh (whole batch
#               handed off in one call -- the remote leg manages its own per-file progress)
#   local       Surya + MinerU, run on this machine via lib/backend-local.sh (Phase 4)
#   surya-only  Surya alone, no readers -- this file's own per-file loop below
#   auto        probe remote (lib/probe.sh); fall back to local with a one-line stderr notice
#               if the probe fails. Never switches mid-batch.
# Per file (surya-only / local): surya_ocr -> results.json -> render-txt.py -> <stem>.txt
#
# --rerender regenerates <stem>.txt from an existing results.json (and canonical.json, if a
# merge has run) without re-running surya_ocr. Seconds per document, no GPU, no network. It
# bypasses the "skip if .txt already exists" check, so use it deliberately, per package. Backend
# selection is irrelevant to --rerender -- it only ever reads what's already on disk.
#
# Progress lines (for a Monitor watching stdout):
#   [OCR] skip <stem>
#   [OCR] done <stem> (<i>/<total>)
#   [OCR] FAIL <stem>: <stage>
#   [OCR] ALL DONE (<total> files) -> <OUT_TXT>

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RENDERTXT="${RENDERTXT:-$SCRIPT_DIR/render-txt.py}"

# --- Argument parsing --------------------------------------------------------
# Positional args in order of first appearance; --rerender is a flag, anywhere; --backend takes
# the following arg as its value, anywhere. A while/shift loop (not a simple for-arg loop) is
# needed here specifically so --backend can consume its value token.

RERENDER=0
POSITIONAL=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --rerender) RERENDER=1; shift ;;
    --backend)
      OCR_BACKEND="${2:?--backend requires a value (remote|local|surya-only|auto)}"
      shift 2
      ;;
    --azure)
      # --azure is handled entirely by SKILL.md (it needs AskUserQuestion for the cost
      # confirmation, which no shell script can do) -- consumed and ignored here rather than
      # silently falling into POSITIONAL, where it would corrupt WORK_DIR.
      echo "[OCR] note: --azure is handled by SKILL.md's --azure recipe, not this script; ignoring here." >&2
      shift
      ;;
    *) POSITIONAL+=("$1"); shift ;;
  esac
done

IN="${POSITIONAL[0]:?Usage: ocr-pipeline.sh <INPUT_DIR_OR_PDF> <OUTPUT_TXT_DIR> [WORK_DIR] [--backend <name>] [--rerender]}"
OUT_TXT="${POSITIONAL[1]:?Usage: ocr-pipeline.sh <INPUT_DIR_OR_PDF> <OUTPUT_TXT_DIR> [WORK_DIR] [--backend <name>] [--rerender]}"
WORK="${POSITIONAL[2]:-./.ocr-work}"

mkdir -p "$OUT_TXT" "$WORK/results" "$WORK/canonical"

# --- Backend dispatch --------------------------------------------------------
# --rerender never touches a backend -- it only reads what's already on disk, handled entirely
# by the per-file loop below (RERENDER short-circuits into that loop's own results_json check).
if [ "$RERENDER" -eq 0 ]; then
  OCR_BACKEND="${OCR_BACKEND:-auto}"
  BACKEND_REMOTE="$SCRIPT_DIR/lib/backend-remote.sh"
  BACKEND_LOCAL="$SCRIPT_DIR/lib/backend-local.sh"
  PROBE="$SCRIPT_DIR/lib/probe.sh"

  case "$OCR_BACKEND" in
    remote)
      exec "$BACKEND_REMOTE" "$IN" "$OUT_TXT" "$WORK"
      ;;
    local)
      exec "$BACKEND_LOCAL" "$IN" "$OUT_TXT" "$WORK"
      ;;
    surya-only)
      : # falls through to this file's own per-file loop below
      ;;
    auto)
      if [ -x "$PROBE" ] && "$PROBE" >/dev/null 2>&1; then
        exec "$BACKEND_REMOTE" "$IN" "$OUT_TXT" "$WORK"
      else
        echo "[OCR] remote box not available -- falling back to OCR_BACKEND=local" >&2
        exec "$BACKEND_LOCAL" "$IN" "$OUT_TXT" "$WORK"
      fi
      ;;
    *)
      echo "[OCR] FAIL setup: unknown OCR_BACKEND '$OCR_BACKEND' (remote|local|surya-only|auto)" >&2
      exit 1
      ;;
  esac
fi

# --- Tool resolution (surya-only / --rerender path only) --------------------
# Reached only when OCR_BACKEND=surya-only or --rerender was given -- remote/local backends
# exec() away above and never need local surya_ocr or a conda env at all.
# Everything below can be overridden by exporting the same variable name.

SURYA_ENV="${SURYA_ENV:-surya}"

# Surya runner. If surya_ocr is already on PATH (env activated, pipx, venv), call it
# directly; otherwise fall back to `conda run -n $SURYA_ENV`.
# RUN/PY are arrays so an empty prefix means "run it directly".
RUN=()
PY=(python3)
if ! command -v surya_ocr >/dev/null 2>&1; then
  if [ -z "${CONDA:-}" ]; then
    if [ -n "${CONDA_EXE:-}" ] && [ -x "$CONDA_EXE" ]; then
      CONDA="$CONDA_EXE"
    else
      CONDA="$(command -v conda 2>/dev/null)"
    fi
  fi
  if [ -z "${CONDA:-}" ]; then
    # conda is commonly absent from non-interactive PATH; probe standard installs.
    for c in "$HOME/miniforge3/condabin/conda" "$HOME/miniconda3/condabin/conda" \
             "$HOME/anaconda3/condabin/conda" "$HOME/mambaforge/condabin/conda" \
             /opt/homebrew/Caskroom/miniforge/base/condabin/conda \
             /opt/conda/condabin/conda; do
      [ -x "$c" ] && { CONDA="$c"; break; }
    done
  fi
  if [ -z "${CONDA:-}" ]; then
    echo "[OCR] FAIL setup: surya_ocr not on PATH and no conda found." >&2
    echo "[OCR]   Activate the surya env, or set CONDA=/path/to/conda (env: \$SURYA_ENV, default 'surya')." >&2
    exit 1
  fi
  RUN=("$CONDA" run -n "$SURYA_ENV")
  PY=("$CONDA" run -n "$SURYA_ENV" python)
fi

if [ ! -f "$RENDERTXT" ]; then
  echo "[OCR] FAIL setup: render-txt.py not found at $RENDERTXT" >&2
  exit 1
fi

# Collect input PDFs (single file or whole directory) into a NUL-delimited list.
FILELIST="$(mktemp)"
trap 'rm -f "$FILELIST"' EXIT

if [ -f "$IN" ]; then
  printf '%s\0' "$IN" > "$FILELIST"
else
  find "$IN" -type f -iname '*.pdf' -print0 > "$FILELIST"
fi

TOTAL=$(tr -cd '\0' < "$FILELIST" | wc -c | tr -d ' ')
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

  # Surya's own output layout has varied across versions: some nest an extra
  # "surya/" directory under --results_dir, some don't. Accept either.
  results_json="$WORK/results/surya/$stem/results.json"
  if [ ! -s "$results_json" ]; then
    results_json="$WORK/results/$stem/results.json"
  fi

  if [ "$RERENDER" -eq 1 ]; then
    if [ ! -s "$results_json" ]; then
      echo "[OCR] FAIL $stem: --rerender requested but no results.json under $WORK/results/surya/$stem/ or $WORK/results/$stem/"
      continue
    fi
    if ! "${PY[@]}" "$RENDERTXT" "$results_json" "$out_file" "$canonical_json" >/dev/null 2>&1; then
      echo "[OCR] FAIL $stem: render-txt"
      continue
    fi
    echo "[OCR] done $stem ($i/$TOTAL)"
    continue
  fi

  if [ -s "$out_file" ]; then
    echo "[OCR] skip $stem"
    continue
  fi

  # "${RUN[@]+...}" keeps an empty prefix array safe under `set -u` on bash 3.2 (macOS).
  mkdir -p "$WORK/logs"
  surya_log="$WORK/logs/$stem.surya.log"
  if ! PYTORCH_MPS_HIGH_WATERMARK_RATIO=1.6 RECOGNITION_BATCH_SIZE=16 \
      "${RUN[@]+"${RUN[@]}"}" surya_ocr "$pdf" --results_dir "$WORK/results" >"$surya_log" 2>&1; then
    if grep -qE 'CERTIFICATE_VERIFY_FAILED|self-signed certificate|huggingface\.co' "$surya_log"; then
      # huggingface_hub revalidates cached model files over the network on every call
      # (HEAD request for the etag) unless told not to. If the models were already
      # downloaded in an earlier run, that revalidation is the only thing a VPN/proxy's
      # SSL interception can break — retry fully offline before giving up.
      if PYTORCH_MPS_HIGH_WATERMARK_RATIO=1.6 RECOGNITION_BATCH_SIZE=16 \
          HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
          "${RUN[@]+"${RUN[@]}"}" surya_ocr "$pdf" --results_dir "$WORK/results" >>"$surya_log" 2>&1; then
        : # offline retry succeeded, fall through to results_json check below
      else
        echo "[OCR] FAIL $stem: surya_ocr (Hugging Face isn't accessible — surya_ocr needs to download or revalidate model weights from huggingface.co, and something on this network path is intercepting/blocking that HTTPS connection with a self-signed cert. This is the signature of a VPN or corporate proxy. An offline retry using any already-cached models also failed, so the weights aren't fully cached yet. Disconnect the VPN, or otherwise get huggingface.co reachable, then re-run — already-completed files are skipped automatically.)"
        continue
      fi
    else
      echo "[OCR] FAIL $stem: surya_ocr (see $surya_log)"
      continue
    fi
  fi

  if [ ! -s "$results_json" ]; then
    echo "[OCR] FAIL $stem: surya_ocr (no results.json under $WORK/results/surya/$stem/ or $WORK/results/$stem/ — see $surya_log)"
    continue
  fi

  if ! "${PY[@]}" "$RENDERTXT" "$results_json" "$out_file" "$canonical_json" >/dev/null 2>&1; then
    echo "[OCR] FAIL $stem: render-txt"
    continue
  fi

  echo "[OCR] done $stem ($i/$TOTAL)"
done < "$FILELIST"

echo "[OCR] ALL DONE ($TOTAL files) -> $OUT_TXT"
