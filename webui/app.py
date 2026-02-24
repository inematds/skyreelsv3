import os
import re
import sys
import subprocess
import threading
import queue
import time
import json
import glob
from pathlib import Path
from flask import Flask, render_template, request, jsonify, Response, send_file

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
RESULT_DIR = PROJECT_ROOT / "result"
UPLOAD_DIR = PROJECT_ROOT / "uploads"
VENV_PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"

UPLOAD_DIR.mkdir(exist_ok=True)
QUEUES_FILE = UPLOAD_DIR / "queues.json"

app = Flask(__name__)

# ---- Global generation state ----
generation_state = {
    "running": False,
    "log": [],
    "progress": 0,
    "total": 8,
    "status": "idle",  # idle | running | done | error
    "last_video": None,
    "current_job_id": None,
    "current_nq_id": None,
    "current_nq_name": None,
    "current_nq_scene": None,
}
log_queue = queue.Queue()

# ---- Job Queue ----
job_queue = []          # list of job dicts (all statuses)
job_queue_lock = threading.Lock()
_job_id_counter = 0

# ---- Named Queues ----
named_queues = []
nq_lock = threading.Lock()
_nq_id_counter = 0


def _next_nq_id():
    global _nq_id_counter
    _nq_id_counter += 1
    return _nq_id_counter


def _save_queues():
    """Persist named_queues to disk (called after every mutation)."""
    try:
        with nq_lock:
            data = json.loads(json.dumps(named_queues))  # deep copy via JSON
        # Reset transient states before saving
        for nq in data:
            if nq["status"] == "running":
                nq["status"] = "idle"
            for j in nq["jobs"]:
                if j["status"] in ("running", "pending"):
                    j["status"] = "idle"
        QUEUES_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"[queues] save error: {e}")


def _load_queues():
    """Load named_queues from disk on startup."""
    global _nq_id_counter, _job_id_counter
    if not QUEUES_FILE.exists():
        return
    try:
        data = json.loads(QUEUES_FILE.read_text())
        for nq in data:
            # Reset any in-flight states from previous run
            if nq.get("status") in ("running", "pending"):
                nq["status"] = "idle"
            for j in nq.get("jobs", []):
                if j.get("status") in ("running", "pending"):
                    j["status"] = "idle"
            named_queues.append(nq)
        # Restore counters to avoid ID collisions
        if named_queues:
            _nq_id_counter = max(nq["id"] for nq in named_queues)
            all_job_ids = [j["id"] for nq in named_queues for j in nq.get("jobs", [])]
            if all_job_ids:
                _job_id_counter = max(all_job_ids)
        print(f"[queues] loaded {len(named_queues)} queue(s) from {QUEUES_FILE}")
    except Exception as e:
        print(f"[queues] load error: {e}")


def _next_job_id():
    global _job_id_counter
    _job_id_counter += 1
    return _job_id_counter


# Patterns for named-queue reference resolution
_RE_PREV     = re.compile(r'^\{\{prev\}\}$', re.IGNORECASE)
_RE_JOB_IDX  = re.compile(r'^\{\{job:(\d+)\}\}$', re.IGNORECASE)
_RE_SEED_TS  = re.compile(r'result/[^/]+/(\d+)_<timestamp>\.mp4', re.IGNORECASE)


def _resolve_nq_refs(job, nq):
    """Return a shallow copy of job with forward-reference fields resolved.

    Supported syntaxes (in input_video / input_image / input_audio):
      {{prev}}       – output_video of the immediately previous job in the queue
      {{job:N}}      – output_video of the job at 0-based index N
      result/<task>/<seed>_<timestamp>.mp4  – resolved by matching seed (legacy compat)
    """
    if not nq:
        return job

    jobs = nq.get("jobs", [])
    idx  = job.get("nq_job_index", 0)

    def resolve(value):
        if not value or not isinstance(value, str):
            return value

        # {{prev}}
        if _RE_PREV.match(value):
            if idx > 0:
                out = jobs[idx - 1].get("output_video", "")
                if out:
                    print(f"[ref] {{{{prev}}}} → {out}")
                    return out
            print(f"[ref] warning: {{{{prev}}}} could not resolve (idx={idx})")
            return value

        # {{job:N}}
        m = _RE_JOB_IDX.match(value)
        if m:
            ref_idx = int(m.group(1))
            if 0 <= ref_idx < len(jobs):
                out = jobs[ref_idx].get("output_video", "")
                if out:
                    print(f"[ref] {{{{job:{ref_idx}}}}} → {out}")
                    return out
            print(f"[ref] warning: {{{{job:{m.group(1)}}}}} could not resolve")
            return value

        # result/<task>/<seed>_<timestamp>.mp4
        m = _RE_SEED_TS.search(value)
        if m:
            seed = m.group(1)
            for j in jobs:
                if str(j.get("seed", "")) == seed and j.get("output_video"):
                    print(f"[ref] <timestamp> seed={seed} → {j['output_video']}")
                    return j["output_video"]
            print(f"[ref] warning: <timestamp> seed={seed} not found in queue jobs")
            return value

        return value

    resolved = dict(job)
    for field in ("input_video", "input_image", "input_audio"):
        if field in resolved:
            resolved[field] = resolve(resolved[field])
    return resolved


def build_cmd_from_job(job):
    """Build generate_video.py command + env + metadata from a job dict."""
    task_type = job.get("task_type", "reference_to_video")
    prompt    = job.get("prompt", "")
    resolution = job.get("resolution", "540P")
    duration  = str(job.get("duration", 5))
    seed      = str(job.get("seed", 42))
    offload   = bool(job.get("offload", True))
    low_vram  = bool(job.get("low_vram", False))

    # talking_avatar only supports 480P / 720P
    if task_type == "talking_avatar" and resolution == "540P":
        resolution = "480P"

    cmd = [
        str(VENV_PYTHON), str(PROJECT_ROOT / "generate_video.py"),
        "--task_type", task_type,
        "--prompt", prompt,
        "--resolution", resolution,
        "--duration", duration,
        "--seed", seed,
    ]

    if low_vram:
        cmd.append("--low_vram")
    elif offload:
        cmd.append("--offload")

    # Task-specific params
    if task_type == "reference_to_video":
        ref_imgs = job.get("ref_imgs", [])
        if isinstance(ref_imgs, list):
            ref_imgs = ",".join(ref_imgs)
        if ref_imgs:
            cmd += ["--ref_imgs", ref_imgs]

    if task_type in ("single_shot_extension", "shot_switching_extension"):
        input_video = job.get("input_video", "")
        if input_video:
            cmd += ["--input_video", input_video]

    if task_type == "talking_avatar":
        input_image = job.get("input_image", "")
        input_audio = job.get("input_audio", "")
        if input_image:
            cmd += ["--input_image", input_image]
        if input_audio:
            cmd += ["--input_audio", input_audio]

    env_extra = {}
    if low_vram:
        env_extra["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

    # Metadata for JSON sidecar
    metadata = {
        "task_type": task_type,
        "prompt": prompt or "(sem prompt)",
        "resolution": resolution,
        "seed": seed,
        "offload": low_vram or offload,
        "low_vram": low_vram,
    }
    if task_type == "reference_to_video":
        ref_imgs = job.get("ref_imgs", [])
        if isinstance(ref_imgs, str):
            ref_imgs = [r.strip() for r in ref_imgs.split(",") if r.strip()]
        metadata["ref_imgs"] = ref_imgs
        metadata["duration"] = duration + "s"
    if task_type in ("single_shot_extension", "shot_switching_extension"):
        metadata["input_video"] = job.get("input_video", "")
        metadata["duration"] = duration + "s"
    if task_type == "talking_avatar":
        metadata["input_image"] = job.get("input_image", "")
        metadata["input_audio"] = job.get("input_audio", "")
        metadata["duration"] = "determinado pelo áudio"

    return cmd, env_extra, metadata


def start_next_queued_job():
    """Called when a generation finishes. Picks the next pending job."""
    if generation_state["running"]:
        return
    with job_queue_lock:
        for job in job_queue:
            if job["status"] == "pending":
                job["status"] = "running"
                job["started_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                # Resolve named-queue references ({{prev}}, {{job:N}}, <timestamp>)
                nq = None
                if job.get("nq_id") is not None:
                    with nq_lock:
                        nq = next((q for q in named_queues if q["id"] == job["nq_id"]), None)
                effective_job = _resolve_nq_refs(job, nq)
                cmd, env_extra, metadata = build_cmd_from_job(effective_job)
                thread = threading.Thread(
                    target=run_generation,
                    args=(cmd, env_extra, metadata, job),
                    daemon=True,
                )
                thread.start()
                return


def _nq_job_done_hook(job):
    """Called after each job finishes. Stops the queue on error; marks done when all finish."""
    nq_id = job.get("nq_id")
    if nq_id is None:
        return
    with nq_lock:
        nq = next((q for q in named_queues if q["id"] == nq_id), None)
        if nq is None:
            return
        # If this job failed, cancel all remaining pending jobs for this queue
        if job.get("status") == "error":
            with job_queue_lock:
                for j in nq["jobs"]:
                    if j["status"] == "pending":
                        j["status"] = "idle"
                        # Remove from global job_queue so they won't start
                        if j in job_queue:
                            job_queue.remove(j)
            nq["status"] = "error"
        else:
            still_active = any(j["status"] in ("pending", "running") for j in nq["jobs"])
            all_finished = all(j["status"] in ("done", "error") for j in nq["jobs"])
            if not still_active:
                if all_finished:
                    any_error = any(j["status"] == "error" for j in nq["jobs"])
                    nq["status"] = "error" if any_error else "done"
                else:
                    nq["status"] = "idle"  # some jobs still idle
    _save_queues()


def run_named_queue(nq_id):
    """Schedule all idle jobs of a named queue for sequential execution."""
    with nq_lock:
        nq = next((q for q in named_queues if q["id"] == nq_id), None)
        if nq is None or nq["status"] == "running":
            return False
        pending_jobs = [j for j in nq["jobs"] if j["status"] == "idle"]
        if not pending_jobs:
            return False
        nq["status"] = "running"
        for j in pending_jobs:
            j["status"] = "pending"

    with job_queue_lock:
        for j in pending_jobs:
            if not any(ex["id"] == j["id"] for ex in job_queue):
                job_queue.append(j)

    if not generation_state["running"]:
        start_next_queued_job()
    return True


def run_single_nq_job_fn(nq_id, job_id):
    """Schedule a single named queue job for execution."""
    with nq_lock:
        nq = next((q for q in named_queues if q["id"] == nq_id), None)
        if nq is None:
            return False
        job = next((j for j in nq["jobs"] if j["id"] == job_id), None)
        if job is None or job["status"] in ("running", "pending"):
            return False
        job["status"] = "pending"
        if nq["status"] == "idle":
            nq["status"] = "running"

    with job_queue_lock:
        if not any(j["id"] == job_id for j in job_queue):
            job_queue.append(job)

    if not generation_state["running"]:
        start_next_queued_job()
    return True


def run_generation(cmd, env_extra=None, metadata=None, job=None):
    generation_state["running"] = True
    generation_state["log"] = []
    generation_state["progress"] = 0
    generation_state["status"] = "running"
    generation_state["last_video"] = None
    generation_state["current_job_id"] = job["id"] if job else None

    # Named queue progress info
    nq_id = job.get("nq_id") if job else None
    if nq_id is not None:
        with nq_lock:
            nq = next((q for q in named_queues if q["id"] == nq_id), None)
            if nq:
                idx = next((i + 1 for i, j in enumerate(nq["jobs"]) if j["id"] == job["id"]), 1)
                total = len(nq["jobs"])
                generation_state["current_nq_id"]   = nq_id
                generation_state["current_nq_name"] = nq["name"]
                generation_state["current_nq_scene"] = f"Cena {idx}/{total} — {job.get('label', '')}"
    else:
        generation_state["current_nq_id"]   = None
        generation_state["current_nq_name"] = None
        generation_state["current_nq_scene"] = None

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    if env_extra:
        env.update(env_extra)

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=str(PROJECT_ROOT),
            env=env,
        )

        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue

            generation_state["log"].append(line)
            log_queue.put(line)

            # Parse progress from tqdm output e.g. " 25%|██▌  | 2/8"
            if "/8 [" in line or "/4 [" in line:
                try:
                    part = line.strip().split("|")[0].strip().rstrip("%")
                    pct = int(part)
                    generation_state["progress"] = pct
                except Exception:
                    pass

        proc.wait()

        if proc.returncode == 0:
            generation_state["status"] = "done"
            if job:
                job["status"] = "done"
                job["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            # Find latest video
            videos = sorted(RESULT_DIR.rglob("*.mp4"), key=lambda p: p.stat().st_mtime)
            if videos:
                last_video = videos[-1]
                generation_state["last_video"] = str(last_video.relative_to(PROJECT_ROOT))
                if job:
                    job["output_video"] = generation_state["last_video"]
                # Save metadata JSON alongside the video
                if metadata:
                    metadata["generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    meta_path = last_video.with_suffix(".json")
                    meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2))
        else:
            generation_state["status"] = "error"
            if job:
                job["status"] = "error"
                job["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

    except Exception as e:
        generation_state["log"].append(f"ERROR: {e}")
        generation_state["status"] = "error"
        if job:
            job["status"] = "error"
            job["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    finally:
        generation_state["running"] = False
        generation_state["current_job_id"] = None
        log_queue.put("__DONE__")
        # Update named queue status
        if job:
            _nq_job_done_hook(job)
        generation_state["current_nq_id"]    = None
        generation_state["current_nq_name"]  = None
        generation_state["current_nq_scene"] = None
        # Auto-start next pending job
        start_next_queued_job()


# ---- Parse Markdown queue format ----
def parse_md_queue(md_text):
    """Parse a queue from Markdown format. Returns list of job dicts."""
    jobs = []
    current = {}
    for line in md_text.splitlines():
        stripped = line.strip()
        # New job block on ## heading
        if stripped.startswith("##") or (stripped.startswith("#") and not stripped.startswith("##")):
            if current and "task_type" in current:
                jobs.append(current)
            current = {}
        elif stripped.startswith("- "):
            parts = stripped[2:].split(":", 1)
            if len(parts) == 2:
                key = parts[0].strip()
                val = parts[1].strip()
                # Type coercion
                if key in ("duration", "seed"):
                    try:
                        val = int(val)
                    except ValueError:
                        pass
                elif key == "ref_imgs":
                    val = [v.strip() for v in val.split(",") if v.strip()]
                elif key in ("offload", "low_vram"):
                    val = val.lower() in ("true", "yes", "1", "sim")
                current[key] = val
    if current and "task_type" in current:
        jobs.append(current)
    return jobs


# ============================================================
# Routes
# ============================================================

@app.route("/")
def index():
    videos = []
    if RESULT_DIR.exists():
        for v in sorted(RESULT_DIR.rglob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
            size_mb = v.stat().st_size / 1024 / 1024
            videos.append({
                "path": str(v.relative_to(PROJECT_ROOT)),
                "name": v.name,
                "task": v.parent.name,
                "size": f"{size_mb:.1f} MB",
                "has_meta": v.with_suffix(".json").exists(),
            })
    return render_template("index.html", videos=videos)


@app.route("/generate", methods=["POST"])
def generate():
    data = request.form

    task_type  = data.get("task_type", "reference_to_video")
    prompt     = data.get("prompt", "")
    resolution = data.get("resolution", "540P")
    duration   = int(data.get("duration", 5))
    seed       = int(data.get("seed", 42))
    offload    = data.get("offload", "true") == "true"
    low_vram   = data.get("low_vram", "false") == "true"

    job = {
        "id": _next_job_id(),
        "task_type": task_type,
        "prompt": prompt,
        "resolution": resolution,
        "duration": duration,
        "seed": seed,
        "offload": offload,
        "low_vram": low_vram,
        "status": "pending",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "label": f"{task_type} — seed {seed}",
    }

    # Handle file uploads for reference_to_video
    if task_type == "reference_to_video":
        ref_imgs = []
        files = request.files.getlist("ref_imgs")
        for f in files:
            if f and f.filename:
                safe_name = re.sub(r'[^\w\-.]', '_', f.filename)
                save_path = UPLOAD_DIR / safe_name
                f.save(str(save_path))
                ref_imgs.append(str(save_path))
        manual = data.get("ref_imgs_path", "").strip()
        if manual:
            ref_imgs += [p.strip() for p in manual.split(",") if p.strip()]
        if not ref_imgs:
            return jsonify({"error": "Informe ao menos uma imagem de referência"}), 400
        job["ref_imgs"] = ref_imgs

    # Handle input_video for extension tasks
    if task_type in ("single_shot_extension", "shot_switching_extension"):
        input_video = data.get("input_video", "").strip()
        if not input_video:
            return jsonify({"error": "Informe o vídeo de entrada"}), 400
        job["input_video"] = input_video

    # Handle talking_avatar inputs
    if task_type == "talking_avatar":
        input_image_file = request.files.get("input_image_file")
        if input_image_file and input_image_file.filename:
            safe_name = re.sub(r'[^\w\-.]', '_', input_image_file.filename)
            save_path = UPLOAD_DIR / safe_name
            input_image_file.save(str(save_path))
            job["input_image"] = str(save_path)
        else:
            input_image = data.get("input_image", "").strip()
            if not input_image:
                return jsonify({"error": "Informe a imagem do retrato"}), 400
            job["input_image"] = input_image

        input_audio_file = request.files.get("input_audio_file")
        if input_audio_file and input_audio_file.filename:
            safe_name = re.sub(r'[^\w\-.]', '_', input_audio_file.filename)
            save_path = UPLOAD_DIR / safe_name
            input_audio_file.save(str(save_path))
            job["input_audio"] = str(save_path)
        else:
            input_audio = data.get("input_audio", "").strip()
            if not input_audio:
                return jsonify({"error": "Informe o arquivo de áudio"}), 400
            job["input_audio"] = input_audio

    # Enqueue and auto-start if idle
    with job_queue_lock:
        job_queue.append(job)

    if not generation_state["running"]:
        start_next_queued_job()

    return jsonify({"ok": True, "job_id": job["id"]})


@app.route("/stream")
def stream():
    def event_gen():
        for line in generation_state["log"]:
            yield f"data: {json.dumps({'log': line})}\n\n"

        while True:
            try:
                line = log_queue.get(timeout=1)
                if line == "__DONE__":
                    payload = {
                        "status": generation_state["status"],
                        "progress": generation_state["progress"],
                        "video": generation_state.get("last_video"),
                    }
                    yield f"data: {json.dumps({'done': payload})}\n\n"
                    break
                yield f"data: {json.dumps({'log': line, 'progress': generation_state['progress']})}\n\n"
            except queue.Empty:
                if not generation_state["running"]:
                    break
                yield f"data: {json.dumps({'ping': True, 'progress': generation_state['progress'], 'nq_scene': generation_state.get('current_nq_scene')})}\n\n"

    return Response(event_gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/status")
def status():
    return jsonify(generation_state)


@app.route("/video/<path:filepath>")
def serve_video(filepath):
    full = PROJECT_ROOT / filepath
    if not full.exists():
        return "Not found", 404
    return send_file(str(full), mimetype="video/mp4")


@app.route("/video-meta/<path:filepath>")
def video_meta(filepath):
    full = PROJECT_ROOT / filepath
    meta = full.with_suffix(".json")
    if not meta.exists():
        return jsonify({}), 404
    return jsonify(json.loads(meta.read_text()))


@app.route("/videos")
def list_videos():
    videos = []
    if RESULT_DIR.exists():
        for v in sorted(RESULT_DIR.rglob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
            size_mb = v.stat().st_size / 1024 / 1024
            videos.append({
                "path": str(v.relative_to(PROJECT_ROOT)),
                "name": v.name,
                "task": v.parent.name,
                "size": f"{size_mb:.1f} MB",
                "has_meta": v.with_suffix(".json").exists(),
            })
    return jsonify(videos)


# ---- Queue endpoints ----

@app.route("/queue", methods=["GET"])
def get_queue():
    with job_queue_lock:
        return jsonify(list(job_queue))


@app.route("/queue/add", methods=["POST"])
def queue_add():
    data = request.get_json(force=True, silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "JSON inválido"}), 400
    if not data.get("task_type"):
        return jsonify({"error": "task_type obrigatório"}), 400

    job = {
        "id": _next_job_id(),
        "status": "pending",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "label": data.get("label") or f"{data['task_type']} — seed {data.get('seed', 42)}",
        **data,
    }
    with job_queue_lock:
        job_queue.append(job)

    if not generation_state["running"]:
        start_next_queued_job()

    return jsonify({"ok": True, "id": job["id"]})


@app.route("/queue/clear", methods=["POST"])
def queue_clear():
    with job_queue_lock:
        removed = sum(1 for j in job_queue if j["status"] == "pending")
        job_queue[:] = [j for j in job_queue if j["status"] != "pending"]
    return jsonify({"ok": True, "removed": removed})


@app.route("/queue/remove/<int:job_id>", methods=["POST"])
def queue_remove(job_id):
    with job_queue_lock:
        for i, job in enumerate(job_queue):
            if job["id"] == job_id and job["status"] == "pending":
                job_queue.pop(i)
                return jsonify({"ok": True})
    return jsonify({"error": "Job não encontrado ou não está pendente"}), 404


@app.route("/queue/import", methods=["POST"])
def queue_import():
    content = request.data.decode("utf-8").strip()
    if not content:
        return jsonify({"error": "Conteúdo vazio"}), 400

    try:
        # Auto-detect format
        if content.startswith("[") or content.startswith("{"):
            raw = json.loads(content)
            if isinstance(raw, dict):
                raw = [raw]
            jobs_data = raw
        else:
            jobs_data = parse_md_queue(content)

        added = 0
        with job_queue_lock:
            for data in jobs_data:
                if not data.get("task_type"):
                    continue
                job = {
                    "id": _next_job_id(),
                    "status": "pending",
                    "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "label": data.get("label") or f"{data['task_type']} — seed {data.get('seed', 42)}",
                    **data,
                }
                job_queue.append(job)
                added += 1

        if added > 0 and not generation_state["running"]:
            start_next_queued_job()

        return jsonify({"ok": True, "added": added})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/doc/<path:filename>")
def serve_doc(filename):
    doc_dir = PROJECT_ROOT / "doc"
    full = doc_dir / filename
    if not full.exists() or not full.is_file():
        return "Not found", 404
    return send_file(str(full), mimetype="text/plain; charset=utf-8")


@app.route("/doc/download/<path:filename>")
def download_doc(filename):
    doc_dir = PROJECT_ROOT / "doc"
    full = doc_dir / filename
    if not full.exists() or not full.is_file():
        return "Not found", 404
    return send_file(str(full), as_attachment=True, download_name=filename)


@app.route("/help")
def help_page():
    return render_template("help.html")


# ---- Named Queue endpoints ----

@app.route("/nqueues", methods=["GET"])
def get_named_queues():
    with nq_lock:
        result = [{
            "id": nq["id"],
            "name": nq["name"],
            "status": nq["status"],
            "job_count": len(nq["jobs"]),
            "done_count": sum(1 for j in nq["jobs"] if j["status"] == "done"),
            "error_count": sum(1 for j in nq["jobs"] if j["status"] == "error"),
            "created_at": nq["created_at"],
        } for nq in named_queues]
    return jsonify(result)


@app.route("/nqueues", methods=["POST"])
def create_named_queue():
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"error": "JSON inválido"}), 400
    name = data.get("name") or f"Fila {len(named_queues) + 1}"
    jobs_data = data.get("jobs", [])
    if isinstance(jobs_data, dict):
        jobs_data = [jobs_data]

    nq_id = _next_nq_id()
    jobs = []
    for i, jd in enumerate(jobs_data):
        if not jd.get("task_type"):
            continue
        jobs.append({
            "id": _next_job_id(),
            "nq_id": nq_id,
            "nq_job_index": i,
            "status": "idle",
            "label": jd.get("label") or f"{jd['task_type']} — seed {jd.get('seed', 42)}",
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "output_video": "",
            **{k: v for k, v in jd.items() if k not in ("id", "nq_id", "status")},
        })

    nq = {
        "id": nq_id,
        "name": name,
        "status": "idle",
        "jobs": jobs,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with nq_lock:
        named_queues.append(nq)
    _save_queues()
    return jsonify({"ok": True, "id": nq_id})


@app.route("/nqueues/import", methods=["POST"])
def import_nq_route():
    content = request.data.decode("utf-8").strip()
    name = request.args.get("name") or f"Fila {len(named_queues) + 1}"
    if not content:
        return jsonify({"error": "Conteúdo vazio"}), 400
    try:
        if content.startswith("[") or content.startswith("{"):
            raw = json.loads(content)
            if isinstance(raw, dict):
                raw = [raw]
            jobs_data = raw
        else:
            jobs_data = parse_md_queue(content)

        nq_id = _next_nq_id()
        jobs = []
        for i, jd in enumerate(jobs_data):
            if not jd.get("task_type"):
                continue
            jobs.append({
                "id": _next_job_id(),
                "nq_id": nq_id,
                "nq_job_index": i,
                "status": "idle",
                "label": jd.get("label") or f"{jd['task_type']} — seed {jd.get('seed', 42)}",
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "output_video": "",
                **{k: v for k, v in jd.items() if k not in ("id", "nq_id", "status")},
            })

        nq = {
            "id": nq_id,
            "name": name,
            "status": "idle",
            "jobs": jobs,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        with nq_lock:
            named_queues.append(nq)
        _save_queues()
        return jsonify({"ok": True, "id": nq_id, "name": name, "job_count": len(jobs)})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/nqueues/<int:nq_id>", methods=["GET"])
def get_named_queue_detail(nq_id):
    with nq_lock:
        nq = next((q for q in named_queues if q["id"] == nq_id), None)
    if nq is None:
        return jsonify({"error": "Fila não encontrada"}), 404
    return jsonify(nq)


@app.route("/nqueues/<int:nq_id>", methods=["DELETE"])
def delete_named_queue_route(nq_id):
    with nq_lock:
        nq = next((q for q in named_queues if q["id"] == nq_id), None)
        if nq is None:
            return jsonify({"error": "Fila não encontrada"}), 404
        if nq["status"] == "running":
            return jsonify({"error": "Não é possível excluir uma fila em execução"}), 400
        named_queues.remove(nq)
    _save_queues()
    return jsonify({"ok": True})


@app.route("/nqueues/<int:nq_id>/run", methods=["POST"])
def run_nq_route(nq_id):
    ok = run_named_queue(nq_id)
    if not ok:
        return jsonify({"error": "Fila não encontrada, já em execução, ou sem cenas pendentes"}), 400
    return jsonify({"ok": True})


@app.route("/nqueues/<int:nq_id>/jobs/<int:job_id>/run", methods=["POST"])
def run_nq_job_route(nq_id, job_id):
    ok = run_single_nq_job_fn(nq_id, job_id)
    if not ok:
        return jsonify({"error": "Cena não encontrada ou já em execução"}), 400
    return jsonify({"ok": True})


@app.route("/nqueues/<int:nq_id>/reset", methods=["POST"])
def reset_nq_route(nq_id):
    """Reset all error/idle jobs to idle and re-run the full queue from scratch."""
    with nq_lock:
        nq = next((q for q in named_queues if q["id"] == nq_id), None)
        if nq is None:
            return jsonify({"error": "Fila não encontrada"}), 404
        if nq["status"] == "running":
            return jsonify({"error": "Não é possível reiniciar uma fila em execução"}), 400
        for j in nq["jobs"]:
            if j["status"] in ("error", "idle"):
                j["status"] = "idle"
                j["output_video"] = ""
                j.pop("started_at", None)
                j.pop("finished_at", None)
    _save_queues()
    ok = run_named_queue(nq_id)
    if not ok:
        return jsonify({"error": "Sem cenas a executar"}), 400
    return jsonify({"ok": True})


@app.route("/nqueues/<int:nq_id>/finalize", methods=["POST"])
def finalize_nq_route(nq_id):
    return jsonify({"error": "Em desenvolvimento — ffmpeg concat ainda não implementado"}), 501


_load_queues()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7860, debug=False)
