"""FastAPI server for async encrypted HE job submission and monitoring."""

from __future__ import annotations

import base64
import html
import json
import logging
import uuid
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from jinja2 import BaseLoader, Environment, select_autoescape
from redis import Redis
from rq import Queue
from rq.job import Job
from starlette.datastructures import UploadFile

from .job_types import ANALYSIS_TO_JOB_TYPE, JOB_TYPES, canonical_job_type, public_job_types, visible_job_types
from .runner import create_result_bundle, read_log_tail
from .security import normalize_upload_path
from .settings import Settings, get_settings
from .storage import (
    create_job_record,
    directory_size,
    get_job,
    init_db,
    job_dir,
    list_completed_jobs,
    list_jobs,
    now_iso,
    output_dir,
    result_bundle_path,
    update_job,
    use_case_results,
    work_dir,
)


app = FastAPI(title="Home Credit HE EDA Async Job Server", version="0.2.0")
templates = Environment(loader=BaseLoader(), autoescape=select_autoescape(["html", "xml"]))
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("he_async_web")


def settings() -> Settings:
    return get_settings()


def redis_connection(cfg: Settings) -> Redis:
    return Redis.from_url(cfg.redis_url)


def queue_connection(cfg: Settings) -> Queue:
    return Queue(cfg.queue_name, connection=redis_connection(cfg))


def require_auth(request: Request, cfg: Settings, provided_token: str | None = None) -> None:
    if not cfg.auth_token:
        return
    auth = request.headers.get("Authorization", "")
    query_token = request.query_params.get("token", "")
    cookie_token = request.cookies.get("he_receiver_token", "")
    if (
        auth == f"Bearer {cfg.auth_token}"
        or provided_token == cfg.auth_token
        or query_token == cfg.auth_token
        or cookie_token == cfg.auth_token
    ):
        return
    raise HTTPException(status_code=401, detail="unauthorized")


def make_job_id() -> str:
    return now_iso().replace("-", "").replace(":", "").replace("T", "-").replace("Z", "") + "-" + uuid.uuid4().hex[:8]


def render_page(title: str, active: str, body: str) -> HTMLResponse:
    template = templates.from_string(
        """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ title }}</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f7fb;
      --panel: #ffffff;
      --ink: #1f2937;
      --muted: #667085;
      --line: #d6deea;
      --accent: #0f766e;
      --blue: #0b5c8e;
      --good: #047857;
      --bad: #b42318;
      --warn: #b54708;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: var(--bg);
    }
    header {
      background: var(--panel);
      border-bottom: 1px solid var(--line);
    }
    .wrap {
      width: min(1180px, calc(100vw - 32px));
      margin: 0 auto;
    }
    header .wrap {
      min-height: 68px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
    }
    h1 {
      margin: 0;
      font-size: 20px;
      letter-spacing: 0;
    }
    nav {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    nav a, .button, button {
      display: inline-flex;
      align-items: center;
      min-height: 36px;
      border: 0;
      border-radius: 6px;
      padding: 8px 12px;
      background: #e9eef6;
      color: #111827;
      font: inherit;
      font-weight: 720;
      text-decoration: none;
      cursor: pointer;
    }
    nav a.active, .button.primary, button.primary {
      background: var(--accent);
      color: white;
    }
    main {
      padding: 22px 0 36px;
    }
    section, .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
      margin-bottom: 16px;
    }
    h2 {
      font-size: 18px;
      margin: 0 0 14px;
      letter-spacing: 0;
    }
    h3 {
      font-size: 15px;
      margin: 18px 0 8px;
      letter-spacing: 0;
    }
    p, li {
      line-height: 1.45;
    }
    label {
      display: block;
      font-size: 13px;
      font-weight: 720;
      color: #344054;
      margin: 12px 0 6px;
    }
    select, input, textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px 11px;
      background: #fff;
      color: var(--ink);
      font: inherit;
    }
    input[type="file"] {
      border: 1px dashed #aab4c3;
      background: #fbfcfe;
    }
    textarea {
      min-height: 78px;
      resize: vertical;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }
    th, td {
      border-bottom: 1px solid var(--line);
      padding: 9px 8px;
      text-align: left;
      vertical-align: top;
    }
    th {
      color: var(--muted);
      background: #fbfcfe;
      font-weight: 750;
    }
    code {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: .95em;
    }
    pre {
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      background: #111827;
      color: #e5e7eb;
      border-radius: 8px;
      padding: 12px;
      min-height: 190px;
      max-height: 440px;
      overflow: auto;
      font-size: 12px;
    }
    .grid {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(320px, .85fr);
      gap: 16px;
      align-items: start;
    }
    .cards {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }
    .card {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 13px;
      background: #fbfcfe;
    }
    .muted {
      color: var(--muted);
      font-size: 13px;
    }
    .status {
      display: inline-flex;
      border-radius: 999px;
      padding: 3px 8px;
      background: #eef2ff;
      color: #3730a3;
      font-size: 12px;
      font-weight: 780;
    }
    .status.running { background: #fff7ed; color: var(--warn); }
    .status.queued, .status.uploaded { background: #eff6ff; color: var(--blue); }
    .status.succeeded { background: #ecfdf3; color: var(--good); }
    .status.failed, .status.cancelled { background: #fff1f3; color: var(--bad); }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      margin-top: 16px;
    }
    .file-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }
    @media (max-width: 860px) {
      header .wrap { align-items: flex-start; flex-direction: column; padding: 14px 0; }
      .grid, .cards, .file-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
<header>
  <div class="wrap">
    <h1>Home Credit HE EDA Jobs</h1>
    <nav>
      <a href="/jobs/new" class="{{ 'active' if active == 'new' else '' }}">Submit EDA</a>
      <a href="/jobs" class="{{ 'active' if active == 'jobs' else '' }}">Jobs</a>
      <a href="/results" class="{{ 'active' if active == 'results' else '' }}">Results</a>
    </nav>
  </div>
</header>
<main class="wrap">
{{ body | safe }}
</main>
</body>
</html>"""
    )
    return HTMLResponse(template.render(title=title, active=active, body=body))


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def parse_utc_timestamp(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def duration_seconds(start: datetime | None, end: datetime | None) -> int | None:
    if not start or not end:
        return None
    return max(0, int((end - start).total_seconds()))


def format_duration(seconds: int | None) -> str:
    if seconds is None:
        return ""
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {sec}s"
    if minutes:
        return f"{minutes}m {sec}s"
    return f"{sec}s"


def add_timing(job: dict[str, Any]) -> dict[str, Any]:
    item = dict(job)
    now = datetime.now(timezone.utc)
    created = parse_utc_timestamp(item.get("created_at"))
    started = parse_utc_timestamp(item.get("started_at"))
    finished = parse_utc_timestamp(item.get("finished_at"))
    end = finished or now

    queued_seconds = duration_seconds(created, started)
    runtime_seconds = duration_seconds(started, end)
    total_seconds = duration_seconds(created, end)

    item["queued_seconds"] = queued_seconds
    item["runtime_seconds"] = runtime_seconds
    item["total_elapsed_seconds"] = total_seconds
    item["queued_duration"] = format_duration(queued_seconds)
    item["runtime_duration"] = format_duration(runtime_seconds)
    item["total_elapsed_duration"] = format_duration(total_seconds)
    return item


def add_timing_all(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [add_timing(job) for job in jobs]


def job_table(jobs: list[dict[str, Any]]) -> str:
    rows = []
    for job in add_timing_all(jobs):
        rows.append(
            f"""<tr>
  <td><a href="/jobs/{esc(job['job_id'])}"><code>{esc(job['job_id'])}</code></a></td>
  <td>{esc(job['label'])}<br><span class="muted"><code>{esc(job['job_type'])}</code></span></td>
  <td><span class="status {esc(job['status'])}">{esc(job['status'])}</span></td>
  <td>{esc(job.get('created_at') or '')}</td>
  <td>{esc(job.get('finished_at') or '')}</td>
  <td>{esc(job.get('runtime_duration') or '')}</td>
  <td>{esc(job.get('total_elapsed_duration') or '')}</td>
  <td>{len(job.get('output_files') or [])}</td>
</tr>"""
        )
    if not rows:
        rows.append('<tr><td colspan="8" class="muted">No jobs yet.</td></tr>')
    return (
        "<table><thead><tr><th>Job</th><th>EDA criterion</th><th>Status</th>"
        "<th>Created</th><th>Finished</th><th>HE runtime</th><th>Total elapsed</th><th>Outputs</th></tr></thead><tbody>"
        + "\n".join(rows)
        + "</tbody></table>"
    )


def required_files_present(root: Path, job_type: str) -> bool:
    for item in JOB_TYPES[job_type]["required"]:
        if item.endswith("/"):
            if not (root / item.rstrip("/")).is_dir():
                return False
        elif not (root / item).is_file():
            return False
    return True


def detect_job_type(root: Path) -> str:
    upload_manifest = root / "upload_bag_manifest.json"
    if upload_manifest.is_file():
        try:
            manifest = json.loads(upload_manifest.read_text(encoding="utf-8"))
            manifest_job_type = canonical_job_type(str(manifest.get("job_type") or ""))
            if manifest_job_type in JOB_TYPES and required_files_present(root, manifest_job_type):
                return manifest_job_type
        except (OSError, json.JSONDecodeError):
            pass

    if required_files_present(root, "home_credit_application_numeric_summary"):
        return "home_credit_application_numeric_summary"
    if required_files_present(root, "home_credit_linear_score_demo"):
        return "home_credit_linear_score_demo"
    aggregate_probe = "home_credit_application_category_counts"
    if required_files_present(root, aggregate_probe):
        manifest = root / "aggregate_manifest.csv"
        try:
            lines = manifest.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines = []
        for line in lines[1:50]:
            first = line.split(",", 1)[0].strip().lower()
            detected = ANALYSIS_TO_JOB_TYPE.get(first)
            if detected:
                return detected
        return "home_credit_application_category_counts"
    raise HTTPException(
        status_code=400,
        detail=(
            "could not auto-detect Home Credit EDA criterion from artifact; upload a zip "
            "made by package_home_credit_upload_bag.py or choose the criterion explicitly"
        ),
    )


@app.on_event("startup")
def startup() -> None:
    cfg = settings()
    init_db(cfg)
    logger.info(
        "async web startup jobs_dir=%s build_dir=%s db_path=%s redis_url=%s queue=%s",
        cfg.jobs_dir,
        cfg.build_dir,
        cfg.db_path,
        cfg.redis_url,
        cfg.queue_name,
    )


@app.get("/", response_class=HTMLResponse)
def root() -> RedirectResponse:
    return RedirectResponse("/jobs")


@app.get("/jobs/new", response_class=HTMLResponse)
def submit_page() -> HTMLResponse:
    cards = []
    options = ['<option value="auto" selected>Auto-detect from artifact</option>']
    for job_type, cfg in visible_job_types().items():
        options.append(f'<option value="{esc(job_type)}">{esc(cfg["label"])}</option>')
        requirements = "".join(f"<li><code>{esc(item)}</code></li>" for item in cfg["required"])
        returns = "".join(f"<li><code>{esc(item)}</code></li>" for item in cfg.get("server_returns", []))
        client_requirements = "".join(f"<li>{esc(item)}</li>" for item in cfg.get("client_requirements", []))
        cards.append(
            f"""<div class="card">
  <h3>{esc(cfg['label'])}</h3>
  <p class="muted">{esc(cfg['description'])}</p>
  <p><strong>Notebook cells</strong>: <code>{esc(cfg.get('notebook_cells', ''))}</code></p>
  <p><strong>HE operation</strong>: <code>{esc(cfg.get('he_operation', ''))}</code></p>
  <p><strong>Client preparation</strong></p>
  <ul>{client_requirements}</ul>
  <p><strong>Upload contract</strong></p>
  <ul>{requirements}</ul>
  <p><strong>Encrypted server returns</strong></p>
  <ul>{returns}</ul>
</div>"""
        )
    body = f"""
<div class="grid">
  <section>
    <h2>Submit Encrypted Home Credit EDA</h2>
    <form id="submitJobForm" method="post" action="/jobs/new" enctype="multipart/form-data">
      <label for="job_type">Notebook EDA criterion</label>
      <select id="job_type" name="job_type">{"".join(options)}</select>

      <label for="access_token">Web token</label>
      <input id="access_token" name="access_token" type="password" autocomplete="off" placeholder="Only needed when HE_RECEIVER_TOKEN is set">

      <label for="artifact">Encrypted upload bag</label>
      <input id="artifact" type="file" name="files" accept=".zip">
      <p class="muted">Upload one criterion zip produced by <code>package_home_credit_upload_bag.py --workload ...</code>. The server extracts it, normalizes the bundle layout, and keeps only encrypted artifacts/manifests.</p>

      <label for="note">Client note</label>
      <textarea id="note" name="note" placeholder="Dataset, row limit, criterion, test name"></textarea>

      <div class="actions">
        <button id="queueButton" class="primary" type="submit">Queue Job</button>
        <a class="button" href="/jobs">View Jobs</a>
      </div>
      <p id="uploadStatus" class="muted">Ready.</p>
    </form>
  </section>
  <section>
    <h2>Server Boundary</h2>
    <p class="muted">The server stores encrypted artifacts, public/eval keys, job metadata, logs, and encrypted Home Credit EDA result bundles.</p>
    <p><strong>Never upload</strong></p>
    <ul>
      <li>raw Home Credit CSV files</li>
      <li>plaintext prepared vectors</li>
      <li><code>secret_key.bin</code> or private keys</li>
      <li>decrypted reports</li>
    </ul>
  </section>
</div>
<section>
  <h2>Available Notebook Criteria</h2>
  <div class="cards">{"".join(cards)}</div>
</section>
<script>
const form = document.getElementById('submitJobForm');
const button = document.getElementById('queueButton');
const statusLine = document.getElementById('uploadStatus');

form.addEventListener('submit', (event) => {{
  event.preventDefault();
  const artifact = document.getElementById('artifact');
  if (!artifact.files.length) {{
    statusLine.textContent = 'Choose an encrypted upload bag zip first.';
    return;
  }}
  button.disabled = true;
  statusLine.textContent = 'Starting upload...';
  const xhr = new XMLHttpRequest();
  xhr.open('POST', form.action);
  xhr.upload.addEventListener('progress', (progress) => {{
    if (progress.lengthComputable) {{
      const percent = Math.round((progress.loaded / progress.total) * 100);
      statusLine.textContent = `Uploading encrypted bag... ${{percent}}%`;
    }} else {{
      statusLine.textContent = 'Uploading encrypted bag...';
    }}
  }});
  xhr.addEventListener('load', () => {{
    if (xhr.status >= 200 && xhr.status < 400) {{
      statusLine.textContent = 'Upload accepted. Opening job page...';
      window.location.href = xhr.responseURL || '/jobs';
    }} else {{
      statusLine.textContent = `Submit failed: ${{xhr.status}} ${{xhr.statusText}} ${{xhr.responseText.slice(0, 240)}}`;
      button.disabled = false;
    }}
  }});
  xhr.addEventListener('error', () => {{
    statusLine.textContent = 'Upload failed before reaching the server.';
    button.disabled = false;
  }});
  xhr.send(new FormData(form));
}});
</script>
"""
    return render_page("Submit HE Job", "new", body)


@app.post("/jobs/new")
async def submit_form(request: Request) -> RedirectResponse:
    cfg = settings()
    content_length = request.headers.get("content-length", "unknown")
    logger.info("submit request received client=%s content_length=%s", request.client, content_length)
    try:
        form = await request.form()
        logger.info("submit form parsed client=%s field_count=%s", request.client, len(form))
        access_token = str(form.get("access_token") or "")
        require_auth(request, cfg, access_token)
        job = await create_job_from_form(request, cfg, form)
        logger.info(
            "submit queued job_id=%s job_type=%s files=%s bytes=%s",
            job["job_id"],
            job["job_type"],
            job["input_file_count"],
            job["input_bytes"],
        )
        response = RedirectResponse(f"/jobs/{job['job_id']}", status_code=303)
        if access_token:
            response.set_cookie("he_receiver_token", access_token, httponly=True, samesite="lax")
        return response
    except Exception:
        logger.exception("submit request failed client=%s content_length=%s", request.client, content_length)
        raise


@app.get("/jobs", response_class=HTMLResponse)
def jobs_page() -> HTMLResponse:
    cfg = settings()
    init_db(cfg)
    jobs = list_jobs(cfg, limit=200)
    body = f"""
<section>
  <div class="actions" style="justify-content: space-between; margin-top: 0;">
    <h2 style="margin: 0;">Job Monitor</h2>
    <a class="button primary" href="/jobs/new">Submit Job</a>
  </div>
  <p class="muted">This page is the slow-HE waiting room: queued, running, completed, and failed jobs.</p>
  {job_table(jobs)}
</section>
<script>setTimeout(() => window.location.reload(), 5000);</script>
"""
    return render_page("HE Jobs", "jobs", body)


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_detail_page(job_id: str, request: Request) -> HTMLResponse:
    cfg = settings()
    init_db(cfg)
    try:
        job = add_timing(get_job(cfg, job_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    output_links = []
    for item in job.get("output_files", []):
        output_links.append(
            f'<li><a href="/api/jobs/{esc(job_id)}/download?path={quote(str(item), safe="")}"><code>{esc(item)}</code></a></li>'
        )
    outputs = "".join(output_links)
    bundle = ""
    if job["status"] == "succeeded":
        bundle = f'<a class="button primary" href="/api/jobs/{esc(job_id)}/download-bundle">Download result bundle</a>'
    body = f"""
<section>
  <div class="actions" style="justify-content: space-between; margin-top: 0;">
    <h2 style="margin: 0;">Job <code>{esc(job_id)}</code></h2>
    <a class="button" href="/jobs">Back to Jobs</a>
  </div>
  <p><span class="status {esc(job['status'])}">{esc(job['status'])}</span> {esc(job['label'])}</p>
  <p class="muted">HE runtime: {esc(job.get('runtime_duration') or 'not started')} | Total elapsed: {esc(job.get('total_elapsed_duration') or '')}</p>
  <div class="actions">
    {bundle}
    <a class="button" href="/api/jobs/{esc(job_id)}">JSON status</a>
    <a class="button" href="/api/jobs/{esc(job_id)}/logs">Raw log</a>
  </div>
</section>
<div class="grid">
  <section>
    <h2>Status</h2>
    <pre id="status">{esc(json.dumps(job, indent=2))}</pre>
  </section>
  <section>
    <h2>Output Files</h2>
    <ul>{outputs or '<li class="muted">No output files yet.</li>'}</ul>
  </section>
</div>
<section>
  <h2>Server Log</h2>
  <pre id="log">Loading...</pre>
</section>
<script>
async function refreshDetail() {{
  const statusRes = await fetch('/api/jobs/{job_id}');
  if (statusRes.ok) {{
    const data = await statusRes.json();
    document.getElementById('status').textContent = JSON.stringify(data, null, 2);
  }}
  const logRes = await fetch('/api/jobs/{job_id}/logs');
  if (logRes.ok) {{
    document.getElementById('log').textContent = await logRes.text();
  }}
}}
refreshDetail();
setInterval(refreshDetail, 3000);
</script>
"""
    return render_page(f"Job {job_id}", "jobs", body)


@app.get("/results", response_class=HTMLResponse)
def results_page(request: Request) -> HTMLResponse:
    cfg = settings()
    init_db(cfg)
    completed = add_timing_all(list_completed_jobs(cfg, limit=200))
    rows = []
    for job in completed:
        rows.append(
            f"""<tr>
  <td><a href="/jobs/{esc(job['job_id'])}"><code>{esc(job['job_id'])}</code></a></td>
  <td>{esc(job['label'])}</td>
  <td>{esc(job.get('finished_at') or '')}</td>
  <td>{esc(job.get('runtime_duration') or '')}</td>
  <td>{job.get('output_bytes') or 0}</td>
  <td><a class="button primary" href="/api/jobs/{esc(job['job_id'])}/download-bundle">Download</a></td>
</tr>"""
        )
    if not rows:
        rows.append('<tr><td colspan="6" class="muted">No completed encrypted result bundles yet.</td></tr>')
    use_cases = use_case_results(cfg)
    cards = []
    for item in use_cases:
        cards.append(
            f"""<div class="card">
  <h3>{esc(item['label'])}</h3>
  <p><span class="status {esc(item['latest_status'])}">{esc(item['latest_status'])}</span></p>
  <p class="muted">Latest: {esc(item['latest_job_id'] or 'none')}</p>
</div>"""
        )
    body = f"""
<section>
  <h2>Result Index</h2>
  <p class="muted">Completed encrypted bundles only. The server still does not decrypt.</p>
  <p><strong>Client pull latest</strong></p>
  <pre>python3 code/client/home_credit/download_job_bundle.py \\
  --server {esc(str(request.base_url).rstrip('/'))} \\
  --job-id latest</pre>
  <table><thead><tr><th>Job</th><th>EDA criterion</th><th>Finished</th><th>HE runtime</th><th>Output bytes</th><th>Bundle</th></tr></thead><tbody>{"".join(rows)}</tbody></table>
</section>
<section>
  <h2>EDA Criterion Status</h2>
  <div class="cards">{"".join(cards)}</div>
</section>
"""
    return render_page("HE Results", "results", body)


async def create_job_from_form(request: Request, cfg: Settings, form: Any) -> dict[str, Any]:
    job_type = str(form.get("job_type") or "auto")
    note = str(form.get("note") or "")
    uploads = [
        value
        for key, value in form.multi_items()
        if key == "files" and isinstance(value, UploadFile) and value.filename
    ]
    return await save_and_enqueue(request, cfg, job_type=job_type, note=note, uploads=uploads, json_files=None)


async def save_and_enqueue(
    request: Request,
    cfg: Settings,
    *,
    job_type: str,
    note: str,
    uploads: list[UploadFile] | None,
    json_files: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    job_type = canonical_job_type(job_type)
    explicit_auto = job_type in {"", "auto", "detect"}
    if not explicit_auto and job_type not in JOB_TYPES:
        raise HTTPException(status_code=400, detail=f"unknown job_type: {job_type}")
    if not explicit_auto and JOB_TYPES[job_type].get("disabled"):
        raise HTTPException(status_code=400, detail=f"job_type is disabled: {job_type}")

    job_id = make_job_id()
    root = work_dir(cfg, job_id)
    root.mkdir(parents=True, exist_ok=False)
    saved: list[str] = []
    total_bytes = 0
    seen: set[str] = set()
    logger.info("job %s upload save begin requested_job_type=%s", job_id, job_type)

    def save_payload_file(raw_path: str, data: bytes) -> None:
        nonlocal total_bytes
        rel = normalize_upload_path(raw_path)
        rel_posix = rel.as_posix()
        if rel_posix in seen:
            raise HTTPException(status_code=400, detail=f"duplicate upload path: {rel_posix}")
        seen.add(rel_posix)
        total_bytes += len(data)
        if total_bytes > cfg.max_upload_bytes:
            raise HTTPException(status_code=413, detail=f"upload exceeds {cfg.max_upload_bytes} bytes")
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        saved.append(rel_posix)

    def save_zip_payload(raw_path: str, data: bytes) -> None:
        logger.info("job %s zip received name=%s bytes=%s", job_id, raw_path, len(data))
        try:
            archive = zipfile.ZipFile(BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise HTTPException(status_code=400, detail=f"invalid zip artifact: {raw_path}") from exc
        members = archive.infolist()
        logger.info("job %s zip opened entries=%s", job_id, len(members))
        before_count = len(saved)
        for member in members:
            if member.is_dir():
                continue
            with archive.open(member) as handle:
                save_payload_file(member.filename, handle.read())
        logger.info("job %s zip extracted files=%s", job_id, len(saved) - before_count)

    if uploads is not None:
        for upload in uploads:
            data = await upload.read()
            filename = upload.filename or ""
            if filename.lower().endswith(".zip"):
                save_zip_payload(filename, data)
            else:
                save_payload_file(filename, data)

    if json_files is not None:
        for item in json_files:
            encoded = item.get("content_base64")
            if not isinstance(encoded, str):
                raise HTTPException(status_code=400, detail="missing content_base64 for JSON upload file")
            try:
                data = base64.b64decode(encoded, validate=True)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="invalid base64 for JSON upload file") from exc
            raw_path = str(item.get("path", ""))
            if raw_path.lower().endswith(".zip"):
                save_zip_payload(raw_path, data)
            else:
                save_payload_file(raw_path, data)

    if not saved:
        raise HTTPException(status_code=400, detail="no files uploaded")

    if explicit_auto:
        job_type = detect_job_type(root)
        logger.info("job %s auto-detected job_type=%s", job_id, job_type)
    else:
        logger.info("job %s explicit job_type=%s", job_id, job_type)

    init_db(cfg)
    job = create_job_record(cfg, job_id=job_id, job_type=job_type, note=note, input_files=saved, input_bytes=total_bytes)
    logger.info("job %s record created files=%s bytes=%s", job_id, len(saved), total_bytes)
    try:
        queue_job = queue_connection(cfg).enqueue(
            "he_async_web.worker.run_he_job",
            job_id,
            job_timeout=cfg.job_timeout_seconds,
            result_ttl=cfg.result_ttl_seconds,
        )
    except Exception as exc:  # noqa: BLE001 - return useful server state to the UI
        update_job(cfg, job_id, status="failed", error=f"failed to enqueue RQ job: {exc}")
        logger.exception("job %s enqueue failed", job_id)
        raise HTTPException(status_code=503, detail=f"failed to enqueue RQ job: {exc}") from exc
    logger.info("job %s enqueued rq_job_id=%s", job_id, queue_job.id)
    return update_job(cfg, job_id, status="queued", rq_job_id=queue_job.id)


@app.get("/api/health")
def api_health(request: Request) -> dict[str, Any]:
    cfg = settings()
    require_auth(request, cfg)
    init_db(cfg)
    redis_status = "unknown"
    try:
        redis_connection(cfg).ping()
        redis_status = "ok"
    except Exception as exc:  # noqa: BLE001 - health should stay readable
        redis_status = f"error: {exc}"
    return {
        "status": "ok",
        "redis": redis_status,
        "redis_url": cfg.redis_url,
        "queue": cfg.queue_name,
        "jobs_dir": str(cfg.jobs_dir),
        "build_dir": str(cfg.build_dir),
        "db_path": str(cfg.db_path),
        "auth_required": bool(cfg.auth_token),
    }


@app.get("/api/job-types")
@app.get("/api/workloads")
def api_job_types(request: Request) -> dict[str, Any]:
    require_auth(request, settings())
    return {"job_types": public_job_types()}


@app.get("/api/jobs")
def api_jobs(request: Request, status: str | None = None, limit: int = 100) -> dict[str, Any]:
    cfg = settings()
    require_auth(request, cfg)
    init_db(cfg)
    return {"jobs": add_timing_all(list_jobs(cfg, status=status, limit=limit))}


@app.post("/api/jobs")
async def api_create_job(request: Request) -> dict[str, Any]:
    cfg = settings()
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        require_auth(request, cfg)
        payload = await request.json()
        return await save_and_enqueue(
            request,
            cfg,
            job_type=str(payload.get("job_type") or ""),
            note=str(payload.get("note") or ""),
            uploads=None,
            json_files=payload.get("files") or [],
        )

    form = await request.form()
    require_auth(request, cfg, str(form.get("access_token") or ""))
    return await create_job_from_form(request, cfg, form)


@app.get("/api/jobs/{job_id}")
def api_job(job_id: str, request: Request) -> dict[str, Any]:
    cfg = settings()
    require_auth(request, cfg)
    init_db(cfg)
    try:
        return add_timing(get_job(cfg, job_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/jobs/{job_id}/logs", response_class=PlainTextResponse)
def api_job_logs(job_id: str, request: Request) -> PlainTextResponse:
    cfg = settings()
    require_auth(request, cfg)
    try:
        get_job(cfg, job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return PlainTextResponse(read_log_tail(cfg, job_id))


@app.get("/api/jobs/{job_id}/download-bundle")
def api_download_bundle(job_id: str, request: Request) -> FileResponse:
    cfg = settings()
    require_auth(request, cfg)
    try:
        job = get_job(cfg, job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if job["status"] != "succeeded":
        raise HTTPException(status_code=409, detail=f"job is not succeeded: {job['status']}")
    bundle = result_bundle_path(cfg, job_id)
    if not bundle.exists():
        bundle = create_result_bundle(cfg, job_id)
        update_job(cfg, job_id, result_bundle=str(bundle), output_bytes=directory_size(output_dir(cfg, job_id)))
    return FileResponse(bundle, media_type="application/zip", filename=f"{job_id}-encrypted-results.zip")


@app.get("/api/jobs/{job_id}/download")
def api_download_file(job_id: str, path: str, request: Request) -> FileResponse:
    cfg = settings()
    require_auth(request, cfg)
    try:
        get_job(cfg, job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    rel = PurePosixPath(path.replace("\\", "/").strip("/"))
    if rel.is_absolute() or ".." in rel.parts:
        raise HTTPException(status_code=400, detail="unsafe output path")
    target = output_dir(cfg, job_id) / Path(*rel.parts)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="output file not found")
    return FileResponse(target, filename=target.name)


@app.get("/api/results")
def api_results(request: Request, limit: int = 100) -> dict[str, Any]:
    cfg = settings()
    require_auth(request, cfg)
    init_db(cfg)
    criteria = use_case_results(cfg)
    return {
        "results": add_timing_all(list_completed_jobs(cfg, limit=limit)),
        "criteria": criteria,
        "use_cases": criteria,
    }


@app.post("/api/jobs/{job_id}/cancel")
def api_cancel_job(job_id: str, request: Request) -> dict[str, Any]:
    cfg = settings()
    require_auth(request, cfg)
    try:
        job = get_job(cfg, job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if job["status"] not in {"uploaded", "queued"}:
        raise HTTPException(status_code=409, detail=f"cannot cancel status {job['status']}")
    if job.get("rq_job_id"):
        try:
            rq_job = Job.fetch(job["rq_job_id"], connection=redis_connection(cfg))
            rq_job.cancel()
        except Exception:
            pass
    return update_job(cfg, job_id, status="cancelled", finished_at=now_iso())
