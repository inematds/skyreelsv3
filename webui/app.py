import io
import os
import re
import sys
import uuid
import subprocess
import threading
import queue
import time
import json
import glob
import zipfile
from pathlib import Path
from flask import Flask, render_template, request, jsonify, Response, send_file
from werkzeug.utils import secure_filename

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
RESULT_DIR = PROJECT_ROOT / "result"
UPLOAD_DIR = PROJECT_ROOT / "uploads"
VENV_PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"

UPLOAD_DIR.mkdir(exist_ok=True)
QUEUES_FILE = UPLOAD_DIR / "queues.json"

PROJECTS_DIR = PROJECT_ROOT / "projetos"
PROJECTS_DIR.mkdir(exist_ok=True)

GLOBAL_CONFIG_FILE   = UPLOAD_DIR / "global_config.json"
SYSTEM_PROMPT_FILE   = UPLOAD_DIR / "system_prompt_episode.txt"

DEFAULT_SYSTEM_PROMPT = """\
Você é um assistente de produção de série animada com IA (SkyReels V3). A partir da descrição do episódio e dos recursos do projeto, gere um array JSON com TODAS as cenas necessárias para cobrir a história completa.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DESCRIÇÃO DO EPISÓDIO:
{description}

{resources}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PARÂMETROS TÉCNICOS:
- Task type   : {task_type}
- Resolução   : {resolution}
- Duração/cena: ~{duration}s (ajuste conforme ritmo de cada cena)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REFERÊNCIA DAS TASKS DO SKYREELS V3:

• reference_to_video — Gera vídeo a partir de 1–4 imagens de referência + prompt de texto (modelo 14B).
  O campo "ref_imgs" é OBRIGATÓRIO (paths das imagens do personagem/ambiente da cena).
  O "prompt" descreve o movimento e ação que ocorre no vídeo.

• single_shot_extension — Estende um vídeo existente por 5–30s (modelo 14B).
  Usado quando a cena anterior precisa continuar sem corte.

• shot_switching_extension — Estende com transição cinemática de câmera, máx. 5s (modelo 14B).
  Usado para mudança de ângulo ou ambiente com transição suave.

• talking_avatar — Gera avatar falante a partir de retrato + áudio, até 200s (modelo 19B).
  Requer "input_image" (portrait) e "input_audio" (arquivo de áudio).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REGRAS OBRIGATÓRIAS — preencha TODOS os campos:

1. PROMPT DE VÍDEO (campo "prompt"):
   - Descrição cinemática detalhada em INGLÊS
   - Inclua: composição, iluminação, movimento de câmera, emoção da cena, ação dos personagens
   - Exemplo: "Medium shot, Valen stands at school corridor, morning sunlight through windows, she turns to look at Lumi, curious expression, soft camera pan right, anime style, 2030 futuristic school"

2. PROMPT DE IMAGEM (campo "image_prompt"):
   - Prompt em INGLÊS para geração de imagem estática via fal.ai / Flux
   - Descreva: personagens presentes, ambiente, cores dominantes, estilo artístico, iluminação, ângulo
   - Mantenha estilo visual consistente com os personagens do projeto
   - Exemplo: "anime style illustration, 2030 futuristic school corridor, teenage girl with purple hair and confident expression, warm morning light, detailed background, vibrant colors"

3. TEXTO DE ÁUDIO (campo "audio_text"):
   - Narração ou diálogos em PORTUGUÊS BRASILEIRO para geração via ElevenLabs
   - Inclua APENAS o que será falado/narrado nesta cena
   - Se a cena for silenciosa ou só musical, use string vazia: ""
   - Mantenha tom e personalidade dos personagens conforme os documentos do projeto
   - Exemplo: "Valen olha para Lumi e diz: Você também vai para a turma do Professor Dex?"

4. IMAGENS DE REFERÊNCIA (campo "ref_imgs"):
   - Use os paths EXATOS das imagens listadas nos recursos acima
   - MÁXIMO 4 imagens por cena — NUNCA coloque mais de 4 (limite técnico do pipeline)
   - REGRA DE CONSISTÊNCIA DE AMBIENTE: SEMPRE inclua a imagem do local/ambiente em TODA
     cena que acontece naquele ambiente — inclusive closes e planos de diálogo.
     Sem a imagem do ambiente, o modelo gera um fundo aleatório e inconsistente.
   - Composição ideal por cena:
     · Cena de estabelecimento (wide/panorâmica): ambiente + 1-2 personagens presentes
     · Close/diálogo: personagem que fala + ambiente onde a cena ocorre
     · Grupo: até 2 personagens principais + ambiente (máx 3 refs, reserve 1 slot para variação)
   - Exemplo correto (close em corredor): ["projetos/X/imagens/valen.png", "projetos/X/imagens/escola.png"]
   - Exemplo ERRADO (close sem ambiente): ["projetos/X/imagens/valen.png"]  ← fundo inconsistente!
   - ⚠ PROIBIDO: colocar duas imagens diferentes que mostrem o MESMO personagem — isso
     DUPLICA o personagem na cena (duas cópias do mesmo personagem aparecem lado a lado).
     Use NO MÁXIMO uma imagem por personagem.
   - ⚠ USE A IMAGEM CORRETA para o tipo de personagem: se o personagem é um ANIMAL
     (ratinho, cachorro, robô, etc.), use a imagem desse animal — NUNCA substitua por uma
     imagem de personagem humano para representá-lo.

5. VOZ DO PERSONAGEM (campo "voice_id"):
   - Extraia o voice_id do ElevenLabs diretamente dos documentos do projeto (tabela de casting)
   - Coloque o voice_id do personagem principal que fala ou narra a cena
   - Se a cena for silenciosa ou a voz for genérica/narradora, use string vazia: ""
   - NÃO invente voice_ids — use SOMENTE os que estão explicitamente nos docs do projeto
   - Exemplo: "FIEA0c5UHH9JnvWaQrXS" (Valen), "vibfi5nlk3hs8Mtvf9Oy" (Lumi), etc.

6. TRILHA DE FUNDO (campo "audio_bg"):
   - Path para arquivo de música/trilha do projeto (pasta audios/ do projeto)
   - Mixada a 28% do volume sobre a narração/diálogo (ou sozinha se audio_text vazio)
   - Use para: cenas épicas, panorâmicas, momentos de tensão, transições sem diálogo
   - Se não há trilha disponível ou a cena não precisa, use string vazia: ""
   - Exemplo: "projetos/INETUSX/audios/tema_principal.mp3"

7. CONSISTÊNCIA NARRATIVA:
   - Use os documentos do projeto como base de conhecimento absoluta para personagens, universo e vozes
   - Use EXATAMENTE os nomes dos personagens conforme os documentos do projeto — NUNCA invente
     nomes alternativos ou genéricos (ex: se o personagem chama "Ratinho", não use "Rato" ou "ratinho")
   - ⚠ COERÊNCIA AÇÃO/DIREÇÃO: o audio_text e o prompt de vídeo DEVEM descrever a MESMA
     ação na MESMA direção. Se a narração diz "subindo a escada", o prompt DEVE dizer
     "walking UP the stairs" — jamais "walking down". Contradições entre áudio e vídeo
     destroem completamente a coerência narrativa.
   - Distribua imagens de referência coerentemente (personagem correto em cada cena)
   - Adapte duração conforme intensidade narrativa (~{duration}s como base)
   - Cubra TODA a história descrita — não pule cenas importantes

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Retorne SOMENTE um array JSON válido, sem texto antes ou depois, começando com [ e terminando com ].
Cada cena deve seguir EXATAMENTE este formato:
{json_template}

APENAS o JSON. Nada mais.\
"""


def _load_system_prompt():
    if SYSTEM_PROMPT_FILE.exists():
        return SYSTEM_PROMPT_FILE.read_text(encoding="utf-8")
    return DEFAULT_SYSTEM_PROMPT


def _load_global_config():
    if GLOBAL_CONFIG_FILE.exists():
        try:
            return json.loads(GLOBAL_CONFIG_FILE.read_text())
        except Exception:
            pass
    return {}

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

# ---- Episode AI Generation (background) ----
# {job_id: {status: pending|done|error, jobs: [], saved_doc: str, error: str, project: str}}
_ep_gen_state: dict = {}
_ep_gen_by_project: dict = {}   # {proj_name: job_id}  — último job por projeto
_ep_gen_lock = threading.Lock()

# ---- Named Queues ----
named_queues = []
nq_lock = threading.Lock()
_nq_id_counter = 0

# ---- Background episode generation ----
_ep_gen_state: dict = {}       # job_id -> {status, jobs, saved_doc, ep_title, error, raw}
_ep_gen_by_project: dict = {}  # project_name -> job_id (latest)
_ep_gen_lock = threading.Lock()


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
        # Atribuir ep_code a episódios existentes que não têm código
        _proj_counters: dict = {}
        for nq in named_queues:
            proj = nq.get("project", "")
            if proj and not nq.get("ep_code"):
                _proj_counters[proj] = _proj_counters.get(proj, 0) + 1
                nq["ep_code"] = f"EP{_proj_counters[proj]:03d}"
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


def _parse_project_voices(proj_name: str) -> dict:
    """Lê os docs do projeto e extrai mapa {nome_personagem: voice_id} de tabelas Markdown.
    Procura pela coluna 'Voice ID' (3ª coluna) em tabelas pipe-separadas.
    Padrão: | Personagem | Voz | voice_id | ...
    """
    voices: dict = {}
    docs_dir = PROJECTS_DIR / proj_name / "docs"
    if not docs_dir.exists():
        return voices
    # ElevenLabs voice IDs: alphanum, 15–25 chars
    # Captura: | Nome | qualquer_coisa | VOICE_ID |
    row_re = re.compile(r'^\|\s*([^|]+?)\s*\|[^|]*\|\s*([A-Za-z0-9]{15,25})\s*\|')
    skip_names = {"personagem", "character", "nome", "voz", "voice", "perfil"}
    for f in sorted(docs_dir.glob("*.md")):
        for line in f.read_text(errors="ignore").splitlines():
            m = row_re.match(line.strip())
            if not m:
                continue
            name = m.group(1).strip()
            vid  = m.group(2).strip()
            if name.lower() in skip_names:
                continue
            voices[name] = vid
    return voices


def _match_voice(voices: dict, label: str, fallback: str) -> str:
    """Retorna o voice_id do personagem cujo nome aparece MAIS CEDO no label da cena.
    Evita falso match quando múltiplos personagens estão no título (ex: 'Lumi Chama Valen').
    """
    label_lower = label.lower()
    best_pos = len(label_lower) + 1
    best_vid = fallback
    for name, vid in voices.items():
        first = name.split()[0].lower()
        idx = label_lower.find(first)
        if idx != -1 and idx < best_pos:
            best_pos = idx
            best_vid = vid
    return best_vid


def _next_ep_code(proj_name: str) -> str:
    """Gera o próximo código sequencial de episódio para um projeto (EP001, EP002, ...)."""
    existing = [
        q.get("ep_code", "")
        for q in named_queues
        if q.get("project") == proj_name and q.get("ep_code", "").startswith("EP")
    ]
    nums = []
    for code in existing:
        try:
            nums.append(int(code[2:]))
        except ValueError:
            pass
    n = max(nums, default=0) + 1
    return f"EP{n:03d}"


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
        if isinstance(ref_imgs, str):
            ref_imgs = [r.strip() for r in ref_imgs.split(",") if r.strip()]
        ref_imgs = ref_imgs[:4]  # pipeline limita a 4 imagens (MAX_ALLOWED_REF_IMG_LENGTH)
        if ref_imgs:
            cmd += ["--ref_imgs", ",".join(ref_imgs)]

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
                    # Auto-mix audio (reference_to_video/extension geram vídeo silencioso)
                    if job.get("task_type") != "talking_avatar":
                        sp_str = job.get("input_audio", "")
                        bg_str = job.get("audio_bg", "")
                        sp = (PROJECT_ROOT / sp_str) if sp_str else None
                        bg = (PROJECT_ROOT / bg_str) if bg_str else None
                        sp = sp if (sp and sp.exists()) else None
                        bg = bg if (bg and bg.exists()) else None
                        if sp or bg:
                            _mix_audio_scene(last_video, speech_path=sp, bg_path=bg)
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


@app.route("/uploads/list")
def list_uploads():
    """Lista todos os arquivos na pasta uploads/ (nível raiz, sem subpastas).
    Retorna 'files' (imagens) e 'docs' (textos/outros) separados.
    """
    IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
    SKIP       = {"queues.json", "global_config.json"}
    images, docs = [], []
    for f in sorted(UPLOAD_DIR.iterdir()):
        if not f.is_file() or f.name in SKIP:
            continue
        entry = {
            "name": f.name,
            "size": f.stat().st_size,
            "path": str(f.relative_to(PROJECT_ROOT)),
        }
        if f.suffix.lower() in IMAGE_EXTS:
            images.append(entry)
        else:
            docs.append(entry)
    return jsonify({"files": images, "docs": docs})


@app.route("/file/<path:filepath>")
def serve_file(filepath):
    """Serve any project file inline (for image thumbnails, etc.)."""
    full = PROJECT_ROOT / filepath
    try:
        full = full.resolve()
        if not str(full).startswith(str(PROJECT_ROOT.resolve())):
            return "Forbidden", 403
    except Exception:
        return "Not found", 404
    if not full.exists() or not full.is_file():
        return "Not found", 404
    return send_file(str(full))


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


@app.route("/download/<path:filepath>")
def download_file(filepath):
    full = PROJECT_ROOT / filepath
    try:
        full = full.resolve()
        PROJECT_ROOT.resolve()
    except Exception:
        return "Not found", 404
    if not str(full).startswith(str(PROJECT_ROOT.resolve())):
        return "Forbidden", 403
    if not full.exists() or not full.is_file():
        return "Not found", 404
    return send_file(str(full), as_attachment=True, download_name=full.name)


@app.route("/nqueues/<int:nq_id>/export-json")
def export_nq_json(nq_id):
    with nq_lock:
        nq = next((q for q in named_queues if q["id"] == nq_id), None)
        if nq is None:
            return "Fila não encontrada", 404
        data = json.dumps(nq, indent=2, ensure_ascii=False).encode("utf-8")
        safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in nq["name"]).strip()
    buf = io.BytesIO(data)
    return send_file(buf, as_attachment=True, download_name=f"{safe}.json", mimetype="application/json")


@app.route("/nqueues/<int:nq_id>/download-zip")
def download_nq_zip(nq_id):
    include_sources = request.args.get("include_sources", "0") == "1"
    with nq_lock:
        nq = next((q for q in named_queues if q["id"] == nq_id), None)
        if nq is None:
            return "Fila não encontrada", 404
        jobs_snap = [dict(j) for j in nq["jobs"]]
        safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in nq["name"]).strip()
    buf = io.BytesIO()
    added = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for job in jobs_snap:
            if not job.get("output_video"):
                continue
            vp = PROJECT_ROOT / job["output_video"]
            if vp.exists() and str(vp) not in added:
                zf.write(str(vp), f"videos/{vp.name}")
                added.add(str(vp))
            if include_sources:
                for ref in job.get("ref_imgs") or []:
                    p = PROJECT_ROOT / ref
                    if p.exists() and str(p) not in added:
                        zf.write(str(p), f"sources/{p.name}")
                        added.add(str(p))
                for key in ("input_video", "input_image", "input_audio"):
                    val = job.get(key)
                    if val:
                        p = PROJECT_ROOT / val
                        if p.exists() and str(p) not in added:
                            zf.write(str(p), f"sources/{p.name}")
                            added.add(str(p))
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f"{safe}.zip", mimetype="application/zip")


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

def _estimate_job_minutes(job):
    """Estimated generation time in minutes for a single job."""
    t   = job.get("task_type", "")
    res = job.get("resolution", "720P")
    dur = job.get("duration", 5) or 5
    if t == "reference_to_video":
        base = {"480P": 8, "540P": 12, "720P": 18}.get(res, 14)
        return base + dur * 0.5
    if t == "talking_avatar":
        return {"480P": 15, "720P": 22}.get(res, 15)
    if t == "single_shot_extension":
        return 8 + dur * 0.4
    if t == "shot_switching_extension":
        return 5 + dur * 0.3
    return 10

@app.route("/nqueues", methods=["GET"])
def get_named_queues():
    with nq_lock:
        result = [{
            "id": nq["id"],
            "name": nq["name"],
            "project": nq.get("project", ""),
            "ep_code": nq.get("ep_code", ""),
            "status": nq["status"],
            "job_count": len(nq["jobs"]),
            "done_count": sum(1 for j in nq["jobs"] if j["status"] == "done"),
            "error_count": sum(1 for j in nq["jobs"] if j["status"] == "error"),
            "created_at": nq["created_at"],
            "estimated_minutes": round(sum(
                _estimate_job_minutes(j) for j in nq["jobs"]
            )),
            "remaining_minutes": round(sum(
                _estimate_job_minutes(j) for j in nq["jobs"]
                if j["status"] not in ("done",)
            )),
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

    proj = data.get("project", "")
    nq = {
        "id": nq_id,
        "name": name,
        "project": proj,
        "status": "idle",
        "jobs": jobs,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if proj:
        nq["ep_code"] = _next_ep_code(proj)
    with nq_lock:
        named_queues.append(nq)
    _save_queues()
    return jsonify({"ok": True, "id": nq_id, "ep_code": nq.get("ep_code", "")})


@app.route("/nqueues/import", methods=["POST"])
def import_nq_route():
    content = request.data.decode("utf-8").strip()
    name = request.args.get("name") or f"Fila {len(named_queues) + 1}"
    project = request.args.get("project", "")
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
            "project": project,
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


@app.route("/nqueues/<int:nq_id>/jobs", methods=["POST"])
def add_nq_job(nq_id):
    data = request.get_json(force=True)
    if not data.get("task_type"):
        return jsonify({"error": "task_type obrigatório"}), 400
    with nq_lock:
        nq = next((q for q in named_queues if q["id"] == nq_id), None)
        if nq is None:
            return jsonify({"error": "Fila não encontrada"}), 404
        job_id = _next_job_id()
        job = {
            "id": job_id,
            "nq_id": nq_id,
            "nq_job_index": len(nq["jobs"]),
            "status": "idle",
            "label": data.get("label") or f"{data['task_type']} — seed {data.get('seed', 42)}",
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "output_video": "",
            **{k: v for k, v in data.items() if k not in ("id", "nq_id", "status", "created_at", "output_video")},
        }
        nq["jobs"].append(job)
    _save_queues()
    return jsonify({"ok": True, "id": job_id})


@app.route("/nqueues/<int:nq_id>/jobs/<int:job_id>", methods=["DELETE"])
def delete_nq_job(nq_id, job_id):
    with nq_lock:
        nq = next((q for q in named_queues if q["id"] == nq_id), None)
        if nq is None:
            return jsonify({"error": "Fila não encontrada"}), 404
        job = next((j for j in nq["jobs"] if j["id"] == job_id), None)
        if job is None:
            return jsonify({"error": "Cena não encontrada"}), 404
        if job["status"] == "running":
            return jsonify({"error": "Cena em execução não pode ser removida"}), 400
        nq["jobs"] = [j for j in nq["jobs"] if j["id"] != job_id]
    _save_queues()
    return jsonify({"ok": True})


@app.route("/nqueues/<int:nq_id>/jobs/<int:job_id>", methods=["PATCH"])
def patch_nq_job(nq_id, job_id):
    data = request.get_json(force=True)
    PROTECTED = {"id", "nq_id", "nq_job_index", "status", "created_at",
                 "output_video", "started_at", "finished_at", "task_type"}
    with nq_lock:
        nq = next((q for q in named_queues if q["id"] == nq_id), None)
        if nq is None:
            return jsonify({"error": "Fila não encontrada"}), 404
        job = next((j for j in nq["jobs"] if j["id"] == job_id), None)
        if job is None:
            return jsonify({"error": "Cena não encontrada"}), 404
        if job["status"] == "running":
            return jsonify({"error": "Cena não pode ser editada enquanto está rodando"}), 400
        was_done = job["status"] == "done"
        for k, v in data.items():
            if k not in PROTECTED:
                job[k] = v
        # Campos de áudio/voz não invalidam o vídeo gerado — não resetar o job
        AUDIO_ONLY = {"audio_bg", "audio_text", "voice_id", "input_audio"}
        edits = set(k for k in data if k not in PROTECTED)
        audio_only_edit = bool(edits) and edits.issubset(AUDIO_ONLY)
        if was_done and not audio_only_edit:
            job["status"] = "idle"
            job["output_video"] = ""
            job["started_at"] = ""
            job["finished_at"] = ""
    _save_queues()
    return jsonify({"ok": True, "reset": was_done})


@app.route("/nqueues/<int:nq_id>", methods=["DELETE"])
def delete_named_queue_route(nq_id):
    force = request.args.get("force") == "true"
    with nq_lock:
        nq = next((q for q in named_queues if q["id"] == nq_id), None)
        if nq is None:
            return jsonify({"error": "Fila não encontrada"}), 404
        if nq["status"] == "running":
            return jsonify({"error": "Não é possível excluir uma fila em execução"}), 400
        if nq.get("project") and not force:
            # Episódio vinculado a projeto sem force: só limpa jobs e reseta status
            nq["jobs"] = []
            nq["status"] = "idle"
            nq["current_job"] = 0
        else:
            named_queues.remove(nq)
    _save_queues()
    return jsonify({"ok": True})


@app.route("/nqueues/<int:nq_id>/gallery")
def nq_gallery(nq_id):
    """Lista os assets gerados para o episódio: imagens, áudios e vídeos."""
    nq = next((q for q in named_queues if q["id"] == nq_id), None)
    if nq is None:
        return jsonify({"error": "Fila não encontrada"}), 404

    proj_name = nq.get("project", "")
    ep_code   = nq.get("ep_code", "")

    result: dict = {"images": [], "audios": [], "videos": [], "docs": []}

    if proj_name and ep_code:
        ep_dir = PROJECTS_DIR / proj_name / "episodios" / ep_code
        for f in sorted((ep_dir / "imagens").glob("*")) if (ep_dir / "imagens").exists() else []:
            if f.is_file():
                result["images"].append(str(f.relative_to(PROJECT_ROOT)))
        for f in sorted((ep_dir / "audios").glob("*")) if (ep_dir / "audios").exists() else []:
            if f.is_file():
                result["audios"].append(str(f.relative_to(PROJECT_ROOT)))

    # Vídeos gerados (output_video de cada job)
    for j in nq.get("jobs", []):
        vid = j.get("output_video", "")
        if vid and (PROJECT_ROOT / vid).exists():
            result["videos"].append(vid)

    return jsonify(result)


@app.route("/nqueues/<int:nq_id>/project-link", methods=["DELETE"])
def unlink_nq_from_project(nq_id):
    """Remove a associação do episódio com o projeto sem excluir a fila."""
    with nq_lock:
        nq = next((q for q in named_queues if q["id"] == nq_id), None)
        if nq is None:
            return jsonify({"error": "Fila não encontrada"}), 404
        if nq["status"] == "running":
            return jsonify({"error": "Não é possível desvincular uma fila em execução"}), 400
        nq.pop("project", None)
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
    """Repetir do erro: reset error+idle jobs (keep done), run from first error."""
    with nq_lock:
        nq = next((q for q in named_queues if q["id"] == nq_id), None)
        if nq is None:
            return jsonify({"error": "Fila não encontrada"}), 404
        if nq["status"] == "running":
            return jsonify({"error": "Não é possível operar uma fila em execução"}), 400
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


@app.route("/nqueues/<int:nq_id>/restart", methods=["POST"])
def restart_nq_route(nq_id):
    """Reiniciar do zero: reset ALL jobs (including done), run from beginning."""
    with nq_lock:
        nq = next((q for q in named_queues if q["id"] == nq_id), None)
        if nq is None:
            return jsonify({"error": "Fila não encontrada"}), 404
        if nq["status"] == "running":
            return jsonify({"error": "Não é possível operar uma fila em execução"}), 400
        for j in nq["jobs"]:
            j["status"] = "idle"
            j["output_video"] = ""
            j.pop("started_at", None)
            j.pop("finished_at", None)
    _save_queues()
    ok = run_named_queue(nq_id)
    if not ok:
        return jsonify({"error": "Sem cenas a executar"}), 400
    return jsonify({"ok": True})


def _audio_duration(path: Path) -> float:
    """Returns audio duration in seconds using ffprobe."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
            capture_output=True, text=True, timeout=10
        )
        data = json.loads(r.stdout) if r.returncode == 0 else {}
        return float(data.get("format", {}).get("duration", 0))
    except Exception:
        return 0.0


def _video_info(path):
    """Returns (has_audio, duration_seconds) for a video file."""
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_streams", "-show_format", str(path)],
        capture_output=True, text=True, timeout=15
    )
    data = json.loads(r.stdout) if r.returncode == 0 else {}
    has_aud = any(s.get("codec_type") == "audio" for s in data.get("streams", []))
    duration = float(data.get("format", {}).get("duration", 0))
    return has_aud, duration


def _mix_audio_scene(video_path: Path, speech_path: Path = None,
                     bg_path: Path = None, bg_volume: float = 0.28) -> bool:
    """Mixes speech and/or background audio into a video, replacing it in-place.
    - speech_path: narração/diálogo (volume 100%)
    - bg_path: trilha de fundo (volume bg_volume, padrão 28%)
    - Usa -map 0:v para sempre descartar o áudio existente no vídeo.
    """
    if not speech_path and not bg_path:
        return False
    tmp = video_path.with_name(video_path.stem + "_mixed_tmp.mp4")
    try:
        cmd = ["ffmpeg", "-y", "-i", str(video_path)]
        if speech_path:
            cmd += ["-i", str(speech_path)]
        if bg_path:
            cmd += ["-i", str(bg_path)]

        if speech_path and bg_path:
            si, bi = 1, 2
            fc = (
                f"[{si}:a]aresample=44100,volume=1.0[speech];"
                f"[{bi}:a]aresample=44100,volume={bg_volume}[bg];"
                f"[speech][bg]amix=inputs=2:dropout_transition=0[a]"
            )
            cmd += ["-filter_complex", fc,
                    "-map", "0:v", "-map", "[a]",
                    "-c:v", "copy", "-c:a", "aac", "-ar", "44100", "-ac", "2",
                    "-shortest", str(tmp)]
        elif speech_path:
            cmd += ["-map", "0:v", "-map", "1:a",
                    "-c:v", "copy", "-c:a", "aac", "-ar", "44100", "-ac", "2",
                    "-shortest", str(tmp)]
        else:  # bg only
            fc = f"[1:a]aresample=44100,volume={bg_volume}[a]"
            cmd += ["-filter_complex", fc,
                    "-map", "0:v", "-map", "[a]",
                    "-c:v", "copy", "-c:a", "aac", "-ar", "44100", "-ac", "2",
                    "-shortest", str(tmp)]

        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode == 0 and tmp.exists():
            tmp.replace(video_path)
            return True
        if tmp.exists():
            tmp.unlink()
        return False
    except Exception:
        if tmp.exists():
            tmp.unlink()
        return False


# Backwards-compat alias
def _mix_audio_into_video(video_path: Path, audio_path: Path) -> bool:
    return _mix_audio_scene(video_path, speech_path=audio_path)


@app.route("/nqueues/<int:nq_id>/finalize", methods=["POST"])
def finalize_nq_route(nq_id):
    with nq_lock:
        nq = next((q for q in named_queues if q["id"] == nq_id), None)
        if nq is None:
            return jsonify({"error": "Fila não encontrada"}), 404
        videos = [
            PROJECT_ROOT / j["output_video"]
            for j in nq["jobs"]
            if j.get("status") == "done" and j.get("output_video")
        ]
        nq_name = nq["name"]

    if not videos:
        return jsonify({"error": "Nenhuma cena concluída para finalizar"}), 400

    missing = [str(v) for v in videos if not v.exists()]
    if missing:
        return jsonify({"error": f"Arquivo(s) não encontrado(s): {', '.join(missing)}"}), 400

    out_dir = PROJECT_ROOT / "result" / "finalized"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%d_%H-%M-%S")
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in nq_name)
    out_path = out_dir / f"{safe_name}_{ts}.mp4"

    # Check audio presence per video
    infos = [_video_info(v) for v in videos]
    any_audio = any(has_aud for has_aud, _ in infos)

    import tempfile

    if not any_audio:
        # All silent — simple concat copy
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            for v in videos:
                f.write(f"file '{v}'\n")
            list_path = f.name
        try:
            result = subprocess.run(
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                 "-i", list_path, "-c", "copy", str(out_path)],
                capture_output=True, text=True, timeout=600)
        finally:
            os.unlink(list_path)
    else:
        # Mixed audio/silent — filter_complex to normalize all streams then concat
        cmd = ["ffmpeg", "-y"]
        for v in videos:
            cmd.extend(["-i", str(v)])

        # Determine target resolution (most common among done videos)
        from collections import Counter
        res_list = []
        for v in videos:
            r = subprocess.run(
                ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height", "-of", "csv=p=0", str(v)],
                capture_output=True, text=True, timeout=10)
            res_list.append(r.stdout.strip())
        target_res = Counter(res_list).most_common(1)[0][0]
        tw, th = target_res.split(",")

        filter_parts = []
        concat_inputs = ""
        for i, (has_aud, dur) in enumerate(infos):
            filter_parts.append(
                f"[{i}:v]scale={tw}:{th}:force_original_aspect_ratio=decrease,"
                f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:black,"
                f"setpts=PTS-STARTPTS[v{i}]"
            )
            if has_aud:
                filter_parts.append(
                    f"[{i}:a]aresample=44100,aformat=channel_layouts=stereo,"
                    f"asetpts=PTS-STARTPTS[a{i}]"
                )
            else:
                filter_parts.append(
                    f"anullsrc=r=44100:cl=stereo,atrim=duration={dur:.3f},"
                    f"asetpts=PTS-STARTPTS[a{i}]"
                )
            concat_inputs += f"[v{i}][a{i}]"

        n = len(videos)
        filter_parts.append(f"{concat_inputs}concat=n={n}:v=1:a=1[v][a]")
        cmd += [
            "-filter_complex", ";".join(filter_parts),
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "128k",
            str(out_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    if result.returncode != 0:
        return jsonify({"error": f"ffmpeg falhou: {result.stderr[-500:]}"}), 500

    rel_path = str(out_path.relative_to(PROJECT_ROOT))
    return jsonify({"ok": True, "output_video": rel_path, "scene_count": len(videos)})


@app.route("/nqueues/<int:nq_id>/mix-audio", methods=["POST"])
def nq_mix_audio(nq_id):
    """Mixes input_audio and/or audio_bg into done scene videos.
    - Skips jobs with no audio sources.
    - Always re-mixes if audio_bg is set (discards existing audio track via -map 0:v).
    - Skips jobs whose video already has audio when only input_audio is set (no bg change).
    """
    with nq_lock:
        nq = next((q for q in named_queues if q["id"] == nq_id), None)
        if nq is None:
            return jsonify({"error": "Fila não encontrada"}), 404
        jobs = nq["jobs"]

    mixed, skipped, errors = 0, 0, []
    for job in jobs:
        if job.get("status") != "done" or job.get("task_type") == "talking_avatar":
            skipped += 1
            continue
        output_video = job.get("output_video", "")
        sp_str = job.get("input_audio", "")
        bg_str = job.get("audio_bg", "")
        if not output_video or (not sp_str and not bg_str):
            skipped += 1
            continue
        vpath = PROJECT_ROOT / output_video
        if not vpath.exists():
            errors.append(f"{job.get('label','?')}: vídeo não encontrado")
            continue
        sp = (PROJECT_ROOT / sp_str) if sp_str else None
        bg = (PROJECT_ROOT / bg_str) if bg_str else None
        sp = sp if (sp and sp.exists()) else None
        bg = bg if (bg and bg.exists()) else None
        if not sp and not bg:
            errors.append(f"{job.get('label','?')}: arquivo(s) de áudio não encontrado(s)")
            continue
        # Se só tem speech e o vídeo já tem áudio: pula (já mixado)
        # Se tem audio_bg: sempre re-mixa (pode ter mudado a trilha)
        if not bg:
            has_aud, _ = _video_info(vpath)
            if has_aud:
                skipped += 1
                continue
        ok = _mix_audio_scene(vpath, speech_path=sp, bg_path=bg)
        if ok:
            mixed += 1
        else:
            errors.append(f"{job.get('label','?')}: ffmpeg falhou")

    return jsonify({"ok": True, "mixed": mixed, "skipped": skipped, "errors": errors})


@app.route("/nqueues/<int:nq_id>/set-audio-bg", methods=["POST"])
def nq_set_audio_bg(nq_id):
    """Define audio_bg em todos os jobs da fila (ou limpa se audio_bg vazio)."""
    data = request.get_json(force=True)
    audio_bg = data.get("audio_bg", "").strip()
    with nq_lock:
        nq = next((q for q in named_queues if q["id"] == nq_id), None)
        if nq is None:
            return jsonify({"error": "Fila não encontrada"}), 404
        updated = 0
        for job in nq["jobs"]:
            job["audio_bg"] = audio_bg
            updated += 1
    _save_queues()
    return jsonify({"ok": True, "updated": updated, "audio_bg": audio_bg})


# ─── Config global ───────────────────────────────────────────

@app.route("/config", methods=["GET"])
def get_global_config():
    return jsonify(_load_global_config())


@app.route("/config", methods=["POST"])
def save_global_config():
    data = request.get_json(force=True)
    GLOBAL_CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return jsonify({"ok": True})


# ─── Projetos ────────────────────────────────────────────────

@app.route("/projects", methods=["GET"])
def list_projects():
    projs = []
    if PROJECTS_DIR.exists():
        for d in sorted(PROJECTS_DIR.iterdir()):
            if d.is_dir():
                projs.append({"name": d.name, "path": str(d.relative_to(PROJECT_ROOT))})
    return jsonify(projs)


@app.route("/projects", methods=["POST"])
def create_project():
    data = request.get_json(force=True)
    name = re.sub(r'[^a-zA-Z0-9_\- ]', '', data.get("name", "")).strip()
    if not name:
        return jsonify({"error": "Nome inválido"}), 400
    proj_dir = PROJECTS_DIR / name
    if proj_dir.exists():
        return jsonify({"error": "Projeto já existe"}), 409
    for sub in ("imagens", "audios", "docs", "episodios", "temp"):
        (proj_dir / sub).mkdir(parents=True, exist_ok=True)
    return jsonify({"ok": True, "name": name})


@app.route("/projects/<name>", methods=["GET"])
def get_project(name):
    proj_dir = PROJECTS_DIR / name
    if not proj_dir.exists():
        return jsonify({"error": "Projeto não encontrado"}), 404
    folders = {}
    for sub in ("imagens", "audios", "docs", "episodios", "temp"):
        sub_dir = proj_dir / sub
        sub_dir.mkdir(exist_ok=True)
        files = []
        for f in sorted(sub_dir.iterdir()):
            if f.is_file():
                files.append({
                    "name": f.name,
                    "size": f.stat().st_size,
                    "path": str(f.relative_to(PROJECT_ROOT))
                })
        folders[sub] = files
    with nq_lock:
        episodes = [
            {
                "id":       q["id"],
                "name":     q["name"],
                "ep_code":  q.get("ep_code", ""),
                "total":    len(q.get("jobs", [])),
                "done":     sum(1 for j in q.get("jobs", []) if j["status"] == "done"),
                "running":  any(j["status"] == "running" for j in q.get("jobs", [])),
                "error":    any(j["status"] == "error" for j in q.get("jobs", [])),
                "status":   q.get("status", "idle"),
            }
            for q in named_queues
            if q.get("project") == name
        ]
    return jsonify({"name": name, "folders": folders, "episodes": episodes})


@app.route("/projects/<name>/voices")
def get_project_voices(name):
    """Retorna o mapa personagem → voice_id extraído dos docs do projeto."""
    voices = _parse_project_voices(name)
    return jsonify({"project": name, "voices": voices})


@app.route("/projects/<name>/upload/<subfolder>", methods=["POST"])
def upload_project_file(name, subfolder):
    if subfolder not in ("imagens", "audios", "docs", "episodios", "temp"):
        return jsonify({"error": "Pasta inválida"}), 400
    proj_dir = PROJECTS_DIR / name / subfolder
    proj_dir.mkdir(parents=True, exist_ok=True)
    if not (PROJECTS_DIR / name).exists():
        return jsonify({"error": "Projeto não encontrado"}), 404
    uploaded = []
    for file in request.files.getlist("files"):
        fname = secure_filename(file.filename)
        if not fname:
            continue
        file.save(str(proj_dir / fname))
        uploaded.append(fname)
    return jsonify({"ok": True, "uploaded": uploaded})


@app.route("/projects/<name>/files/<subfolder>/<filename>", methods=["DELETE"])
def delete_project_file(name, subfolder, filename):
    if subfolder not in ("imagens", "audios", "docs", "episodios", "temp"):
        return jsonify({"error": "Pasta inválida"}), 400
    fpath = PROJECTS_DIR / name / subfolder / filename
    if not fpath.exists():
        return jsonify({"error": "Arquivo não encontrado"}), 404
    fpath.unlink()
    return jsonify({"ok": True})


@app.route("/projects/<name>", methods=["DELETE"])
def delete_project(name):
    import shutil
    proj_dir = PROJECTS_DIR / name
    if not proj_dir.exists():
        return jsonify({"error": "Projeto não encontrado"}), 404
    shutil.rmtree(str(proj_dir))
    return jsonify({"ok": True})


@app.route("/projects/<name>/config", methods=["GET"])
def get_project_config(name):
    cfg_file = PROJECTS_DIR / name / "config.json"
    if cfg_file.exists():
        return jsonify(json.loads(cfg_file.read_text()))
    return jsonify({})


@app.route("/projects/<name>/config", methods=["POST"])
def save_project_config(name):
    proj_dir = PROJECTS_DIR / name
    if not proj_dir.exists():
        return jsonify({"error": "Projeto não encontrado"}), 404
    data = request.get_json(force=True)
    (proj_dir / "config.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return jsonify({"ok": True})


@app.route("/system-prompt/episode", methods=["GET"])
def get_system_prompt():
    return jsonify({"prompt": _load_system_prompt(), "default": DEFAULT_SYSTEM_PROMPT})


@app.route("/system-prompt/episode", methods=["POST"])
def save_system_prompt():
    data = request.get_json(force=True)
    text = data.get("prompt", "").strip()
    if not text:
        return jsonify({"error": "Prompt não pode ser vazio"}), 400
    SYSTEM_PROMPT_FILE.write_text(text, encoding="utf-8")
    return jsonify({"ok": True})


@app.route("/system-prompt/episode/reset", methods=["POST"])
def reset_system_prompt():
    if SYSTEM_PROMPT_FILE.exists():
        SYSTEM_PROMPT_FILE.unlink()
    return jsonify({"ok": True, "prompt": DEFAULT_SYSTEM_PROMPT})


def _build_phase1_prompt(description: str, image_paths: list, docs_content: list) -> str:
    """Prompt para Fase 1: Claude identifica ambientes e elementos novos necessários."""
    images_list = "\n".join(f"- {p}" for p in image_paths) if image_paths else "Nenhuma"
    docs_str = ("\n\nDocumentos do projeto:\n" + "\n\n".join(docs_content)[:3000]) if docs_content else ""
    return f"""Você é um supervisor de produção de série animada.
A partir da descrição do episódio e dos recursos visuais do projeto, faça:

1. MAPEAMENTO DE AMBIENTES: Identifique todos os locais/ambientes onde as cenas acontecem
2. ELEMENTOS NOVOS: Identifique elementos visuais que NÃO têm imagem de referência disponível na lista abaixo

Imagens de referência disponíveis no projeto:
{images_list}{docs_str}

Descrição do episódio:
{description}

Retorne SOMENTE um JSON válido com este formato exato:
{{
  "environments": [
    {{
      "name": "nome curto do ambiente",
      "description": "descrição visual detalhada do ambiente",
      "existing_ref": "projetos/X/imagens/Y.png ou null se não existe"
    }}
  ],
  "new_elements": [
    {{
      "name": "nome do elemento",
      "type": "environment|character|object",
      "image_prompt": "prompt detalhado em inglês para gerar imagem via fal.ai (anime style, 16:9, 2030 futuristic)"
    }}
  ]
}}

REGRAS OBRIGATÓRIAS:
- environments.existing_ref: use o path EXATO de uma imagem da lista acima (copie exatamente como está), ou null
- new_elements: SOMENTE elementos que NÃO têm nenhuma imagem correspondente na lista acima
- Máximo 5 novos elementos — priorize ambientes e personagens novos mais importantes
- Se todos os ambientes já têm referência visual: new_elements = []

APENAS o JSON."""


@app.route("/projects/<name>/generate-episode", methods=["POST"])
def generate_episode_prompts(name):
    data = request.get_json(force=True)
    description = data.get("description", "") or data.get("concept", "")
    doc_title   = data.get("doc_title", "").strip()
    task_type   = data.get("task_type", "reference_to_video")
    resolution  = data.get("resolution", "720P")
    duration    = int(data.get("duration", 5))
    ref_imgs    = data.get("ref_imgs", [])

    # Salvar descrição em docs/ antes de gerar
    saved_doc = None
    doc_path  = None
    proj_dir  = PROJECTS_DIR / name
    if proj_dir.exists() and description:
        docs_dir = proj_dir / "docs"
        docs_dir.mkdir(exist_ok=True)
        safe_title = re.sub(r'[^\w\-_ ]', '', doc_title or "descricao_episodio").strip() or "descricao_episodio"
        doc_path = docs_dir / f"{safe_title}.md"
        doc_path.write_text(description, encoding="utf-8")
        saved_doc = str(doc_path.relative_to(PROJECT_ROOT))

    # Coletar TODOS os recursos para contexto de consistência
    all_images, all_audios, all_docs_content = [], [], []

    # Imagens: pasta do projeto
    img_proj_dir = proj_dir / "imagens"
    if img_proj_dir.exists():
        for f in sorted(img_proj_dir.iterdir()):
            if f.is_file():
                all_images.append(str(f.relative_to(PROJECT_ROOT)))

    if proj_dir.exists():
        for f in sorted((proj_dir / "audios").iterdir()) if (proj_dir / "audios").exists() else []:
            if f.is_file():
                all_audios.append(f.name)
        for f in sorted((proj_dir / "docs").iterdir()) if (proj_dir / "docs").exists() else []:
            if f.is_file() and f.suffix in (".md", ".txt") and f != doc_path:
                try:
                    all_docs_content.append(f"--- {f.name} ---\n{f.read_text(encoding='utf-8', errors='ignore')[:2000]}")
                except Exception:
                    pass

    # Usar ref_imgs selecionadas (vêm de uploads/) ou todas as imagens de uploads/
    effective_imgs = ref_imgs if ref_imgs else all_images
    images_list = "\n".join(f"- {p}" for p in effective_imgs) if effective_imgs else "Nenhuma"

    resources_section = f"\nImagens de referência do projeto (use os paths exatos nas cenas):\n{images_list}\n"
    if all_audios:
        resources_section += f"\nÁudios disponíveis no projeto:\n" + "\n".join(f"- {a}" for a in all_audios) + "\n"
    if all_docs_content:
        resources_section += f"\nDocumentos do projeto (contexto de consistência):\n" + "\n\n".join(all_docs_content) + "\n"

    json_template = (
        f'{{\n'
        f'  "label": "Cena 01 — Título curto",\n'
        f'  "task_type": "{task_type}",\n'
        f'  "prompt": "Cinematic video description in English — camera movement, lighting, characters, action...",\n'
        f'  "image_prompt": "Flux/fal.ai image prompt in English — characters, environment, art style, colors...",\n'
        f'  "audio_text": "Narração ou diálogos em português para esta cena (ou string vazia se silenciosa)",\n'
        f'  "voice_id": "ElevenLabs voice_id do personagem que fala nesta cena (extraia dos docs do projeto; vazio se narração genérica)",\n'
        f'  "audio_bg": "path para trilha de fundo do projeto (projetos/<nome>/audios/<arquivo>.mp3) ou string vazia",\n'
        f'  "resolution": "{resolution}",\n'
        f'  "duration": <duração em segundos mais adequada para esta cena>,\n'
        f'  "seed": <número entre 1000 e 9999>,\n'
        f'  "offload": false,\n'
        f'  "low_vram": false,\n'
        f'  "ref_imgs": ["uploads/personagem1.jpg", "uploads/ambiente.png"]  // MÁXIMO 4 — use 2-3 idealmente\n'
        f'}}'
    )

    # Fase 2 usará json_template e template do sistema; construímos fora para capturar no closure
    _sys_template = _load_system_prompt()

    # Iniciar geração em background — retorna job_id imediatamente
    job_id = uuid.uuid4().hex[:8]
    with _ep_gen_lock:
        _ep_gen_state[job_id] = {
            "status": "running",
            "phase": "phase1",
            "phase_msg": "Fase 1: identificando ambientes e elementos visuais…",
            "jobs": [],
            "saved_doc": saved_doc,
            "ep_title": doc_title,
            "error": None,
            "raw": "",
            "environments": [],
            "new_refs": [],
        }
        _ep_gen_by_project[name] = job_id

    def _run():
        _env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        proc = None
        try:
            # ─── FASE 1: identificar ambientes e elementos novos ───────────────
            with _ep_gen_lock:
                _ep_gen_state[job_id]["phase"]     = "phase1"
                _ep_gen_state[job_id]["phase_msg"] = "Fase 1: identificando ambientes e elementos visuais…"

            phase1_prompt = _build_phase1_prompt(description, effective_imgs, all_docs_content)
            proc = subprocess.run(
                ["/home/nmaldaner/.local/bin/claude", "-p", phase1_prompt],
                capture_output=True, text=True, timeout=180, env=_env
            )
            raw1 = proc.stdout.strip()
            if raw1.startswith("```"):
                raw1 = re.sub(r"^```[a-z]*\n?", "", raw1)
                raw1 = re.sub(r"\n?```$", "", raw1)

            phase1_result = json.loads(raw1)
            environments = phase1_result.get("environments", [])
            new_elements = phase1_result.get("new_elements", [])
            with _ep_gen_lock:
                _ep_gen_state[job_id]["environments"] = environments

            # ─── FASE 1b: gerar imagens para elementos novos ──────────────────
            new_refs = []
            if new_elements:
                with _ep_gen_lock:
                    _ep_gen_state[job_id]["phase"]     = "generating_refs"
                    _ep_gen_state[job_id]["phase_msg"] = f"Gerando {len(new_elements)} imagem(ns) de referência nova(s)…"

                cfg = _load_global_config()
                fal_key = cfg.get("fal_key", "") or os.environ.get("FAL_KEY", "")
                if fal_key:
                    try:
                        import fal_client
                        import urllib.request as urllib_req
                        os.environ["FAL_KEY"] = fal_key
                        model = cfg.get("image_model", "fal-ai/flux/dev")
                        img_dir = PROJECTS_DIR / name / "imagens"
                        img_dir.mkdir(exist_ok=True)

                        for idx_e, elem in enumerate(new_elements):
                            with _ep_gen_lock:
                                _ep_gen_state[job_id]["phase_msg"] = (
                                    f"Gerando referência {idx_e + 1}/{len(new_elements)}: "
                                    f"{elem.get('name', '')}…"
                                )
                            try:
                                img_prompt = elem.get("image_prompt") or elem.get("name", "")
                                res = fal_client.subscribe(model, arguments={
                                    "prompt": img_prompt,
                                    "num_images": 1,
                                    "image_size": "landscape_16_9",
                                })
                                url = res["images"][0]["url"]
                                safe_n = re.sub(r'[^\w\-]', '_', elem.get("name", "element")[:40])
                                dest = img_dir / f"{safe_n}.png"
                                urllib_req.urlretrieve(url, str(dest))
                                rel = str(dest.relative_to(PROJECT_ROOT))
                                new_refs.append({
                                    "name": elem.get("name"),
                                    "type": elem.get("type", ""),
                                    "path": rel,
                                })
                                print(f"[ep-gen] nova ref gerada: {rel}")
                            except Exception as img_err:
                                print(f"[ep-gen] erro ao gerar imagem para '{elem.get('name')}': {img_err}")
                    except ImportError:
                        print("[ep-gen] fal-client não instalado — pulando geração de novas refs")

            with _ep_gen_lock:
                _ep_gen_state[job_id]["new_refs"] = new_refs

            # ─── FASE 2: gerar cenas com referências completas ────────────────
            with _ep_gen_lock:
                _ep_gen_state[job_id]["phase"]     = "phase2"
                _ep_gen_state[job_id]["phase_msg"] = "Fase 2: criando cenas com referências completas…"

            # Lista atualizada: refs originais + novas geradas
            all_refs = list(effective_imgs) + [nr["path"] for nr in new_refs]
            updated_images_list = "\n".join(f"- {p}" for p in all_refs) if all_refs else "Nenhuma"

            # Mapa de ambientes para orientar a IA na fase 2
            env_section = ""
            if environments:
                env_section = (
                    "\n\nMAPA DE AMBIENTES DO EPISÓDIO"
                    " — distribua CONSISTENTEMENTE por cena:\n"
                )
                for env in environments:
                    ref = env.get("existing_ref")
                    # Substituir/completar com nova ref gerada se houver
                    for nr in new_refs:
                        if nr["name"].lower() == env["name"].lower():
                            ref = nr["path"]
                            break
                    env_section += f"- {env['name']}: {env.get('description', '')}\n"
                    if ref:
                        env_section += (
                            f"  → REFERÊNCIA OBRIGATÓRIA: {ref}"
                            f" (inclua em TODA cena que ocorre neste ambiente)\n"
                        )

            resources_section_updated = (
                f"\nImagens de referência do projeto (use os paths exatos nas cenas):\n"
                f"{updated_images_list}\n"
            )
            if all_audios:
                resources_section_updated += (
                    "\nÁudios disponíveis no projeto:\n"
                    + "\n".join(f"- {a}" for a in all_audios) + "\n"
                )
            if all_docs_content:
                resources_section_updated += (
                    "\nDocumentos do projeto (contexto de consistência):\n"
                    + "\n\n".join(all_docs_content) + "\n"
                )
            if env_section:
                resources_section_updated += env_section

            phase2_prompt = _sys_template.format(
                description=description,
                resources=resources_section_updated,
                task_type=task_type,
                resolution=resolution,
                duration=duration,
                json_template=json_template,
            )

            proc = subprocess.run(
                ["/home/nmaldaner/.local/bin/claude", "-p", phase2_prompt],
                capture_output=True, text=True, timeout=360, env=_env
            )
            raw2 = proc.stdout.strip()
            if raw2.startswith("```"):
                raw2 = re.sub(r"^```[a-z]*\n?", "", raw2)
                raw2 = re.sub(r"\n?```$", "", raw2)
            jobs = json.loads(raw2)
            if not isinstance(jobs, list):
                raise ValueError("Resposta não é um array")

            with _ep_gen_lock:
                if job_id in _ep_gen_state:
                    done_msg = f"Concluído! {len(jobs)} cenas"
                    if new_refs:
                        done_msg += f" · {len(new_refs)} nova(s) referência(s) criada(s)"
                    _ep_gen_state[job_id]["status"]   = "done"
                    _ep_gen_state[job_id]["phase"]     = "done"
                    _ep_gen_state[job_id]["phase_msg"] = done_msg
                    _ep_gen_state[job_id]["jobs"]      = jobs

        except Exception as e:
            with _ep_gen_lock:
                if job_id in _ep_gen_state:
                    _ep_gen_state[job_id]["status"] = "error"
                    _ep_gen_state[job_id]["error"]  = str(e)
                    _ep_gen_state[job_id]["raw"]    = proc.stdout[:500] if proc else ""

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"job_id": job_id, "saved_doc": saved_doc})


@app.route("/projects/<name>/generate-episode-status/<job_id>")
def generate_episode_status(name, job_id):
    with _ep_gen_lock:
        state = dict(_ep_gen_state.get(job_id, {}))
    if not state:
        return jsonify({"error": "não encontrado"}), 404
    return jsonify(state)


@app.route("/projects/<name>/regenerate-scene", methods=["POST"])
def regenerate_scene_prompt(name):
    """Re-gera o prompt de uma cena específica via Claude CLI."""
    data       = request.get_json(force=True)
    label      = data.get("label", "")
    resolution = data.get("resolution", "720P")
    duration   = int(data.get("duration", 5))
    ref_imgs   = data.get("ref_imgs", [])

    images_list = "\n".join(f"- {p}" for p in ref_imgs) if ref_imgs else "Nenhuma"
    json_template = (
        f'{{\n'
        f'  "label": "{label}",\n'
        f'  "task_type": "reference_to_video",\n'
        f'  "prompt": "Descrição cinemática detalhada em inglês para geração de vídeo por IA...",\n'
        f'  "resolution": "{resolution}",\n'
        f'  "duration": {duration},\n'
        f'  "seed": <número entre 1000 e 9999>,\n'
        f'  "offload": false,\n'
        f'  "low_vram": false,\n'
        f'  "ref_imgs": [<inclua paths relevantes da lista acima, ou [] se não houver>]\n'
        f'}}'
    )
    prompt = f"""Você é um assistente de produção de vídeo. Gere um prompt detalhado para esta cena de vídeo IA (SkyReels).

Cena: {label}
Imagens de referência disponíveis (use os paths exatos):
{images_list}
Resolução: {resolution}
Duração sugerida: ~{duration}s

Retorne SOMENTE um objeto JSON válido (não um array), começando com {{ e terminando com }}:
{json_template}

APENAS o JSON, nada mais."""

    _env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    result = None
    try:
        result = subprocess.run(
            ["/home/nmaldaner/.local/bin/claude", "-p", prompt],
            capture_output=True, text=True, timeout=60, env=_env
        )
        raw = result.stdout.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        job = json.loads(raw)
        if isinstance(job, list):
            job = job[0]
        return jsonify({"ok": True, "job": job})
    except Exception as e:
        return jsonify({
            "error": str(e),
            "raw": result.stdout[:500] if result else ""
        }), 500


@app.route("/projects/<name>/generate-images", methods=["POST"])
def generate_episode_images(name):
    import urllib.request as urllib_req
    try:
        import fal_client
    except ImportError:
        return jsonify({"error": "fal-client não instalado. Execute: pip install fal-client"}), 500

    cfg = _load_global_config()
    fal_key = cfg.get("fal_key", "") or os.environ.get("FAL_KEY", "")
    if not fal_key:
        return jsonify({"error": "FAL_KEY não configurada. Clique em ⚙ na aba Projetos."}), 400

    os.environ["FAL_KEY"] = fal_key
    data    = request.get_json(force=True)
    jobs    = data.get("jobs", [])
    model   = cfg.get("image_model", "fal-ai/flux/dev")
    img_dir = PROJECTS_DIR / name / "imagens"
    img_dir.mkdir(exist_ok=True)

    updated = []
    for job in jobs:
        img_prompt = job.get("image_prompt") or job.get("prompt", "")[:400]
        try:
            res = fal_client.subscribe(model, arguments={
                "prompt": img_prompt,
                "num_images": 1,
                "image_size": "landscape_16_9"
            })
            url = res["images"][0]["url"]
            fname = secure_filename(f"{job.get('label','scene')[:40]}.jpg").replace(" ", "_")
            dest  = img_dir / fname
            urllib_req.urlretrieve(url, str(dest))
            rel   = str(dest.relative_to(PROJECT_ROOT))
            job   = {**job, "ref_imgs": [rel]}
        except Exception as e:
            job = {**job, "_img_error": str(e)}
        updated.append(job)

    return jsonify({"ok": True, "jobs": updated})


@app.route("/projects/<name>/generate-audio", methods=["POST"])
def generate_episode_audio(name):
    try:
        from elevenlabs.client import ElevenLabs as EL
    except ImportError:
        return jsonify({"error": "elevenlabs não instalado. Execute: pip install elevenlabs"}), 500

    cfg    = _load_global_config()
    el_key = cfg.get("elevenlabs_key", "") or os.environ.get("ELEVENLABS_API_KEY", "")
    voice  = cfg.get("elevenlabs_voice_id", "")
    if not el_key or not voice:
        return jsonify({"error": "ElevenLabs não configurado. Clique em ⚙ na aba Projetos."}), 400

    data    = request.get_json(force=True)
    jobs    = data.get("jobs", [])
    aud_dir = PROJECTS_DIR / name / "audios"
    aud_dir.mkdir(exist_ok=True)
    client  = EL(api_key=el_key)

    updated = []
    for job in jobs:
        text = job.get("audio_text") or ""
        if not text:
            updated.append(job)
            continue
        try:
            audio_bytes = b"".join(client.text_to_speech.convert(
                text=text, voice_id=voice,
                model_id="eleven_multilingual_v2",
                output_format="mp3_44100_128"
            ))
            fname = secure_filename(f"{job.get('label','scene')[:40]}.mp3").replace(" ", "_")
            dest  = aud_dir / fname
            dest.write_bytes(audio_bytes)
            rel   = str(dest.relative_to(PROJECT_ROOT))
            import math
            aud_dur = _audio_duration(dest)
            new_job = {**job, "input_audio": rel}
            if aud_dur > 0:
                min_dur = math.ceil(aud_dur) + 1
                if new_job.get("duration", 0) < min_dur:
                    new_job["duration"] = min_dur
            job = new_job
        except Exception as e:
            job = {**job, "_audio_error": str(e)}
        updated.append(job)

    return jsonify({"ok": True, "jobs": updated})


def _nq_get_project(nq_id):
    """Retorna (nq, proj_name) ou (None, None)."""
    with nq_lock:
        nq = next((q for q in named_queues if q["id"] == nq_id), None)
    if nq is None:
        return None, None
    return nq, nq.get("project", "")


@app.route("/nqueues/<int:nq_id>/generate-images", methods=["POST"])
def nq_generate_images(nq_id):
    import urllib.request as urllib_req
    nq, proj_name = _nq_get_project(nq_id)
    if nq is None:
        return jsonify({"error": "Fila não encontrada"}), 404
    if not proj_name:
        return jsonify({"error": "Episódio não vinculado a um projeto"}), 400
    try:
        import fal_client
    except ImportError:
        return jsonify({"error": "fal-client não instalado"}), 500

    cfg = _load_global_config()
    fal_key = cfg.get("fal_key", "") or os.environ.get("FAL_KEY", "")
    if not fal_key:
        return jsonify({"error": "FAL_KEY não configurada. Clique em ⚙ na aba Projetos."}), 400

    os.environ["FAL_KEY"] = fal_key
    model = cfg.get("image_model", "fal-ai/flux/dev")
    # Imagens do episódio ficam em projetos/<proj>/temp/<ep-name>/imagens/
    ep_slug = nq.get("ep_code") or re.sub(r'[^\w\-]', '_', nq.get("name", f"ep_{nq_id}"))[:60]
    img_dir = PROJECTS_DIR / proj_name / "episodios" / ep_slug / "imagens"
    img_dir.mkdir(parents=True, exist_ok=True)

    with nq_lock:
        jobs = list(nq.get("jobs", []))

    errors = []
    for i, job in enumerate(jobs):
        if job.get("status") == "done":
            continue
        img_prompt = job.get("image_prompt") or job.get("prompt", "")[:400]
        ref_paths  = [r for r in (job.get("ref_imgs") or []) if r and not r.startswith("http")]
        try:
            if ref_paths:
                # Tem imagens de referência → usar nano-banana/edit (Gemini 2.5 Flash)
                image_urls = []
                for rp in ref_paths[:4]:   # máx 4 refs
                    full = PROJECT_ROOT / rp
                    if full.exists():
                        image_urls.append(fal_client.upload_file(str(full)))
                if image_urls:
                    # Com refs → nano-banana/edit (Gemini 2.5 Flash + referências)
                    res = fal_client.subscribe("fal-ai/nano-banana/edit", arguments={
                        "prompt": img_prompt,
                        "image_urls": image_urls,
                        "num_images": 1,
                        "aspect_ratio": "16:9",
                        "output_format": "png",
                    })
                else:
                    # Refs não encontradas em disco → text-to-image
                    res = fal_client.subscribe("fal-ai/nano-banana", arguments={
                        "prompt": img_prompt,
                        "num_images": 1,
                        "aspect_ratio": "16:9",
                        "output_format": "png",
                    })
            else:
                # Sem ref_imgs na cena → nano-banana text-to-image
                res = fal_client.subscribe("fal-ai/nano-banana", arguments={
                    "prompt": img_prompt,
                    "num_images": 1,
                    "aspect_ratio": "16:9",
                    "output_format": "png",
                })
            url   = res["images"][0]["url"]
            fname = secure_filename(f"{job.get('label','scene')[:40]}.png").replace(" ", "_")
            dest  = img_dir / fname
            urllib_req.urlretrieve(url, str(dest))
            rel   = str(dest.relative_to(PROJECT_ROOT))
            # Preserva as ref_imgs originais e adiciona a imagem gerada como primeira
            orig_refs = [r for r in (job.get("ref_imgs") or []) if r != rel]
            jobs[i] = {**job, "ref_imgs": [rel] + orig_refs}
        except Exception as e:
            errors.append(f"Cena {i+1}: {e}")

    with nq_lock:
        nq2 = next((q for q in named_queues if q["id"] == nq_id), None)
        if nq2:
            nq2["jobs"] = jobs
    _save_queues()
    return jsonify({"ok": True, "updated": len(jobs), "errors": errors})


@app.route("/nqueues/<int:nq_id>/generate-audio", methods=["POST"])
def nq_generate_audio(nq_id):
    nq, proj_name = _nq_get_project(nq_id)
    if nq is None:
        return jsonify({"error": "Fila não encontrada"}), 404
    if not proj_name:
        return jsonify({"error": "Episódio não vinculado a um projeto"}), 400
    try:
        from elevenlabs.client import ElevenLabs as EL
    except ImportError:
        return jsonify({"error": "elevenlabs não instalado"}), 500

    cfg         = _load_global_config()
    el_key      = cfg.get("elevenlabs_key", "") or os.environ.get("ELEVENLABS_API_KEY", "")
    global_voice = cfg.get("elevenlabs_voice_id", "")
    if not el_key:
        return jsonify({"error": "ElevenLabs não configurado. Clique em ⚙ na aba Projetos."}), 400

    # Mapa de vozes por personagem extraído dos docs do projeto
    proj_voices = _parse_project_voices(proj_name)

    ep_slug = nq.get("ep_code") or re.sub(r'[^\w\-]', '_', nq.get("name", f"ep_{nq_id}"))[:60]
    aud_dir = PROJECTS_DIR / proj_name / "episodios" / ep_slug / "audios"
    aud_dir.mkdir(parents=True, exist_ok=True)
    client  = EL(api_key=el_key)

    with nq_lock:
        jobs = list(nq.get("jobs", []))

    errors = []
    for i, job in enumerate(jobs):
        text = job.get("audio_text") or ""
        if not text:
            continue
        # Voz: 1) voice_id do próprio job, 2) match por nome do personagem no label, 3) global
        voice = (
            job.get("voice_id")
            or (proj_voices and _match_voice(proj_voices, job.get("label", ""), ""))
            or global_voice
        )
        if not voice:
            errors.append(f"Cena {i+1}: nenhuma voz configurada")
            continue
        try:
            audio_bytes = b"".join(client.text_to_speech.convert(
                text=text, voice_id=voice,
                model_id="eleven_multilingual_v2",
                output_format="mp3_44100_128"
            ))
            fname = secure_filename(f"{job.get('label','scene')[:40]}.mp3").replace(" ", "_")
            dest  = aud_dir / fname
            dest.write_bytes(audio_bytes)
            rel   = str(dest.relative_to(PROJECT_ROOT))
            # Sincroniza duração do job com a duração real do áudio (+1s de respiro)
            import math
            aud_dur = _audio_duration(dest)
            new_job = {**job, "input_audio": rel, "voice_id": voice}
            if aud_dur > 0:
                min_dur = math.ceil(aud_dur) + 1
                if new_job.get("duration", 0) < min_dur:
                    new_job["duration"] = min_dur
                    print(f"[audio-gen] cena '{job.get('label','')}': áudio {aud_dur:.1f}s → duration={min_dur}s")
            jobs[i] = new_job
        except Exception as e:
            errors.append(f"Cena {i+1}: {e}")

    with nq_lock:
        nq2 = next((q for q in named_queues if q["id"] == nq_id), None)
        if nq2:
            nq2["jobs"] = jobs
    _save_queues()
    return jsonify({"ok": True, "updated": len(jobs), "errors": errors})


# ─────────────────────────────────────────────────────────────

_load_queues()
_save_queues()   # persiste ep_codes atribuídos retroactivamente

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7860, debug=False, threaded=True)
