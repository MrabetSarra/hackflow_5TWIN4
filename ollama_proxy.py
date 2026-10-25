
import json
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

TOKEN = os.environ.get("OLLAMA_PROXY_TOKEN", "")
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"


class ProxyHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/api/chat":
            self.send_error(404)
            return

        supplied_token = self.headers.get("Authorization", "")
        if not TOKEN or supplied_token != f"Bearer {TOKEN}":
            self.send_error(401, "Unauthorized")
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 2_000_000:
                self.send_error(400, "Invalid request size")
                return

            body = self.rfile.read(length)
            json.loads(body)

            request = urllib.request.Request(
                OLLAMA_URL,
                data=body,
                method="POST",
                headers={"Content-Type": "application/json"},
            )

            with urllib.request.urlopen(request, timeout=240) as response:
                result = response.read()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(result)))
            self.end_headers()
            self.wfile.write(result)

        except urllib.error.HTTPError as error:
            self.send_error(error.code, "Ollama request failed")
        except Exception:
            self.send_error(502, "Ollama is unavailable")

    def log_message(self, format, *args):
        print("Proxy request:", args[0])


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("Set OLLAMA_PROXY_TOKEN before starting the proxy")

    server = HTTPServer(("0.0.0.0", 8001), ProxyHandler)
    print("Secure Ollama proxy listening on port 8001")
    server.serve_forever()
