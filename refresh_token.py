#!/usr/bin/env python3
"""
Refreshes the Instagram long-lived access token and updates the GitHub secret.
Runs weekly. Long-lived tokens last 60 days; refreshing weekly keeps it alive indefinitely.
"""

import base64
import json
import os
import urllib.request
import urllib.error

APP_ID       = os.environ["IG_APP_ID"]
APP_SECRET   = os.environ["IG_APP_SECRET"]
ACCESS_TOKEN = os.environ["IG_ACCESS_TOKEN"]
GH_PAT       = os.environ["GH_PAT"]
REPO         = os.environ["GITHUB_REPOSITORY"]

def log(msg):
    print(f"[refresh_token] {msg}", flush=True)

# ── Step 1: Get new long-lived token from Meta ────────────────────────────────
url = (
    f"https://graph.facebook.com/v21.0/oauth/access_token"
    f"?grant_type=fb_exchange_token"
    f"&client_id={APP_ID}"
    f"&client_secret={APP_SECRET}"
    f"&fb_exchange_token={ACCESS_TOKEN}"
)
req = urllib.request.Request(url)
try:
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
except urllib.error.HTTPError as e:
    log(f"ERROR calling Meta API: {e.code} {e.read().decode()}")
    raise

new_token = data.get("access_token")
if not new_token:
    raise ValueError(f"No access_token in response: {data}")

log(f"New token obtained (expires_in: {data.get('expires_in', '?')} seconds)")

# ── Step 2: Get repo public key for secret encryption ────────────────────────
def gh_api(method, path, payload=None):
    url = f"https://api.github.com{path}"
    body = json.dumps(payload).encode() if payload else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", f"token {GH_PAT}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read()) if r.status != 204 else {}

pk_data = gh_api("GET", f"/repos/{REPO}/actions/secrets/public-key")
pub_key_b64 = pk_data["key"]
key_id      = pk_data["key_id"]

# ── Step 3: Encrypt and update GitHub secret ─────────────────────────────────
try:
    from nacl import encoding, public as nacl_public
    pk = nacl_public.PublicKey(pub_key_b64.encode(), encoding.Base64Encoder())
    box = nacl_public.SealedBox(pk)
    encrypted = base64.b64encode(box.encrypt(new_token.encode())).decode()
except ImportError:
    raise RuntimeError("PyNaCl not installed — add 'pip install PyNaCl' to workflow")

gh_api("PUT", f"/repos/{REPO}/actions/secrets/IG_ACCESS_TOKEN", {
    "encrypted_value": encrypted,
    "key_id": key_id,
})

log("✅ GitHub secret IG_ACCESS_TOKEN updated successfully.")
