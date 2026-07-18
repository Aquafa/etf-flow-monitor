"""Tiny one-shot receiver: accepts a POST body and writes it to data/stocks.json.
Used only for manually seeding data from a browser session. Not part of deployment.
"""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "stocks.json"


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n)
        json.loads(body)  # validate
        OUT.write_bytes(body)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")
        print(f"saved {n} bytes -> {OUT}")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST")
        self.send_header("Access-Control-Allow-Headers", "content-type")
        self.end_headers()

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 8899), H).serve_forever()
