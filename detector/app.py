"""CleanRoom detector service.

Runs the room monitor in a background thread and serves the current state over
HTTP so the LilyGo S3 screen can poll it.

Endpoints:
  GET /status   -> JSON state (consumed by the LilyGo firmware)
  GET /         -> tiny human-readable HTML preview (open in a browser to eyeball it)

Run (after `ollama pull qwen2.5vl:7b`):
  cd detector
  pip install -r requirements.txt
  python app.py
"""

from __future__ import annotations

import json
import os
import pathlib
import threading

import yaml
from dotenv import load_dotenv
from flask import Flask, Response

from detector import Monitor

HERE = pathlib.Path(__file__).parent


def load_config():
    with open(HERE / "config.yaml") as fh:
        return yaml.safe_load(fh)


def create_app(monitor: Monitor) -> Flask:
    app = Flask(__name__)

    @app.get("/status")
    def status():
        return Response(json.dumps(monitor.snapshot()), mimetype="application/json")

    @app.get("/")
    def index():
        snap = monitor.snapshot()
        color = "#1a7f37" if snap["all_clean"] else "#cf222e"
        if snap["all_clean"]:
            body = "<h1>:)</h1><p>All rooms clean</p>"
        else:
            rooms = "".join(f"<li>{r}</li>" for r in snap["untidy_rooms"])
            body = f"<h1>UNTIDY</h1><ul>{rooms}</ul>"
        def checks_html(r):
            if not r.get("checks"):
                return r["reason"]
            out = []
            for c in r["checks"]:
                mark = "✅" if c["pass"] else "❌"
                note = f" — {c['note']}" if c["note"] else ""
                out.append(f"{mark} {c['label']}{note}")
            return "<br>".join(out)

        rows = "".join(
            f"<tr><td>{r['name']}</td><td>{'tidy' if r['tidy'] else 'UNTIDY'}</td>"
            f"<td style='text-align:left'>{checks_html(r)}</td>"
            f"<td>{r['last_error'] or ''}</td></tr>"
            for r in snap["rooms"]
        )
        html = f"""<!doctype html><meta http-equiv="refresh" content="5">
<body style="background:{color};color:#fff;font-family:sans-serif;text-align:center">
{body}
<table style="margin:2em auto;color:#fff;border-collapse:collapse" border="1" cellpadding="6">
<tr><th>room</th><th>state</th><th>checks</th><th>error</th></tr>{rows}</table>
</body>"""
        return Response(html, mimetype="text/html")

    return app


def main():
    load_dotenv(HERE / ".env")
    # Local Ollama needs no key; only cloud backends do. Optional by design.
    api_key = os.environ.get("VISION_API_KEY")

    cfg = load_config()
    monitor = Monitor(cfg, api_key)

    worker = threading.Thread(target=monitor.run, daemon=True)
    worker.start()

    srv = cfg["server"]
    app = create_app(monitor)
    print(f"Serving status on http://{srv['host']}:{srv['port']}/status", flush=True)
    app.run(host=srv["host"], port=srv["port"], threaded=True)


if __name__ == "__main__":
    main()
