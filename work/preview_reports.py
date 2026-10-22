"""Local preview exposing only generated, public simulation reports."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {
    "/advanced.html": ROOT / "outputs/simulator_results_advanced/report.html",
    "/original.html": ROOT / "outputs/simulator_results_original/report.html",
    "/bonus.html": ROOT / "outputs/simulator_results_bonus/report.html",
    "/edge.html": ROOT / "work/report_edge/report.html",
}

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = ALLOWED.get(urlsplit(self.path).path)
        if path is None or not path.is_file():
            self.send_error(404)
            return
        payload = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)
    def log_message(self, *_):
        pass

if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 4187), Handler).serve_forever()
