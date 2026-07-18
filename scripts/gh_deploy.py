"""One-time deploy helper: create the GitHub repo and enable Pages via API.

Reads the GitHub token from the local git credential helper (Windows
Credential Manager); the token is never printed.
"""
import json
import subprocess
import urllib.request
import urllib.error

OWNER = "Aquafa"
REPO = "etf-flow-monitor"


def get_token():
    out = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        capture_output=True, text=True, check=True,
    ).stdout
    for line in out.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1]
    raise RuntimeError("no token from credential helper")


def api(token, method, path, payload=None):
    req = urllib.request.Request(
        "https://api.github.com" + path,
        method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={
            "Authorization": "token " + token,
            "Accept": "application/vnd.github+json",
            "User-Agent": REPO,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def main():
    token = get_token()
    status, body = api(token, "POST", "/user/repos", {
        "name": REPO,
        "description": "ETF 資金流向監測：BTC/ETH 加密 ETF + 各國股市 ETF + 風險警示",
        "homepage": f"https://{OWNER.lower()}.github.io/{REPO}/",
        "has_issues": False,
        "has_wiki": False,
    })
    print("create repo:", status, body.get("full_name") or body.get("message"))

    status, body = api(token, "POST", f"/repos/{OWNER}/{REPO}/pages",
                       {"source": {"branch": "main", "path": "/"}})
    print("enable pages:", status, body.get("message", "ok"))


if __name__ == "__main__":
    main()
