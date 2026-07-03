#!/usr/bin/env python3
"""Tiny no-dependency web receiver for encrypted HE job bundles.

The web layer intentionally does not implement HE math. It accepts encrypted
files, stores them under server_jobs/, and invokes the existing C++ binaries.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import os
import subprocess
import threading
import time
import uuid
import zipfile
from io import BytesIO
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import parse_qs, urlparse


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_JOBS_DIR = REPO_ROOT / "server_jobs" / "web"
DEFAULT_BUILD_DIR = REPO_ROOT / "build"
STATIC_INDEX = Path(__file__).resolve().parent / "static" / "index.html"
MAX_UPLOAD_BYTES = int(os.environ.get("HE_WEB_MAX_UPLOAD_BYTES", str(512 * 1024 * 1024)))
MAX_WORKERS = int(os.environ.get("HE_WEB_MAX_WORKERS", "1"))
AUTH_TOKEN = os.environ.get("HE_RECEIVER_TOKEN", "")
STATUS_LOCK = threading.Lock()
WORKER_SEMAPHORE = threading.Semaphore(MAX_WORKERS)


JOB_TYPES: dict[str, dict[str, Any]] = {
    "home_credit_numeric_summary": {
        "label": "Home Credit Numeric Summary",
        "family": "Home Credit",
        "stage": "Application-train aggregate",
        "scheme": "CKKS",
        "binary": "server_numeric_summary",
        "description": "Packed encrypted sums for selected Home Credit numeric columns.",
        "required": ["crypto_context.bin", "eval_sum_keys.bin", "column_manifest.csv", "columns/"],
        "client_requirements": [
            "Use application_train.csv as the first Home Credit source table.",
            "Rows with null/invalid selected numeric fields removed or imputed before encryption.",
            "Numeric columns such as AMT_CREDIT, AMT_INCOME_TOTAL, AMT_ANNUITY, EXT_SOURCE_1/2/3, and DAYS_BIRTH packed into encrypted chunks.",
            "No raw CSV, plaintext prepared CSV, SK_ID-level plaintext joins, secret key, or decrypted report in the upload.",
            "Manifest rows must point to ciphertext files under columns/.",
        ],
        "client_artifacts": [
            "crypto_context.bin",
            "eval_sum_keys.bin",
            "column_manifest.csv",
            "columns/*.bin",
        ],
        "server_returns": ["numeric_summary/summary_manifest.csv", "numeric_summary/sums/*.bin"],
        "command": [
            "--context",
            "crypto_context.bin",
            "--eval-sum-keys",
            "eval_sum_keys.bin",
            "--manifest",
            "column_manifest.csv",
            "--input-dir",
            "columns",
            "--output-dir",
            "output/numeric_summary",
        ],
    },
    "home_credit_category_eda": {
        "label": "Category Default-Rate EDA",
        "family": "Home Credit",
        "stage": "Category-risk EDA",
        "scheme": "CKKS",
        "binary": "server_home_credit_aggregate",
        "description": "Encrypted applicant counts, default counts, and amount sums by one-hot Home Credit category buckets.",
        "required": ["crypto_context.bin", "eval_sum_keys.bin", "eval_mult_keys.bin", "aggregate_manifest.csv", "vectors/"],
        "client_requirements": [
            "Encode categories such as NAME_INCOME_TYPE, OCCUPATION_TYPE, NAME_EDUCATION_TYPE, and ORGANIZATION_TYPE as one-hot encrypted masks.",
            "Map null category values into an explicit NULL_OR_UNKNOWN bucket before encryption.",
            "Encrypt TARGET as a 0/1 default mask when target-conditioned reports are requested.",
            "Encrypt numeric amount vectors such as AMT_CREDIT, AMT_INCOME_TOTAL, and AMT_ANNUITY for grouped sums.",
            "No raw strings, raw CSV, plaintext SK_ID joins, or secret keys in the upload.",
        ],
        "client_artifacts": [
            "crypto_context.bin",
            "eval_sum_keys.bin",
            "eval_mult_keys.bin",
            "aggregate_manifest.csv",
            "vectors/*.bin",
        ],
        "server_returns": ["category_eda/aggregate_summary_manifest.csv", "category_eda/aggregates/*.bin"],
        "command": [
            "--context",
            "crypto_context.bin",
            "--eval-sum-keys",
            "eval_sum_keys.bin",
            "--eval-mult-keys",
            "eval_mult_keys.bin",
            "--manifest",
            "aggregate_manifest.csv",
            "--input-dir",
            "vectors",
            "--output-dir",
            "output/category_eda",
            "--analysis-filter",
            "literal:category",
        ],
    },
    "home_credit_bucket_eda": {
        "label": "Age / EXT_SOURCE Bucket EDA",
        "family": "Home Credit",
        "stage": "Bucket-risk EDA",
        "scheme": "CKKS",
        "binary": "server_home_credit_aggregate",
        "description": "Encrypted default-rate tables for age bins, DAYS_EMPLOYED anomaly, and EXT_SOURCE score buckets.",
        "required": ["crypto_context.bin", "eval_sum_keys.bin", "eval_mult_keys.bin", "aggregate_manifest.csv", "vectors/"],
        "client_requirements": [
            "Convert DAYS_BIRTH to positive age years and bucket client-side.",
            "Encode DAYS_EMPLOYED == 365243 as an explicit anomaly mask before encryption.",
            "Bucket EXT_SOURCE_1/2/3 after null handling or explicit null bucket creation.",
            "Encrypt bucket masks and TARGET mask; server only aggregates encrypted masks.",
        ],
        "client_artifacts": [
            "crypto_context.bin",
            "eval_sum_keys.bin",
            "eval_mult_keys.bin",
            "aggregate_manifest.csv",
            "vectors/*.bin",
        ],
        "server_returns": ["bucket_eda/aggregate_summary_manifest.csv", "bucket_eda/aggregates/*.bin"],
        "command": [
            "--context",
            "crypto_context.bin",
            "--eval-sum-keys",
            "eval_sum_keys.bin",
            "--eval-mult-keys",
            "eval_mult_keys.bin",
            "--manifest",
            "aggregate_manifest.csv",
            "--input-dir",
            "vectors",
            "--output-dir",
            "output/bucket_eda",
            "--analysis-filter",
            "literal:bucket",
        ],
    },
    "home_credit_domain_ratio_eda": {
        "label": "Domain Ratio EDA",
        "family": "Home Credit",
        "stage": "Financial-ratio EDA",
        "scheme": "CKKS",
        "binary": "server_home_credit_aggregate",
        "description": "Encrypted aggregate tables for CREDIT_INCOME_PERCENT, ANNUITY_INCOME_PERCENT, CREDIT_TERM, and DAYS_EMPLOYED_PERCENT buckets.",
        "required": ["crypto_context.bin", "eval_sum_keys.bin", "eval_mult_keys.bin", "aggregate_manifest.csv", "vectors/"],
        "client_requirements": [
            "Client computes domain ratios from application_train numeric columns before encryption.",
            "Handle division by zero/nulls client-side with explicit invalid/null buckets.",
            "Encrypt ratio bucket masks and TARGET mask for server-side aggregate counts.",
            "Raw financial values and secret keys stay on the client.",
        ],
        "client_artifacts": [
            "crypto_context.bin",
            "eval_sum_keys.bin",
            "eval_mult_keys.bin",
            "aggregate_manifest.csv",
            "vectors/*.bin",
        ],
        "server_returns": ["ratio_eda/aggregate_summary_manifest.csv", "ratio_eda/aggregates/*.bin"],
        "command": [
            "--context",
            "crypto_context.bin",
            "--eval-sum-keys",
            "eval_sum_keys.bin",
            "--eval-mult-keys",
            "eval_mult_keys.bin",
            "--manifest",
            "aggregate_manifest.csv",
            "--input-dir",
            "vectors",
            "--output-dir",
            "output/ratio_eda",
            "--analysis-filter",
            "literal:ratio",
        ],
    },
    "home_credit_linear_score": {
        "label": "Linear ML Score",
        "family": "Home Credit",
        "stage": "Encrypted inference",
        "scheme": "CKKS",
        "binary": "server_linear_score",
        "description": "Encrypted CKKS weighted-sum inference for a small exported Home Credit linear/logistic model.",
        "required": ["crypto_context.bin", "score_manifest.csv", "score_features/"],
        "client_requirements": [
            "Train/export a small linear model in plaintext, or use the demo policy model for plumbing only.",
            "Prepare scaled numeric feature vectors client-side.",
            "Encrypt feature vectors; server receives only encrypted features and plaintext weights.",
            "Server returns encrypted score chunks; client decrypts and optionally applies sigmoid.",
        ],
        "client_artifacts": ["crypto_context.bin", "score_manifest.csv", "score_features/*.bin"],
        "server_returns": ["linear_score/score_summary_manifest.csv", "linear_score/scores/*.bin"],
        "command": [
            "--context",
            "crypto_context.bin",
            "--manifest",
            "score_manifest.csv",
            "--input-dir",
            "score_features",
            "--output-dir",
            "output/linear_score",
        ],
    },
}


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>HE UC Credit Receiver</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --ink: #20242c;
      --muted: #667085;
      --line: #d9dee8;
      --accent: #0f766e;
      --accent-2: #334155;
      --bad: #b42318;
      --good: #047857;
      --warn: #b54708;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--ink);
    }
    header {
      border-bottom: 1px solid var(--line);
      background: var(--panel);
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
      gap: 20px;
    }
    h1 {
      font-size: 20px;
      margin: 0;
      font-weight: 720;
      letter-spacing: 0;
    }
    main {
      padding: 24px 0 36px;
    }
    .grid {
      display: grid;
      grid-template-columns: minmax(0, 1.05fr) minmax(320px, .95fr);
      gap: 16px;
      align-items: start;
    }
    section, .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    section {
      padding: 18px;
    }
    h2 {
      margin: 0 0 14px;
      font-size: 16px;
      letter-spacing: 0;
    }
    label {
      display: block;
      font-size: 13px;
      font-weight: 650;
      color: var(--accent-2);
      margin: 14px 0 6px;
    }
    select, input[type="text"], input[type="password"], textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px 11px;
      font: inherit;
      background: #fff;
      color: var(--ink);
    }
    textarea {
      min-height: 82px;
      resize: vertical;
    }
    .file-row {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin-top: 10px;
    }
    input[type="file"] {
      width: 100%;
      border: 1px dashed #aab4c3;
      border-radius: 6px;
      padding: 12px;
      background: #fbfcfe;
    }
    button {
      border: 0;
      border-radius: 6px;
      padding: 10px 14px;
      background: var(--accent);
      color: white;
      font-weight: 720;
      cursor: pointer;
    }
    button.secondary {
      background: #e9edf3;
      color: #111827;
    }
    button:disabled {
      opacity: .58;
      cursor: not-allowed;
    }
    .actions {
      display: flex;
      gap: 10px;
      align-items: center;
      margin-top: 16px;
      flex-wrap: wrap;
    }
    .hint, .meta {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
    }
    .job-type {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 10px;
      margin: 12px 0 2px;
    }
    .type-card {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      min-height: 124px;
      background: #fbfcfe;
    }
    .type-card.active {
      border-color: var(--accent);
      box-shadow: inset 0 0 0 1px var(--accent);
    }
    .type-card strong {
      display: block;
      font-size: 13px;
      margin-bottom: 4px;
    }
    .type-card code {
      display: inline-block;
      margin-bottom: 8px;
      color: #155e75;
      font-size: 12px;
    }
    .required {
      margin: 10px 0 0;
      padding: 0;
      list-style: none;
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
    }
    .required li {
      border: 1px solid #cbd5e1;
      border-radius: 999px;
      padding: 3px 8px;
      font-size: 12px;
      color: #334155;
      background: white;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }
    th, td {
      border-bottom: 1px solid var(--line);
      text-align: left;
      padding: 9px 8px;
      vertical-align: top;
    }
    th {
      color: var(--muted);
      font-weight: 700;
      background: #fbfcfe;
    }
    .status {
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 3px 8px;
      font-size: 12px;
      font-weight: 750;
      background: #eef2ff;
      color: #3730a3;
    }
    .status.done { background: #ecfdf3; color: var(--good); }
    .status.failed { background: #fff1f3; color: var(--bad); }
    .status.running { background: #fff7ed; color: var(--warn); }
    pre {
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      background: #101828;
      color: #e5e7eb;
      border-radius: 8px;
      padding: 12px;
      min-height: 150px;
      max-height: 360px;
      overflow: auto;
      font-size: 12px;
    }
    .split {
      display: grid;
      grid-template-columns: 1fr;
      gap: 16px;
    }
    .download-list {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 10px;
    }
    .download-list a {
      color: #075985;
      text-decoration: none;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 5px 9px;
      background: white;
      font-size: 12px;
    }
    @media (max-width: 860px) {
      .grid, .job-type, .file-row { grid-template-columns: 1fr; }
      header .wrap { align-items: flex-start; flex-direction: column; padding: 14px 0; }
    }
  </style>
</head>
<body>
<header>
  <div class="wrap">
    <h1>HE UC Credit Receiver</h1>
    <div class="meta" id="health">Checking server...</div>
  </div>
</header>
<main class="wrap">
  <div class="grid">
    <section>
      <h2>Create Job</h2>
      <label for="jobType">HE job type</label>
      <select id="jobType"></select>
      <div class="job-type" id="typeCards"></div>

      <label for="token">Bearer token</label>
      <input id="token" type="password" autocomplete="off" placeholder="Only needed when HE_RECEIVER_TOKEN is set">

      <label>Encrypted files</label>
      <div class="file-row">
        <input id="fileInput" type="file" multiple>
        <input id="dirInput" type="file" multiple webkitdirectory directory>
      </div>
      <p class="hint">Select context/eval-key/manifest files and the encrypted <code>columns/</code> directory. The browser sends encrypted artifacts only.</p>

      <label for="note">Client note</label>
      <textarea id="note" placeholder="Optional: dataset, row count, test label"></textarea>

      <div class="actions">
        <button id="submitBtn">Upload and Run</button>
        <button class="secondary" id="refreshBtn" type="button">Refresh Jobs</button>
        <span class="hint" id="uploadHint"></span>
      </div>
    </section>

    <div class="split">
      <section>
        <h2>Jobs</h2>
        <table>
          <thead>
            <tr><th>Job</th><th>Type</th><th>Status</th><th>Files</th></tr>
          </thead>
          <tbody id="jobsBody"></tbody>
        </table>
      </section>
      <section>
        <h2>Details</h2>
        <pre id="details">Select or submit a job.</pre>
        <div class="download-list" id="downloads"></div>
      </section>
    </div>
  </div>
</main>
<script>
const state = { jobTypes: {}, selectedJob: null };

function authHeaders() {
  const token = document.getElementById('token').value.trim();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function normalizePath(file) {
  const raw = file.webkitRelativePath || file.name;
  const parts = raw.split('/').filter(Boolean);
  for (const anchor of ['columns', 'vectors', 'score_features', 'masks', 'target']) {
    const idx = parts.indexOf(anchor);
    if (idx >= 0) return parts.slice(idx).join('/');
  }
  return parts[parts.length - 1] || file.name;
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const value = String(reader.result || '');
      resolve(value.includes(',') ? value.split(',', 2)[1] : value);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}), ...authHeaders() };
  const res = await fetch(path, { ...options, headers });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return res;
}

async function loadTypes() {
  const res = await api('/api/job-types');
  const data = await res.json();
  state.jobTypes = data.job_types;
  const select = document.getElementById('jobType');
  select.innerHTML = '';
  for (const [id, cfg] of Object.entries(state.jobTypes)) {
    const opt = document.createElement('option');
    opt.value = id;
    opt.textContent = cfg.label;
    opt.disabled = Boolean(cfg.disabled);
    select.appendChild(opt);
  }
  select.addEventListener('change', renderCards);
  renderCards();
}

function renderCards() {
  const selected = document.getElementById('jobType').value;
  const cards = document.getElementById('typeCards');
  cards.innerHTML = '';
  for (const [id, cfg] of Object.entries(state.jobTypes)) {
    const card = document.createElement('div');
    card.className = `type-card ${id === selected ? 'active' : ''}`;
    card.innerHTML = `
      <strong>${cfg.label}</strong>
      <code>${cfg.scheme}</code>
      <div class="hint">${cfg.description}</div>
      <ul class="required">${cfg.required.map(x => `<li>${x}</li>`).join('')}</ul>
    `;
    card.addEventListener('click', () => {
      if (cfg.disabled) return;
      document.getElementById('jobType').value = id;
      renderCards();
    });
    cards.appendChild(card);
  }
}

async function submitJob() {
  const submitBtn = document.getElementById('submitBtn');
  const hint = document.getElementById('uploadHint');
  submitBtn.disabled = true;
  hint.textContent = 'Reading encrypted files...';
  try {
    const files = [
      ...document.getElementById('fileInput').files,
      ...document.getElementById('dirInput').files,
    ];
    if (!files.length) throw new Error('Select at least one encrypted file or directory.');
    const payloadFiles = [];
    for (const file of files) {
      payloadFiles.push({
        path: normalizePath(file),
        size: file.size,
        content_base64: await fileToBase64(file),
      });
    }
    hint.textContent = 'Uploading job...';
    const res = await api('/api/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        job_type: document.getElementById('jobType').value,
        note: document.getElementById('note').value,
        files: payloadFiles,
      }),
    });
    const data = await res.json();
    state.selectedJob = data.job_id;
    hint.textContent = `Queued ${data.job_id}`;
    await refreshJobs();
    await showJob(data.job_id);
  } catch (err) {
    hint.textContent = String(err.message || err);
  } finally {
    submitBtn.disabled = false;
  }
}

async function refreshJobs() {
  const res = await api('/api/jobs');
  const data = await res.json();
  const body = document.getElementById('jobsBody');
  body.innerHTML = '';
  for (const job of data.jobs) {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><button class="secondary" data-job="${job.job_id}">${job.job_id}</button></td>
      <td>${job.job_type}</td>
      <td><span class="status ${job.status}">${job.status}</span></td>
      <td>${job.input_file_count || 0}</td>
    `;
    tr.querySelector('button').addEventListener('click', () => showJob(job.job_id));
    body.appendChild(tr);
  }
}

async function showJob(jobId) {
  state.selectedJob = jobId;
  const res = await api(`/api/jobs/${jobId}`);
  const data = await res.json();
  document.getElementById('details').textContent = JSON.stringify(data, null, 2);
  const downloads = document.getElementById('downloads');
  downloads.innerHTML = '';
  for (const item of data.output_files || []) {
    const a = document.createElement('a');
    a.href = `/api/jobs/${jobId}/download?path=${encodeURIComponent(item)}`;
    a.textContent = item;
    if (document.getElementById('token').value.trim()) {
      a.addEventListener('click', (event) => {
        event.preventDefault();
        downloadWithAuth(jobId, item);
      });
    }
    downloads.appendChild(a);
  }
}

async function downloadWithAuth(jobId, item) {
  const res = await api(`/api/jobs/${jobId}/download?path=${encodeURIComponent(item)}`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = item.split('/').pop();
  a.click();
  URL.revokeObjectURL(url);
}

async function health() {
  try {
    const res = await api('/api/health');
    const data = await res.json();
    document.getElementById('health').textContent = `workers ${data.max_workers}, jobs ${data.jobs_dir}`;
  } catch (err) {
    document.getElementById('health').textContent = String(err.message || err);
  }
}

document.getElementById('submitBtn').addEventListener('click', submitJob);
document.getElementById('refreshBtn').addEventListener('click', refreshJobs);
loadTypes().then(refreshJobs).then(health);
setInterval(refreshJobs, 4000);
setInterval(() => { if (state.selectedJob) showJob(state.selectedJob); }, 5000);
</script>
</body>
</html>
"""


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def response_json(handler: BaseHTTPRequestHandler, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
    data = json.dumps(payload, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def response_text(
    handler: BaseHTTPRequestHandler,
    text: str,
    status: HTTPStatus = HTTPStatus.OK,
    content_type: str = "text/plain; charset=utf-8",
) -> None:
    data = text.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def index_html() -> str:
    if STATIC_INDEX.exists():
        return STATIC_INDEX.read_text(encoding="utf-8")
    return INDEX_HTML


def clean_job_types() -> dict[str, Any]:
    return {
        key: {
            "label": value["label"],
            "family": value.get("family", ""),
            "stage": value.get("stage", ""),
            "scheme": value["scheme"],
            "description": value["description"],
            "required": value["required"],
            "client_requirements": value.get("client_requirements", []),
            "client_artifacts": value.get("client_artifacts", []),
            "server_returns": value.get("server_returns", []),
            "disabled": bool(value.get("disabled")),
        }
        for key, value in JOB_TYPES.items()
    }


def safe_relative_path(raw_path: str) -> Path:
    normalized = raw_path.replace("\\", "/").strip("/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe path: {raw_path}")
    lowered = normalized.lower()
    blocked = ["secret", "private", "raw", ".ssh", "id_rsa"]
    if any(token in lowered for token in blocked):
        raise ValueError(f"blocked sensitive-looking path: {raw_path}")
    return Path(*path.parts)


def read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    if length <= 0:
        raise ValueError("request body is empty")
    if length > MAX_UPLOAD_BYTES:
        raise ValueError(f"request exceeds HE_WEB_MAX_UPLOAD_BYTES={MAX_UPLOAD_BYTES}")
    body = handler.rfile.read(length)
    return json.loads(body.decode("utf-8"))


def status_path(job_dir: Path) -> Path:
    return job_dir / "status.json"


def write_status(job_dir: Path, update: dict[str, Any]) -> dict[str, Any]:
    with STATUS_LOCK:
        path = status_path(job_dir)
        current: dict[str, Any] = {}
        if path.exists():
            current = json.loads(path.read_text(encoding="utf-8"))
        current.update(update)
        current["updated_at"] = now_iso()
        path.write_text(json.dumps(current, indent=2), encoding="utf-8")
        return current


def read_status(job_dir: Path) -> dict[str, Any]:
    path = status_path(job_dir)
    if not path.exists():
        raise FileNotFoundError("job status not found")
    return json.loads(path.read_text(encoding="utf-8"))


def list_jobs(jobs_dir: Path) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    if not jobs_dir.exists():
        return jobs
    for path in sorted(jobs_dir.iterdir(), reverse=True):
        if path.is_dir() and status_path(path).exists():
            jobs.append(read_status(path))
    return jobs


def use_case_results(jobs_dir: Path) -> list[dict[str, Any]]:
    jobs = list_jobs(jobs_dir)
    grouped: dict[str, dict[str, Any]] = {}
    for job_type, cfg in JOB_TYPES.items():
        grouped[job_type] = {
            "job_type": job_type,
            "label": cfg["label"],
            "family": cfg.get("family", ""),
            "scheme": cfg.get("scheme", ""),
            "runnable": not bool(cfg.get("disabled")),
            "latest_job_id": "",
            "latest_status": "not_started",
            "latest_updated_at": "",
            "latest_output_files": [],
            "counts": {},
        }

    for job in jobs:
        job_type = str(job.get("job_type", ""))
        if job_type not in grouped:
            continue
        item = grouped[job_type]
        status = str(job.get("status", "unknown"))
        counts = item["counts"]
        counts[status] = counts.get(status, 0) + 1
        updated = str(job.get("updated_at", ""))
        if updated >= item["latest_updated_at"]:
            item["latest_job_id"] = job.get("job_id", "")
            item["latest_status"] = status
            item["latest_updated_at"] = updated
            item["latest_output_files"] = job.get("output_files", [])

    return list(grouped.values())


def list_output_files(job_dir: Path) -> list[str]:
    output = job_dir / "work" / "output"
    if not output.exists():
        return []
    files = []
    for path in sorted(output.rglob("*")):
        if path.is_file():
            files.append(path.relative_to(output).as_posix())
    return files


def create_result_bundle(job_dir: Path) -> bytes:
    status = read_status(job_dir)
    output_root = job_dir / "work" / "output"
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("job_status.json", json.dumps(status, indent=2))
        log_path = job_dir / "server_log.txt"
        if log_path.exists():
            bundle.write(log_path, "server_log.txt")
        if output_root.exists():
            for path in sorted(output_root.rglob("*")):
                if path.is_file():
                    bundle.write(path, path.relative_to(output_root).as_posix())
    return buffer.getvalue()


def validate_required_files(work_dir: Path, job_type: str) -> None:
    cfg = JOB_TYPES[job_type]
    missing: list[str] = []
    for item in cfg["required"]:
        if item.endswith("/"):
            if not (work_dir / item.rstrip("/")).is_dir():
                missing.append(item)
        elif not (work_dir / item).is_file():
            missing.append(item)
    if missing:
        raise ValueError(f"missing required encrypted artifacts: {', '.join(missing)}")


def build_command(build_dir: Path, work_dir: Path, job_type: str) -> list[str]:
    cfg = JOB_TYPES[job_type]
    binary = cfg.get("binary")
    if not binary:
        raise ValueError(f"job type is not runnable yet: {job_type}")
    executable = build_dir / binary
    if not executable.exists():
        raise FileNotFoundError(f"missing build executable: {executable}")

    command = [str(executable)]
    args = cfg["command"]
    for arg in args:
        if arg.startswith("--"):
            command.append(arg)
        elif arg.startswith("literal:"):
            command.append(arg.split(":", 1)[1])
        else:
            command.append(str(work_dir / arg))
    return command


def run_job(job_dir: Path, build_dir: Path) -> None:
    with WORKER_SEMAPHORE:
        try:
            status = read_status(job_dir)
            job_type = status["job_type"]
            work_dir = job_dir / "work"
            validate_required_files(work_dir, job_type)
            command = build_command(build_dir, work_dir, job_type)
            write_status(job_dir, {"status": "running", "started_at": now_iso(), "command": command})
            log_path = job_dir / "server_log.txt"
            with log_path.open("w", encoding="utf-8") as log:
                log.write("$ " + " ".join(command) + "\n\n")
                proc = subprocess.run(command, cwd=REPO_ROOT, text=True, stdout=log, stderr=subprocess.STDOUT)
            if proc.returncode == 0:
                write_status(
                    job_dir,
                    {
                        "status": "done",
                        "finished_at": now_iso(),
                        "returncode": proc.returncode,
                        "output_files": list_output_files(job_dir),
                    },
                )
            else:
                write_status(
                    job_dir,
                    {
                        "status": "failed",
                        "finished_at": now_iso(),
                        "returncode": proc.returncode,
                        "error": f"server binary exited with {proc.returncode}",
                    },
                )
        except Exception as exc:  # noqa: BLE001 - write failure into job status for UI
            write_status(job_dir, {"status": "failed", "finished_at": now_iso(), "error": str(exc)})


def create_job(jobs_dir: Path, build_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    job_type = str(payload.get("job_type", ""))
    if job_type not in JOB_TYPES:
        raise ValueError(f"unknown job_type: {job_type}")
    if JOB_TYPES[job_type].get("disabled"):
        raise ValueError(f"job_type is not runnable yet: {job_type}")
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("files must be a non-empty list")

    job_id = time.strftime("%Y%m%d-%H%M%S-", time.gmtime()) + uuid.uuid4().hex[:8]
    job_dir = jobs_dir / job_id
    work_dir = job_dir / "work"
    work_dir.mkdir(parents=True, exist_ok=False)

    saved = []
    total_bytes = 0
    for item in files:
        rel = safe_relative_path(str(item.get("path", "")))
        encoded = item.get("content_base64")
        if not isinstance(encoded, str):
            raise ValueError(f"missing content_base64 for {rel}")
        data = base64.b64decode(encoded, validate=True)
        total_bytes += len(data)
        dest = work_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        saved.append(rel.as_posix())

    status = {
        "job_id": job_id,
        "job_type": job_type,
        "label": JOB_TYPES[job_type]["label"],
        "scheme": JOB_TYPES[job_type]["scheme"],
        "status": "queued",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "note": str(payload.get("note", "")),
        "input_file_count": len(saved),
        "input_bytes": total_bytes,
        "input_files": saved,
        "output_files": [],
    }
    write_status(job_dir, status)
    thread = threading.Thread(target=run_job, args=(job_dir, build_dir), daemon=True)
    thread.start()
    return status


class HEJobHandler(BaseHTTPRequestHandler):
    jobs_dir = DEFAULT_JOBS_DIR
    build_dir = DEFAULT_BUILD_DIR

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def authorized(self) -> bool:
        if not AUTH_TOKEN:
            return True
        return self.headers.get("Authorization", "") == f"Bearer {AUTH_TOKEN}"

    def require_auth(self) -> bool:
        if self.authorized():
            return True
        response_json(self, {"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
        return False

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/":
                response_text(self, index_html(), content_type="text/html; charset=utf-8")
                return
            if parsed.path == "/api/health":
                response_json(
                    self,
                    {
                        "status": "ok",
                        "jobs_dir": str(self.jobs_dir),
                        "build_dir": str(self.build_dir),
                        "max_workers": MAX_WORKERS,
                        "auth_required": bool(AUTH_TOKEN),
                    },
                )
                return
            if parsed.path == "/api/job-types":
                response_json(self, {"job_types": clean_job_types()})
                return
            if parsed.path == "/api/jobs":
                if not self.require_auth():
                    return
                response_json(self, {"jobs": list_jobs(self.jobs_dir)})
                return
            if parsed.path == "/api/use-case-results":
                if not self.require_auth():
                    return
                response_json(self, {"use_cases": use_case_results(self.jobs_dir)})
                return
            if parsed.path.startswith("/api/jobs/"):
                if not self.require_auth():
                    return
                parts = parsed.path.strip("/").split("/")
                if len(parts) < 3:
                    raise ValueError("missing job_id")
                job_id = parts[2]
                job_dir = self.jobs_dir / job_id
                if not job_dir.is_dir():
                    response_json(self, {"error": "job not found"}, HTTPStatus.NOT_FOUND)
                    return
                if len(parts) == 3:
                    status = read_status(job_dir)
                    status["output_files"] = list_output_files(job_dir)
                    response_json(self, status)
                    return
                if len(parts) == 4 and parts[3] == "download":
                    query = parse_qs(parsed.query)
                    rel = safe_relative_path(query.get("path", [""])[0])
                    output_root = job_dir / "work" / "output"
                    target = (output_root / rel).resolve()
                    if output_root.resolve() not in target.parents or not target.is_file():
                        response_json(self, {"error": "output file not found"}, HTTPStatus.NOT_FOUND)
                        return
                    data = target.read_bytes()
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Content-Disposition", f'attachment; filename="{html.escape(target.name)}"')
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if len(parts) == 4 and parts[3] == "download-bundle":
                    data = create_result_bundle(job_dir)
                    filename = f"he_result_{job_id}.zip"
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/zip")
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Content-Disposition", f'attachment; filename="{html.escape(filename)}"')
                    self.end_headers()
                    self.wfile.write(data)
                    return
            response_json(self, {"error": "not found"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:  # noqa: BLE001 - API error response
            response_json(self, {"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        try:
            if not self.require_auth():
                return
            if parsed.path == "/api/jobs":
                payload = read_json_body(self)
                status = create_job(self.jobs_dir, self.build_dir, payload)
                response_json(self, status, HTTPStatus.ACCEPTED)
                return
            response_json(self, {"error": "not found"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:  # noqa: BLE001 - API error response
            response_json(self, {"error": str(exc)}, HTTPStatus.BAD_REQUEST)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the HE job web receiver.")
    parser.add_argument("--host", default=os.environ.get("HE_WEB_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("HE_WEB_PORT", "8080")))
    parser.add_argument("--jobs-dir", default=str(DEFAULT_JOBS_DIR))
    parser.add_argument("--build-dir", default=str(DEFAULT_BUILD_DIR))
    args = parser.parse_args()

    jobs_dir = Path(args.jobs_dir).resolve()
    build_dir = Path(args.build_dir).resolve()
    jobs_dir.mkdir(parents=True, exist_ok=True)
    HEJobHandler.jobs_dir = jobs_dir
    HEJobHandler.build_dir = build_dir

    server = ReusableThreadingHTTPServer((args.host, args.port), HEJobHandler)
    print(f"HE job web receiver listening on http://{args.host}:{args.port}")
    print(f"jobs_dir={jobs_dir}")
    print(f"build_dir={build_dir}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping receiver")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
