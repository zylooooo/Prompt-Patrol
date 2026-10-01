"""Detector stand-in for the e2e stack: every answer scores 0.99, nothing to load.

Must keep the request/response shapes of the real detector in step with
apps/detector/app/routes.py (/score) and apps/detector/app/main.py (/health),
as consumed by apps/api/app/services/detector_client.py.
"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def _reply(self, status: int, body: dict) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._reply(200, {"status": "ready", "model_version": "stub"})
        else:
            self._reply(404, {"detail": "Not Found"})

    def do_POST(self) -> None:
        if self.path != "/score":
            self._reply(404, {"detail": "Not Found"})
            return
        json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        self._reply(200, {"raw_score": 0.99, "truncated": False})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8001), Handler).serve_forever()
