# Sourced by ocr-pipeline.sh and backend-local.sh, not run directly.
#
# Stopping a batch must stop everything it started. Killing only the batch script reparents its
# `conda run` -> python children to PID 1, where they keep running (and the machine stays slow)
# until they finish on their own.
#
# bash defers a trap until the current *foreground* child exits, which for surya_ocr or mineru
# can be minutes. run_child backgrounds the command and waits on it instead: `wait` returns as
# soon as a trapped signal arrives, so the trap runs immediately.

# Children are collected before their parent is killed: once a parent dies, its children are
# reparented to PID 1 and `pgrep -P` can no longer find them.
kill_tree() {
  local pid="$1" child
  for child in $(pgrep -P "$pid" 2>/dev/null); do
    kill_tree "$child"
  done
  kill -TERM "$pid" 2>/dev/null
}

# Kills only this script's descendants, never the process group: when run from a
# non-interactive shell, the group includes whatever launched the batch.
kill_descendants() {
  local child
  for child in $(pgrep -P $$ 2>/dev/null); do
    kill_tree "$child"
  done
}

# The trap usually fires inside run_child, whose stderr is redirected to a per-file log; fd 9
# keeps the batch's own stderr so the stop notice reaches whoever is watching the run.
exec 9>&2

on_stop_signal() {
  echo "[OCR] stopped by signal -- killing OCR child processes" >&9
  kill_descendants
  exit 143
}

trap on_stop_signal TERM INT HUP

# Usage: run_child <cmd> [args...]  (redirect the call itself; the child inherits it)
# Pass env vars as `run_child env VAR=value cmd ...`.
run_child() {
  "$@" &
  wait $!
}
