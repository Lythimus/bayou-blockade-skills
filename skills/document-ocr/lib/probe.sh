#!/usr/bin/env bash
# Probe the remote OCR box for VPN reachability and provisioning state.
#
# Usage: probe.sh
# Reads OCR_SSH_HOST (required -- an ~/.ssh/config Host alias) and OCR_REMOTE_ROOT (default
# "ocr", relative to the remote $HOME) from the environment, falling back to
# ~/.claude/bayou-credentials.md (grep '^KEY:' | cut -d' ' -f2 -- the adsb-flight-search idiom).
#
# Exit 0 and print a one-line "[OCR] probe: ready ..." summary plus GPU occupancy on success.
# Exit 1 and print one of two distinguishable "[OCR] FAIL setup:" messages otherwise: VPN-gated
# (hostname doesn't resolve) vs. reachable-but-not-provisioned (missing tools/weights/server).

set -uo pipefail

CREDFILE="${BAYOU_CREDENTIALS:-$HOME/.claude/bayou-credentials.md}"

cred() {
  [ -f "$CREDFILE" ] || return 1
  grep "^$1:" "$CREDFILE" | head -1 | cut -d' ' -f2-
}

OCR_SSH_HOST="${OCR_SSH_HOST:-$(cred OCR_SSH_HOST)}"
OCR_REMOTE_ROOT="${OCR_REMOTE_ROOT:-$(cred OCR_REMOTE_ROOT)}"
OCR_REMOTE_ROOT="${OCR_REMOTE_ROOT:-ocr}"

if [ -z "$OCR_SSH_HOST" ]; then
  echo "[OCR] FAIL setup: no OCR_SSH_HOST configured. Set OCR_SSH_HOST in $CREDFILE (an ~/.ssh/config Host alias) or export it." >&2
  exit 1
fi

SSH_ERR="$(mktemp)"
trap 'rm -f "$SSH_ERR"' EXIT

if ! ssh -o BatchMode=yes -o ConnectTimeout=10 "$OCR_SSH_HOST" true 2>"$SSH_ERR"; then
  rc=$?
  if [ "$rc" -eq 255 ] && grep -qi 'could not resolve hostname' "$SSH_ERR"; then
    echo "[OCR] FAIL setup: OCR_SSH_HOST '$OCR_SSH_HOST' did not resolve -- the OCR box is VPN-gated." >&2
    echo "[OCR]   Connect the VPN and re-run; already-finished files are skipped automatically." >&2
    echo "[OCR]   Note: while that VPN is up, huggingface.co is unreachable from this Mac. That is expected" >&2
    echo "[OCR]   and only affects the local tiers -- for local OCR, drop the VPN and use OCR_BACKEND=local." >&2
    exit 1
  fi
  echo "[OCR] FAIL setup: ssh to '$OCR_SSH_HOST' failed (exit $rc):" >&2
  sed 's/^/[OCR]   /' "$SSH_ERR" >&2
  exit 1
fi

# One round trip: tool checks, weights-dir test, vLLM health check, disk free, GPU occupancy,
# logged-in user count. All read-only -- no writes, no installs.
REMOTE_OUT="$(ssh -o BatchMode=yes -o ConnectTimeout=10 "$OCR_SSH_HOST" \
  "OCR_REMOTE_ROOT='$OCR_REMOTE_ROOT' bash -s" <<'REMOTE_EOF'
set -u
for c in surya_ocr olmocr chandra vllm nvidia-smi rsync python3; do
  command -v "$c" >/dev/null 2>&1 && echo "HAVE:$c" || echo "MISS:$c"
done
[ -d "$HOME/$OCR_REMOTE_ROOT/hf-cache" ] && echo "HAVE:weights-dir" || echo "MISS:weights-dir"
curl -sf --max-time 5 http://127.0.0.1:8000/health >/dev/null 2>&1 \
  && echo "HAVE:vllm-server(:8000)" || echo "MISS:vllm-server(:8000)"
df -Pk "$HOME" 2>/dev/null | awk 'NR==2{print "DISK_FREE_KB:"$4}'
who | wc -l | awk '{print "USERS:"$1}'
nvidia-smi --query-gpu=index,utilization.gpu,memory.used,memory.total \
  --format=csv,noheader,nounits 2>/dev/null | tr -d ' ' | sed 's/^/GPU:/'
REMOTE_EOF
)"

if [ -z "$REMOTE_OUT" ]; then
  echo "[OCR] FAIL setup: '$OCR_SSH_HOST' is reachable but the probe script produced no output." >&2
  exit 1
fi

MISSING=()
while IFS= read -r line; do
  case "$line" in
    MISS:*) MISSING+=("${line#MISS:}") ;;
  esac
done <<<"$REMOTE_OUT"

if [ "${#MISSING[@]}" -gt 0 ]; then
  echo "[OCR] FAIL setup: '$OCR_SSH_HOST' is reachable over SSH but is not provisioned for OCR." >&2
  IFS=,; echo "[OCR]   missing: ${MISSING[*]}" >&2; unset IFS
  echo "[OCR]   Provision it with references/remote-setup.md, or re-run with OCR_BACKEND=local." >&2
  exit 1
fi

DISK_FREE_KB="$(grep '^DISK_FREE_KB:' <<<"$REMOTE_OUT" | cut -d: -f2)"
USERS="$(grep '^USERS:' <<<"$REMOTE_OUT" | cut -d: -f2)"
FREE_G=$((DISK_FREE_KB / 1024 / 1024))

echo "[OCR] probe: '$OCR_SSH_HOST' ready -- ${FREE_G}G free, ${USERS} users logged in"
while IFS=: read -r _ idx util used total; do
  echo "[OCR]   gpu$idx: ${util}% util, ${used}/${total} MiB"
done < <(grep '^GPU:' <<<"$REMOTE_OUT")

exit 0
