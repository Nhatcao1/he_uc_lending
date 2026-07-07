#!/usr/bin/env python3
"""Localhost client dashboard for pulling completed HE result bundles."""

from __future__ import annotations

import argparse
import html
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlparse

from download_job_bundle import (
    DECRYPT_CONFIG,
    download,
    download_json,
    infer_client_material,
    safe_extract,
    safe_job_id,
)


JOB_LABELS = {
    "home_credit_missing_data": "4.x Missing Data Checks",
    "home_credit_app_dist_amt_credit": "5.1 Distribution of AMT_CREDIT",
    "home_credit_app_dist_amt_income_total": "5.2 Distribution of AMT_INCOME_TOTAL",
    "home_credit_app_dist_amt_goods_price": "5.3 Distribution of AMT_GOODS_PRICE",
    "home_credit_app_suite_type": "5.4 Who Accompanied Client",
    "home_credit_app_target_balance": "5.5 Target Balance",
    "home_credit_app_loan_type": "5.6 Types of Loan",
    "home_credit_app_own_car_realty": "5.7 Own Car / Own Realty Flags",
    "home_credit_app_income_type": "5.8 Income Sources",
    "home_credit_app_family_status": "5.9 Family Status",
    "home_credit_app_occupation_type": "5.10 Occupation",
    "home_credit_app_education_type": "5.11 Education",
    "home_credit_app_housing_type": "5.12 Housing Type",
    "home_credit_app_organization_type": "5.13 Organization Type",
    "home_credit_app_target_by_income_type": "5.14.1 Income Type by Target",
    "home_credit_app_target_by_family_status": "5.14.2 Family Status by Target",
    "home_credit_app_target_by_occupation_type": "5.14.3 Occupation by Target",
    "home_credit_app_target_by_education_type": "5.14.4 Education by Target",
    "home_credit_app_target_by_housing_type": "5.14.5 Housing Type by Target",
    "home_credit_app_target_by_organization_type": "5.14.6 Organization Type by Target",
    "home_credit_app_target_by_suite_type": "5.14.7 Suite Type by Target",
    "home_credit_prev_contract_type": "5.15.1 Previous Contract Type",
    "home_credit_prev_weekday_process_start": "5.15.2 Previous Application Weekday",
    "home_credit_prev_cash_loan_purpose": "5.15.3 Previous Cash Loan Purpose",
    "home_credit_prev_contract_status": "5.15.4 Previous Contract Status",
    "home_credit_prev_payment_type": "5.15.5 Previous Payment Type",
    "home_credit_prev_reject_reason": "5.15.6 Previous Reject Reason",
    "home_credit_prev_suite_type": "5.15.7 Previous Suite Type",
    "home_credit_prev_client_type": "5.15.8 Previous Client Type",
    "home_credit_prev_goods_category": "5.15.9 Previous Goods Category",
    "home_credit_prev_portfolio": "5.15.10 Previous Portfolio",
    "home_credit_prev_product_type": "5.15.11 Previous Product Type",
    "home_credit_prev_channel_type": "5.15.12 Previous Channel Type",
    "home_credit_prev_seller_industry": "5.15.13 Previous Seller Industry",
    "home_credit_prev_yield_group": "5.15.14 Previous Yield Group",
    "home_credit_prev_product_combination": "5.15.15 Previous Product Combination",
    "home_credit_prev_insured_on_approval": "5.15.16 Previous Insured on Approval",
    "home_credit_app_selected_correlation_stats": "6 Pearson Correlation Support",
    "home_credit_linear_score_demo": "7 Linear Score Demo",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a local client-side HE result dashboard.")
    parser.add_argument("--server", default="http://100.84.97.118:8080", help="Remote HE server URL.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--token", default="", help="Bearer token when HE_RECEIVER_TOKEN is set.")
    parser.add_argument("--output-dir", default="client_runs/home_credit_basic/server_returns")
    parser.add_argument("--client-private-root", default="client_runs/home_credit_basic/client_private")
    parser.add_argument("--decrypt-bin", default="./build/decrypt_ckks_results")
    return parser.parse_args()


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def latest_by_job_type(server: str, token: str, limit: int = 500) -> dict[str, dict[str, object]]:
    data = download_json(f"{server.rstrip('/')}/api/results?{urlencode({'limit': limit})}", token)
    results = data.get("results")
    if not isinstance(results, list):
        raise ValueError("server /api/results returned no results list")
    grouped: dict[str, dict[str, object]] = {}
    for item in results:
        if not isinstance(item, dict):
            continue
        job_type = str(item.get("job_type") or "")
        if job_type and job_type not in grouped:
            grouped[job_type] = item
    return grouped


def decrypt_command_for(args: argparse.Namespace, job_dir: Path) -> str:
    status_path = job_dir / "job_status.json"
    if not status_path.exists():
        return "No job_status.json found; cannot infer decrypt command."
    status = json.loads(status_path.read_text(encoding="utf-8"))
    job_type = str(status.get("job_type") or "")
    cfg = DECRYPT_CONFIG.get(job_type)
    if cfg is None:
        return f"No decrypt template for job_type={job_type!r}"

    helper_args = SimpleNamespace(
        context="",
        secret_key="",
        client_private_root=args.client_private_root,
    )
    context, secret_key, material_source = infer_client_material(helper_args, job_dir)
    manifest = job_dir / cfg["manifest"]
    input_dir = job_dir / cfg["input_dir"]
    output_csv = job_dir / cfg["output_csv"]
    return (
        f"# key material: {material_source}\n"
        f"{args.decrypt_bin} \\\n"
        f"  --context {context} \\\n"
        f"  --secret-key {secret_key} \\\n"
        f"  --manifest {manifest} \\\n"
        f"  --input-dir {input_dir} \\\n"
        f"  --output-csv {output_csv} \\\n"
        f"  --manifest-type {cfg['manifest_type']}"
    )


def download_job(args: argparse.Namespace, job_id: str) -> tuple[Path, Path, str]:
    job_id = safe_job_id(job_id)
    output_root = Path(args.output_dir)
    job_dir = output_root / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    data = download(f"{args.server.rstrip('/')}/api/jobs/{job_id}/download-bundle", args.token)
    zip_path = job_dir / f"he_result_{job_id}.zip"
    zip_path.write_bytes(data)
    safe_extract(zip_path, job_dir)
    return zip_path, job_dir, decrypt_command_for(args, job_dir)


class ResultDashboardHandler(BaseHTTPRequestHandler):
    args: argparse.Namespace

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def send_html(self, body: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.end_headers()

    def page(self, content: str) -> str:
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>HE Client Results</title>
  <style>
    :root {{
      --bg: #f5f7fb;
      --panel: #ffffff;
      --ink: #182230;
      --muted: #667085;
      --line: #d5dde8;
      --accent: #117e73;
      --accent-dark: #0b6159;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--ink);
    }}
    header {{
      background: #101828;
      color: #fff;
      padding: 18px 28px;
    }}
    main {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 22px;
    }}
    section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
      margin-bottom: 16px;
    }}
    h1, h2, h3 {{ margin: 0; }}
    p {{ color: var(--muted); line-height: 1.5; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 10px 8px; text-align: left; vertical-align: top; }}
    th {{ color: var(--muted); background: #fbfcfe; }}
    code, pre {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 13px;
    }}
    pre {{
      white-space: pre-wrap;
      word-break: break-word;
      background: #111827;
      color: #e5e7eb;
      border-radius: 8px;
      padding: 12px;
    }}
    .button {{
      display: inline-block;
      border: 0;
      border-radius: 7px;
      padding: 8px 12px;
      background: #e8edf5;
      color: #111827;
      text-decoration: none;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
    }}
    .button.primary {{ background: var(--accent); color: #fff; }}
    .button.primary:hover {{ background: var(--accent-dark); }}
    .muted {{ color: var(--muted); }}
    .pill {{
      display: inline-block;
      border-radius: 999px;
      padding: 4px 8px;
      background: #e7f8f5;
      color: #0b6159;
      font-size: 12px;
      font-weight: 800;
    }}
    .actions {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
  </style>
</head>
<body>
  <header>
    <h1>Home Credit HE Client Results</h1>
    <p style="color:#d0d5dd; margin: 6px 0 0;">Local client view. It reads server results and stores encrypted notebook-EDA bundles on this machine.</p>
  </header>
  <main>{content}</main>
</body>
</html>"""

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/download":
            self.handle_download(parsed)
            return
        if parsed.path == "/download-all":
            self.handle_download_all()
            return
        if parsed.path != "/":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            grouped = latest_by_job_type(self.args.server, self.args.token)
            self.send_html(self.page(self.render_index(grouped)))
        except Exception as exc:  # noqa: BLE001 - visible local test UI
            self.send_html(self.page(f"<section><h2>Cannot read results</h2><pre>{esc(exc)}</pre></section>"), HTTPStatus.BAD_GATEWAY)

    def handle_download(self, parsed: object) -> None:
        query = parse_qs(parsed.query)
        job_id = (query.get("job_id") or [""])[0]
        if not job_id:
            self.send_html(self.page("<section><h2>Missing job_id</h2></section>"), HTTPStatus.BAD_REQUEST)
            return
        try:
            zip_path, job_dir, command = download_job(self.args, job_id)
            body = f"""
<section>
  <h2>Downloaded</h2>
  <p><span class="pill">{esc(job_id)}</span></p>
  <p>Bundle: <code>{esc(zip_path)}</code></p>
  <p>Extracted: <code>{esc(job_dir)}</code></p>
  <h3>Decrypt Command</h3>
  <pre>{esc(command)}</pre>
  <div class="actions"><a class="button primary" href="/">Back to results</a></div>
</section>
"""
            self.send_html(self.page(body))
        except Exception as exc:  # noqa: BLE001 - visible local test UI
            self.send_html(self.page(f"<section><h2>Download failed</h2><pre>{esc(exc)}</pre><a class=\"button\" href=\"/\">Back</a></section>"), HTTPStatus.BAD_GATEWAY)

    def handle_download_all(self) -> None:
        try:
            grouped = latest_by_job_type(self.args.server, self.args.token)
            blocks = []
            for job_type, label in JOB_LABELS.items():
                job = grouped.get(job_type)
                if not job:
                    blocks.append(f"<h3>{esc(label)}</h3><p class=\"muted\">No completed result.</p>")
                    continue
                job_id = str(job.get("job_id") or "")
                zip_path, job_dir, command = download_job(self.args, job_id)
                blocks.append(
                    f"<h3>{esc(label)}</h3>"
                    f"<p><span class=\"pill\">{esc(job_id)}</span></p>"
                    f"<p>Bundle: <code>{esc(zip_path)}</code></p>"
                    f"<p>Extracted: <code>{esc(job_dir)}</code></p>"
                    f"<pre>{esc(command)}</pre>"
                )
            body = f"""
<section>
  <h2>Downloaded Latest Results</h2>
  {"".join(blocks)}
  <div class="actions"><a class="button primary" href="/">Back to results</a></div>
</section>
"""
            self.send_html(self.page(body))
        except Exception as exc:  # noqa: BLE001 - visible local test UI
            self.send_html(self.page(f"<section><h2>Download-all failed</h2><pre>{esc(exc)}</pre><a class=\"button\" href=\"/\">Back</a></section>"), HTTPStatus.BAD_GATEWAY)

    def render_index(self, grouped: dict[str, dict[str, object]]) -> str:
        rows = []
        for job_type, label in JOB_LABELS.items():
            job = grouped.get(job_type)
            if not job:
                rows.append(
                    f"<tr><td>{esc(label)}</td><td class=\"muted\">No completed result</td><td></td><td></td><td></td></tr>"
                )
                continue
            job_id = str(job.get("job_id") or "")
            finished = str(job.get("finished_at") or "")
            runtime = str(job.get("runtime_duration") or "")
            output_bytes = str(job.get("output_bytes") or "")
            rows.append(
                "<tr>"
                f"<td><strong>{esc(label)}</strong><br><code>{esc(job_type)}</code></td>"
                f"<td><span class=\"pill\">{esc(job_id)}</span><br><span class=\"muted\">{esc(finished)}</span></td>"
                f"<td>{esc(runtime)}</td>"
                f"<td>{esc(output_bytes)}</td>"
                f"<td><a class=\"button primary\" href=\"/download?{urlencode({'job_id': job_id})}\">Pull bundle</a></td>"
                "</tr>"
            )
        return f"""
<section>
  <h2>Latest Result Per EDA Criterion</h2>
  <p>Server: <code>{esc(self.args.server)}</code></p>
  <p>Local output: <code>{esc(self.args.output_dir)}</code></p>
  <p><a class="button primary" href="/download-all">Pull all latest bundles</a></p>
  <table>
    <thead><tr><th>EDA criterion</th><th>Latest completed job</th><th>HE runtime</th><th>Output bytes</th><th>Action</th></tr></thead>
    <tbody>{"".join(rows)}</tbody>
  </table>
</section>
<section>
  <h2>Command Equivalent</h2>
  <pre>python3 code/client/home_credit/download_job_bundle.py \\
  --server {esc(self.args.server)} \\
  --job-id latest</pre>
</section>
"""


def main() -> None:
    args = parse_args()
    ResultDashboardHandler.args = args
    server = ThreadingHTTPServer((args.host, args.port), ResultDashboardHandler)
    print(f"Client result dashboard: http://{args.host}:{args.port}")
    print(f"Reading server results from: {args.server}")
    server.serve_forever()


if __name__ == "__main__":
    main()
