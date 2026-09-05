# Provisioning the remote OCR box

No provisioning script ships with this skill — the box is a shared, multi-tenant research
machine, and installing/starting long-lived services on someone else's hardware deserves a human
reading each step, not a script running unattended. This doc is what you follow by hand (or paste
into a shell) the first time, and whenever a step in it needs re-verifying after a probe failure.

`lib/probe.sh` tells you what's missing before you start, and again after each step below.

This doc's commands are generic (work against any `OCR_SSH_HOST`/`OCR_REMOTE_ROOT`); host-specific
facts about a particular box you've already provisioned (its GPU count, disk quirks, whether it
can reach huggingface.co, unresolved per-box issues) belong in `~/.claude/bayou-credentials.md`
under that host's own section, not in this file.

## Shared-machine etiquette (accepted-risk, same posture as `sonris-session`)

- **Read `nvidia-smi` immediately before every GPU-picking decision**, not once at the start of a
  session. Utilization and free memory on a shared box can and does change between your probe and
  your launch.
- **Pin `CUDA_VISIBLE_DEVICES` to specific free indices.** Never assume all 8 GPUs are yours, and
  never launch a service without an explicit pin — an unpinned process defaults to every visible
  GPU and will collide with someone else's job.
- **Default to 2 replicas** (one GPU for the olmOCR vLLM server, one for the Chandra vLLM server),
  not 8. Both models are ≤ 7B params and fit trivially in 140 GB — there is no throughput reason
  to grab more than 2 cards for the readers. `remote/ocr-node.sh` separately picks one more free
  GPU per batch run for Surya itself (it re-reads occupancy at launch, see its `pick_surya_gpu`).
- **Data-parallel replicas, never tensor-parallel.** These models are too small for TP to do
  anything but add cross-GPU latency for no benefit.
- **Check free disk immediately before a weight pull**, and consider whether the box has a larger
  shared/network drive (e.g. mounted under `/data/...`) separate from the home-directory disk —
  worth using instead if home is tight, via a symlink (`ln -s /path/on/big/drive
  $HOME/$OCR_REMOTE_ROOT/hf-cache`) so every other path in this doc keeps working unmodified.
- **Ask before installing packages or pulling weights**, per the plan's two-regime policy — this
  applies during setup/testing. The shipped skill's steady-state remote runs (rsync a batch,
  launch `ocr-node.sh`, poll) do not ask; provisioning changes to this box do.

## 1. Install `uv`

```bash
ssh "$OCR_SSH_HOST" 'curl -LsSf https://astral.sh/uv/install.sh | sh'
```

Installs to `~/.local/bin/uv`. Confirm with `ssh "$OCR_SSH_HOST" '$HOME/.local/bin/uv --version'`
(use the full path — `~/.local/bin` is not reliably on `PATH` yet, see step 1b).

## 1b. Expose the venv's tools on `PATH` for non-interactive SSH sessions

Every later step in this doc, `lib/probe.sh`'s `command -v` checks, and `remote/ocr-node.sh`'s
bare `surya_ocr`/`olmocr`/`chandra` calls (rsync'd and run via `setsid nohup bash ... ocr-node.sh`,
itself a non-interactive SSH command) all need these tools resolvable without an explicit
`source .../venv/bin/activate` on every single invocation. A **non-interactive, non-login** shell
(exactly what `ssh host 'command'` runs) does not read `~/.bashrc` on most Linux distributions —
except Debian/Ubuntu's default bash build, which *does* source `~/.bashrc` even non-interactively
when it detects the connection came over ssh, and ships that file with an early
`case $- in *i*) ;; *) return;; esac` guard right at the top specifically to stop everything below
it from running in that case. That guard is why a line simply *appended* to `~/.bashrc` (as you'd
naturally do) silently never executes for any `ssh host 'command'` invocation — it has to be
**prepended before the guard** to actually take effect:

```bash
ssh "$OCR_SSH_HOST" 'printf "export PATH=\"\$HOME/'"$OCR_REMOTE_ROOT"'/venv/bin:\$PATH\"\n" \
  | cat - ~/.bashrc > ~/.bashrc.new && mv ~/.bashrc ~/.bashrc.bak && mv ~/.bashrc.new ~/.bashrc'
```

Verify immediately — this must print the venv's `bin` dir at the front, from a **fresh**
non-interactive session (not one that already has the venv activated):

```bash
ssh "$OCR_SSH_HOST" 'echo $PATH'
```

If provisioning fails partway and needs redoing, this step doesn't need repeating — it's additive
and idempotent to re-run, but check it isn't already there before adding it twice.

## 2. Create the venv and install the stack — as separate installs, not one combined command

```bash
ssh "$OCR_SSH_HOST" "\$HOME/.local/bin/uv venv \$HOME/$OCR_REMOTE_ROOT/venv --python 3.12"
```

**Install `vllm` by itself first**, then each reader package as its own separate `uv pip install`
call:

```bash
ssh "$OCR_SSH_HOST" "source \$HOME/$OCR_REMOTE_ROOT/venv/bin/activate && \$HOME/.local/bin/uv pip install vllm"
ssh "$OCR_SSH_HOST" "source \$HOME/$OCR_REMOTE_ROOT/venv/bin/activate && \$HOME/.local/bin/uv pip install 'surya-ocr==0.6.13'"
ssh "$OCR_SSH_HOST" "source \$HOME/$OCR_REMOTE_ROOT/venv/bin/activate && \$HOME/.local/bin/uv pip install olmocr"
ssh "$OCR_SSH_HOST" "source \$HOME/$OCR_REMOTE_ROOT/venv/bin/activate && \$HOME/.local/bin/uv pip install chandra-ocr"
ssh "$OCR_SSH_HOST" "source \$HOME/$OCR_REMOTE_ROOT/venv/bin/activate && \$HOME/.local/bin/uv pip install 'transformers==4.46.2'"
```

**Why this order and shape, confirmed empirically:**

- **Installing all four in one `uv pip install vllm surya-ocr olmocr chandra-ocr` command lets the
  resolver pick an ancient `vllm`** (a ~2023-era release with no prebuilt wheel for the box's
  Python/platform) to satisfy some other package's looser constraint, which then tries to build
  from source and fails on an `nvcc`-vs-`torch` CUDA version mismatch. Installing `vllm` alone
  first pins a modern version with a real wheel; the reader packages layered in afterward don't
  reopen that resolution.
- **`surya-ocr` must be pinned to `0.6.13`, not left to resolve latest.** Surya 2 (`0.22.1` at
  time of writing) is architecturally different: it no longer runs inference directly, it spawns
  its own vLLM/llama.cpp backend **via Docker**, and fails immediately with `docker binary not
  found` if Docker isn't installed. It also uses a different CLI (`--output_dir`, not
  `--results_dir`) and a different `results.json` shape than what this skill's `merge-canonical.py`
  and `render-txt.py` expect (documented in `references/output-schema.md`, written against
  `0.6.13`'s `{stem: [{text_lines: [...], languages, image_bbox, page}]}`). `0.6.13` runs
  standalone via plain torch/transformers, no Docker, no server — the version this whole pipeline
  is built around.
- **`transformers==4.46.2` is required alongside `surya-ocr==0.6.13`.** A newer `transformers`
  (pulled in as a side effect of installing `vllm`/`olmocr`, e.g. `5.15.1` or even `4.57.6`) breaks
  surya 0.6.13's custom `SuryaOCRConfig.__init__`, which unconditionally does
  `kwargs.pop("encoder")` — newer `transformers`' own logging path calls `self.__class__()` with
  no kwargs at some point (inside `to_diff_dict()`), and that bare call raises `KeyError:
  'encoder'`. This is installed *last*, deliberately, to win any version conflict with what the
  other three packages want.
- **This four-tool combination genuinely wants four different `transformers`/dependency profiles**
  sharing one venv. It has worked with this exact pin set, but if you hit a new incompatibility
  after upgrading any one of these packages, the durable fix is splitting into per-tool venvs
  rather than continuing to chase pins in a shared one.

## 3. Pull weights

**`huggingface-cli download <repo> --local-dir <path>` writes a flat directory** (the repo's files
directly under `<path>`), which is a **different, incompatible layout** from the
`hub/models--org--repo/snapshots/<hash>/...` cache structure that `HF_HOME` + `HF_HUB_OFFLINE=1`
expect when a tool loads a model by repo-id string. Pointing `HF_HOME` at a flat `--local-dir`
tree does not work — every tool below needs to be told the **literal local path** instead of a
repo id, via whatever override mechanism it supports (see below). Because of this, and because the
box itself may not be able to reach huggingface.co at all (see the host's own credentials-file
section), the practical download path is usually: pull weights to a machine that *can* reach HF,
then `rsync` the resulting directory tree up.

Check free disk first (see etiquette above — plan for roughly 20-25 GB for olmOCR + Chandra's
VLM weights, plus another ~2 GB for surya 0.6.13's five smaller models, and re-check against
`df -h $HOME` at pull time, not against a number recorded here).

Model repo ids (confirmed by grepping each installed package's own source for its hardcoded
checkpoint constant — don't trust a web search result over this, package versions drift):

```bash
grep -n "SURYA_MODEL_CHECKPOINT\|_MODEL_CHECKPOINT" \
  "$VENV/lib/python3.12/site-packages/surya/settings.py"     # 5 separate small vikp/* repos for 0.6.13
grep -n "MODEL_CHECKPOINT" \
  "$VENV/lib/python3.12/site-packages/chandra/settings.py"   # datalab-to/chandra-ocr-2
olmocr --help | grep -A2 -- --model                          # allenai/olmOCR-2-7B-1025-FP8 default
```

surya 0.6.13's five checkpoints: `vikp/surya_det3`, `vikp/surya_rec2`, `vikp/surya_layout3`,
`vikp/surya_order`, `vikp/surya_tablerec` — small (150 MB–1 GB each, ~2 GB total), separate from
Surya 2's single unified `datalab-to/surya-ocr-2` repo (do **not** download that one for the
pinned `0.6.13`, it's the wrong generation entirely).

```bash
for repo in datalab-to/chandra-ocr-2 allenai/olmOCR-2-7B-1025-FP8 \
            vikp/surya_det3 vikp/surya_rec2 vikp/surya_layout3 vikp/surya_order vikp/surya_tablerec; do
  huggingface-cli download "$repo" --local-dir "./hf-cache/$repo"
done
rsync -avz --partial ./hf-cache/ "$OCR_SSH_HOST:$OCR_REMOTE_ROOT/hf-cache/"
```

`rsync --partial` matters for large files over a flaky link — a dropped connection mid-transfer
resumes instead of restarting from zero on retry.

## 4. Point each tool at the local weight paths (not repo ids)

**surya 0.6.13**: its `Settings` class is a pydantic `BaseSettings`, so every checkpoint constant
is overridable by environment variable of the same name — set these once, prepended into
`~/.bashrc` on the box the same way as step 1b (so `ocr-node.sh`'s bare `surya_ocr` call inherits
them automatically, no code changes needed):

```bash
DETECTOR_MODEL_CHECKPOINT="$HOME/$OCR_REMOTE_ROOT/hf-cache/vikp/surya_det3"
RECOGNITION_MODEL_CHECKPOINT="$HOME/$OCR_REMOTE_ROOT/hf-cache/vikp/surya_rec2"
LAYOUT_MODEL_CHECKPOINT="$HOME/$OCR_REMOTE_ROOT/hf-cache/vikp/surya_layout3"
ORDER_MODEL_CHECKPOINT="$HOME/$OCR_REMOTE_ROOT/hf-cache/vikp/surya_order"
TABLE_REC_MODEL_CHECKPOINT="$HOME/$OCR_REMOTE_ROOT/hf-cache/vikp/surya_tablerec"
```

**olmOCR / Chandra**: pass the local directory as the model argument directly (no env var needed)
— see step 5's `vllm serve` commands, which serve from the local path and set
`--served-model-name` to the canonical repo-id string so client-side `--model`/`VLLM_API_BASE`
references (which use the repo id, matching `ocr-node.sh`) still resolve correctly against the
server.

## 5. Start the persistent vLLM servers, one GPU each

Pick two currently-idle GPU indices from a fresh `nvidia-smi` read (see etiquette above).

```bash
ssh "$OCR_SSH_HOST" "source \$HOME/$OCR_REMOTE_ROOT/venv/bin/activate && \
  CUDA_VISIBLE_DEVICES=<idx-a> VLLM_USE_FLASHINFER_SAMPLER=0 tmux new-session -d -s ocr-olmocr \
  'vllm serve \$HOME/$OCR_REMOTE_ROOT/hf-cache/allenai/olmOCR-2-7B-1025-FP8 \
   --served-model-name allenai/olmOCR-2-7B-1025-FP8 --port 8000 2>&1 | tee \$HOME/$OCR_REMOTE_ROOT/vllm-olmocr.log'"
ssh "$OCR_SSH_HOST" "source \$HOME/$OCR_REMOTE_ROOT/venv/bin/activate && \
  CUDA_VISIBLE_DEVICES=<idx-b> VLLM_USE_FLASHINFER_SAMPLER=0 tmux new-session -d -s ocr-chandra \
  'vllm serve \$HOME/$OCR_REMOTE_ROOT/hf-cache/datalab-to/chandra-ocr-2 \
   --served-model-name datalab-to/chandra-ocr-2 --port 8001 --gpu-memory-utilization 0.6 --max-model-len 16384 \
   2>&1 | tee \$HOME/$OCR_REMOTE_ROOT/vllm-chandra.log'"
```

`VLLM_USE_FLASHINFER_SAMPLER=0` **works around a real, reproducible failure mode**: vLLM's default
FlashInfer top-k/top-p sampler JIT-compiles a CUDA kernel via `nvcc` on first use, and this fails
with `ninja: build stopped: subcommand failed` on any box where the installed `nvcc` toolkit
version is older than what the installed `flashinfer`/`torch` build targets (common — driver
version and `nvcc` toolkit version drift independently, and a driver supporting a newer CUDA
runtime doesn't imply a matching `nvcc` is installed). This env var forces the built-in
non-JIT sampler instead. If you don't hit this failure on a given box, it's a harmless no-op to
leave set.

Log the tee'd file to a `tmux`-external location (as above) so `tail`/`grep` over plain SSH can
read startup progress without attaching to the session.

Ports `8000` (olmOCR) / `8001` (Chandra) are the convention `remote/ocr-node.sh` expects
(`OLMOCR_PORT`/`CHANDRA_PORT` env vars, overridable).

`lib/probe.sh` only checks `:8000` (matching the plan's stated probe check); if Chandra's `:8001`
server isn't up, a run will still start but land with `agreement.m` short by one reader rather
than failing outright — `merge-canonical.py --reader` flags are only added for readers whose
manifest entry actually landed **and produced non-empty output** (see `ocr-node.sh`'s content
checks, not just exit-code/file-existence checks — a reader can exit 0 with a genuinely empty
result file when its own retries against a dead server give up silently).

Confirm both are answering before declaring provisioning done:

```bash
ssh "$OCR_SSH_HOST" 'curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/health'
ssh "$OCR_SSH_HOST" 'curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8001/health'
```

(A bare `curl -sf .../health` prints nothing at all on success — always check the actual status
code, don't infer health from silence.)

tmux (already present on the box) is the simplest option for keeping these alive across your SSH
session; systemd user units are the alternative if you want them to survive a reboot, which tmux
does not.

**If a `vllm serve` launch fails with `ValueError: Free memory on device cuda:0 (X/Y GiB) ... is
less than desired GPU memory utilization`** on a GPU that `nvidia-smi` and a bare
`torch.cuda.mem_get_info()` both report as fully idle (0 MiB used, correct UUID, no other process
attached) — this is a known, unresolved, reproducible-per-config failure mode on at least one box,
cause not identified (ruled out: cross-device collision via `CUDA_VISIBLE_DEVICES`/PCI enumeration
mismatch, a genuine memory leak from a prior crashed attempt, and `max-model-len`-driven profiling
overhead). Lowering `--gpu-memory-utilization` and `--max-model-len` are worth trying but were not
sufficient in the one case observed. Don't sink more than a few attempts into this — the pipeline
degrades gracefully to `m=1` (single reader) without the second server; see `references/backends.md`.

## 6. Confirm `remote/ocr-node.sh`'s reader invocation still matches reality

The `olmocr`/`chandra` CLI invocations in `remote/ocr-node.sh`'s `process_stem()` were confirmed
against real `--help` output as of the package versions in step 2 — but CLI shapes across major
version bumps of either tool are not guaranteed stable. Before trusting a fresh install's output,
re-verify:

```bash
ssh "$OCR_SSH_HOST" "source \$HOME/$OCR_REMOTE_ROOT/venv/bin/activate && olmocr --help"
ssh "$OCR_SSH_HOST" "source \$HOME/$OCR_REMOTE_ROOT/venv/bin/activate && chandra --help"
```

As of the pinned versions: `olmocr <workspace_dir> --pdfs <pdf> --model <id> --server
<url>/v1 [--markdown]` (workspace dir is positional, actual PDF path goes via `--pdfs`, output
lands under `<workspace_dir>` in Dolma-format `.jsonl`) and `chandra <input> <output_dir>
--method vllm` (both positional; no `--server` flag at all — the endpoint comes from the
`VLLM_API_BASE` env var, which **defaults to `http://localhost:8000/v1` — olmOCR's port** — so it
must always be set explicitly for Chandra or it silently talks to the wrong model server instead
of failing loudly).

**`olmocr` also needs `pdftoppm` (the `poppler-utils` package) installed on the box** to rasterize
PDF pages before sending them to the vLLM server — a small, safe, no-daemon system package (`sudo
apt-get install -y poppler-utils`), nothing like installing Docker. Without it, `olmocr` fails
with `pdftoppm is not installed` and every stem lands as reader-partial.

## 7. Re-probe

```bash
OCR_SSH_HOST="$OCR_SSH_HOST" bash lib/probe.sh
```

Should now print `[OCR] probe: '<host>' ready -- ...` instead of a missing-tools `FAIL setup`
message. Only once this passes is `OCR_BACKEND=remote` (or `auto`) ready for an actual end-to-end
test run — and even then, run it on the smallest available real document first, not a large batch,
since a full remote round-trip has more failure surface (SSH, rsync, two server processes, three
CLI invocations, a merge step) than any single piece suggests in isolation.

## Run directory layout on the box (for reference — created automatically by `lib/backend-remote.sh`)

```
$OCR_REMOTE_ROOT/
  venv/                          # step 2
  hf-cache/                      # step 3 (or a symlink to a larger drive, see etiquette above)
  bin/ocr-node.sh                # rsync'd fresh on every launch
  runs/<run_id>/
    in/<stem>.pdf                # rsync'd up, only stems still needing work
    out/<stem>/
      surya/...                  # surya_ocr --results_dir output, dual-path per ocr-pipeline.sh
      olmocr/...
      chandra/...
      manifest.tsv                # stage -> relative output path, written by ocr-node.sh
      .complete                   # marks this stem done, remote-side resume checkpoint
    status.log                    # append-only, tab-delimited, see remote/ocr-node.sh header
    node.stdout                    # ocr-node.sh's own stdout/stderr (verbose, not machine-parsed)
    PID                           # detached process id, for kill -0 liveness checks
    DONE                          # written once every input PDF has reached FINISHED or SKIP
```

All of `runs/<run_id>/` — the source PDF copy and every raw reader artifact — is working state,
not a data store: once `backend-remote.sh`'s `land_stem` has pulled a stem's artifacts down to the
local `$WORK/remote-out/<stem>/` and produced the final `.txt`/`canonical.json` locally, the
matching remote run directory can and should be deleted (`ssh "$OCR_SSH_HOST" "rm -rf
$OCR_REMOTE_ROOT/runs/<run_id>"`) — there's no reason to leave document copies sitting on a shared
multi-tenant box after processing completes. The venv, `hf-cache/`, and running vLLM servers are
reusable tooling, not document data, and don't need cleaning up between documents.
