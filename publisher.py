#!/usr/bin/env python3
"""
Solar Machine — Instagram Auto Publisher
Publishes one carousel post per day via Meta Graph API.
Reads state.json to know which post is next, updates it after publishing.
"""

import json
import os
import sys
import time
import requests
from requests.exceptions import HTTPError

# ── Retry logic for transient Meta API errors ────────────────────────────────
MAX_RETRIES = 4
RETRY_DELAYS = [5, 15, 30, 60]

def api_post(url, params, timeout=30):
    """POST to Meta Graph API with automatic retry on 5xx errors."""
    for attempt, delay in enumerate(RETRY_DELAYS, start=1):
        resp = requests.post(url, params=params, timeout=timeout)
        if resp.status_code < 500:
            return resp
        log(f"  ⚠ Meta API {resp.status_code} (attempt {attempt}/{MAX_RETRIES}) — retrying in {delay}s...")
        time.sleep(delay)
    resp.raise_for_status()
    return resp

# ── Config from environment ──────────────────────────────────────────────────
IG_USER_ID   = os.environ["IG_USER_ID"]
ACCESS_TOKEN = os.environ["IG_ACCESS_TOKEN"]
REPO         = os.environ["GITHUB_REPOSITORY"]  # e.g. ymtmidiasdigitais/solar-machine
BRANCH       = os.environ.get("GITHUB_REF_NAME", "main")
BASE_URL     = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}"
GRAPH_URL    = "https://graph.facebook.com/v21.0"

def log(msg):
    print(f"[publisher] {msg}", flush=True)

# ── Load posts manifest ───────────────────────────────────────────────────────
with open("posts.json", encoding="utf-8") as f:
    posts = json.load(f)

# ── Load state ────────────────────────────────────────────────────────────────
STATE_FILE = "state.json"
if os.path.exists(STATE_FILE):
    with open(STATE_FILE, encoding="utf-8") as f:
        state = json.load(f)
else:
    state = {"next_index": 0}

next_index = state["next_index"]

if next_index >= len(posts):
    log("All posts have been published. Nothing to do.")
    sys.exit(0)

post = posts[next_index]
is_carousel = len(post["cards"]) > 1
log(f"Publishing post {next_index + 1}/{len(posts)}: {post['id']} ({'carousel' if is_carousel else 'single image'})")

if is_carousel:
    # ── Carousel flow (2+ cards) ─────────────────────────────────────────────

    # Step 1: Create media containers for each card
    container_ids = []
    for card_path in post["cards"]:
        image_url = f"{BASE_URL}/{card_path}"
        log(f"  Creating container for {card_path}")
        resp = api_post(
            f"{GRAPH_URL}/{IG_USER_ID}/media",
            params={
                "image_url": image_url,
                "is_carousel_item": "true",
                "access_token": ACCESS_TOKEN,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        if "id" not in data:
            log(f"ERROR creating container: {data}")
            sys.exit(1)
        container_ids.append(data["id"])
        log(f"    Container ID: {data['id']}")
        time.sleep(1)  # avoid rate limiting

    # Step 2: Create carousel container
    log("Creating carousel container...")
    resp = api_post(
        f"{GRAPH_URL}/{IG_USER_ID}/media",
        params={
            "media_type": "CAROUSEL",
            "children": ",".join(container_ids),
            "caption": post["caption"],
            "access_token": ACCESS_TOKEN,
        },
    )
    resp.raise_for_status()
    data = resp.json()
    if "id" not in data:
        log(f"ERROR creating carousel: {data}")
        sys.exit(1)
    creation_id = data["id"]
    log(f"Carousel container ID: {creation_id}")

else:
    # ── Single image flow (1 card) ────────────────────────────────────────────
    image_url = f"{BASE_URL}/{post['cards'][0]}"
    log(f"  Creating image container for {post['cards'][0]}")
    resp = api_post(
        f"{GRAPH_URL}/{IG_USER_ID}/media",
        params={
            "image_url": image_url,
            "caption": post["caption"],
            "access_token": ACCESS_TOKEN,
        },
    )
    resp.raise_for_status()
    data = resp.json()
    if "id" not in data:
        log(f"ERROR creating image container: {data}")
        sys.exit(1)
    creation_id = data["id"]
    log(f"Image container ID: {creation_id}")

# ── Wait for container to be ready ───────────────────────────────────────────
log("Waiting for media to be ready...")
time.sleep(5)

# ── Publish ───────────────────────────────────────────────────────────────────
log("Publishing...")
resp = api_post(
    f"{GRAPH_URL}/{IG_USER_ID}/media_publish",
    params={
        "creation_id": creation_id,
        "access_token": ACCESS_TOKEN,
    },
)
resp.raise_for_status()
data = resp.json()
if "id" not in data:
    log(f"ERROR publishing: {data}")
    sys.exit(1)

log(f"✅ Published! Post ID: {data['id']}")

# ── Step 5: Update state ──────────────────────────────────────────────────────
state["next_index"] = next_index + 1
with open(STATE_FILE, "w", encoding="utf-8") as f:
    json.dump(state, f, indent=2)
log(f"State updated: next post will be index {state['next_index']}")
