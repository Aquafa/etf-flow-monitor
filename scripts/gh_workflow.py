"""Trigger the update-data workflow and report its latest run status."""
import sys
import time
from gh_deploy import get_token, api, OWNER, REPO

WF = "update-data.yml"


def main():
    token = get_token()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run":
        status, body = api(token, "POST",
                           f"/repos/{OWNER}/{REPO}/actions/workflows/{WF}/dispatches",
                           {"ref": "main"})
        print("dispatch:", status, body.get("message", "ok"))
    status, body = api(token, "GET",
                       f"/repos/{OWNER}/{REPO}/actions/runs?per_page=3", None)
    for r in body.get("workflow_runs", []):
        print(r["run_number"], r["status"], r.get("conclusion"), r["created_at"])


if __name__ == "__main__":
    main()
