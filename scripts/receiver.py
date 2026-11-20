"""A local stand-in for WhatsApp: prints whatever the function delivers.

Run it, then point the function at it with NOTIFY_URLS=json://localhost:9999/hook
Apprise posts {"version", "title", "message", "type"} as JSON.
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


class Hook(BaseHTTPRequestHandler):
    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        try:
            payload = json.loads(raw)
            print(f"\n=== received on {self.path}\n[{payload.get('type')}] {payload.get('title')}\n{payload.get('message')}", flush=True)
        except ValueError:
            print(f"\n=== received on {self.path} (not JSON): {raw[:200]!r}", flush=True)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9999
    print(f"receiver: listening on http://localhost:{port}/  (NOTIFY_URLS=json://localhost:{port}/hook)")
    HTTPServer(("127.0.0.1", port), Hook).serve_forever()
