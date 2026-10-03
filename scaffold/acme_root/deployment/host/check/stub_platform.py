"""The platform as far as a host's first start reads it, for check.sh alone.

It answers the health call with the clock, issues a credential to any
enrollment, takes heartbeats, hands out no work, and holds the control stream
open. Each call is printed, so the check reads what the host sent from inside
its unit. Standard library only: it runs on the host release's interpreter.
"""

import json
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST_ID = str(uuid.uuid4())
POOL_ID = str(uuid.uuid4())


class Platform(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.command} {self.path}", flush=True)

    def _answer(self, status: int, body: object) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._answer(200, {"status": "ok", "version": "check"})
        elif self.path.startswith("/v1/hosts/me/control"):
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            while True:
                self.wfile.write(b"\n")
                self.wfile.flush()
                time.sleep(5)
        else:
            self._answer(404, {"detail": "not here"})

    def do_POST(self) -> None:
        body = self._body()
        now = datetime.now(UTC)
        if self.path == "/v1/hosts/enrollments":
            print(f"enrolled {json.dumps(body.get('advertisement'))}", flush=True)
            self._answer(
                201,
                {
                    "credential_id": str(uuid.uuid4()),
                    "expires_at": (now + timedelta(days=1)).isoformat(),
                    "host_id": HOST_ID,
                    "pool_id": POOL_ID,
                    "token": "hcr_check",
                },
            )
        elif self.path == "/v1/hosts/me/heartbeats":
            self._answer(
                200,
                {
                    "advertisement": body.get("advertisement"),
                    "created_at": now.isoformat(),
                    "exec_version": body.get("exec_version"),
                    "id": HOST_ID,
                    "last_seen_at": now.isoformat(),
                    "name": "check",
                    "online": True,
                    "pool_id": POOL_ID,
                    "revoked_at": None,
                },
            )
        elif self.path == "/v1/hosts/me/claims":
            self._answer(200, {"item": None})
        else:
            self._answer(404, {"detail": "not here"})


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Platform).serve_forever()
