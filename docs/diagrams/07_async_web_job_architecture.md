# Async Web Job Architecture

![Async web job architecture](07_async_web_job_architecture.svg)

```mermaid
flowchart LR
  browser["Browser\nsubmit + monitor + download"]
  nginx["Nginx\noptional public/Tailscale proxy"]
  web["FastAPI web/API\nupload, pages, metadata"]
  db["SQLite job DB\nstatus + paths + logs pointer"]
  queue["Redis/RQ queue\npending HE jobs"]
  worker["RQ worker\none HE job at a time"]
  cpp["C++ OpenFHE binaries\nnumeric, aggregate, score"]
  storage["server_jobs volume\nencrypted input/output bundles"]

  browser --> nginx --> web
  browser --> web
  web --> db
  web --> queue
  web --> storage
  queue --> worker
  worker --> db
  worker --> storage
  worker --> cpp
  cpp --> storage
  web --> browser
```

Purpose:

```text
Make slow HE jobs asynchronous: submit now, monitor status/logs, download the
encrypted result bundle later.
```

Trust boundary:

```text
Server stores encrypted artifacts, public/eval keys, job metadata, and logs.
Server still must not receive raw CSV, plaintext prepared vectors, secret key,
or decrypted reports.
```
