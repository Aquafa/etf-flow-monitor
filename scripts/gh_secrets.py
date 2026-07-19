"""Set non-credential Actions secrets (email addresses) for the report workflow.

Only writes SMTP_USER / MAIL_TO (the user's email address). The actual Gmail
app password is never handled here — the user manages it in the GitHub UI.
"""
import base64
import sys

from gh_deploy import get_token, api, OWNER, REPO
from nacl import encoding, public

EMAIL = "igolla99@gmail.com"


def main():
    token = get_token()
    _, key = api(token, "GET", f"/repos/{OWNER}/{REPO}/actions/secrets/public-key", None)
    pk = public.PublicKey(key["key"].encode(), encoding.Base64Encoder())
    for name in ("SMTP_USER", "MAIL_TO"):
        sealed = public.SealedBox(pk).encrypt(EMAIL.encode())
        status, _ = api(token, "PUT", f"/repos/{OWNER}/{REPO}/actions/secrets/{name}",
                        {"encrypted_value": base64.b64encode(sealed).decode(),
                         "key_id": key["key_id"]})
        print(name, "->", status)


if __name__ == "__main__":
    main()
