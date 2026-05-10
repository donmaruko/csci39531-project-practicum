import json
import os
import re
import sys

import requests

from config import SCRIPT_DIR, TICKETMASTER_KEY
from ticketmaster import _extract_event

if __name__ == "__main__":
    artist = " ".join(sys.argv[1:]).strip() if len(sys.argv) > 1 else input("Artist: ").strip()
    slug = re.sub(r'[^a-z0-9]+', '_', artist.lower()).strip('_')

    resp = requests.get(
        "https://app.ticketmaster.com/discovery/v2/events",
        params={
            "keyword": artist,
            "classificationName": "music",
            "size": 5,
            "apikey": TICKETMASTER_KEY,
        },
        timeout=10,
    )
    resp.raise_for_status()
    raw = resp.json()
    raw_events = raw.get("_embedded", {}).get("events", [])

    raw_file = os.path.join(SCRIPT_DIR, f"debug_raw_{slug}.json")
    with open(raw_file, "w") as f:
        json.dump(raw, f, indent=2)
    print(f"raw        -> {len(raw_events)} events -> {raw_file}")

    extracted = [_extract_event(ev) for ev in raw_events]

    extracted_file = os.path.join(SCRIPT_DIR, f"debug_extracted_{slug}.json")
    with open(extracted_file, "w") as f:
        json.dump(extracted, f, indent=2, default=str)
    print(f"extracted  -> {len(extracted)} events -> {extracted_file}")