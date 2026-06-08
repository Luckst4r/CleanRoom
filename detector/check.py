"""One-shot capture + assessment — the deploy/tuning helper.

Grabs a single frame from a room's source (or one you pass on the command line),
saves it to last_frame.jpg so you can eyeball exactly what the model sees, then
runs ONE tidiness assessment and prints the verdict. No service, no loop.

Use it during setup to aim the camera and tune the criteria text:

  cd detector
  python check.py                          # uses room 0 from config.yaml
  python check.py --source samples/test.jpg   # try a local photo
  python check.py --source "rtsp://user:pass@192.168.1.50:554/stream2"
  python check.py --room 1                  # a different room in config.yaml
"""

from __future__ import annotations

import argparse
import os
import pathlib
import time

import yaml
from dotenv import load_dotenv

from detector import VisionBackend, grab_frame

HERE = pathlib.Path(__file__).parent
FRAME_OUT = HERE / "last_frame.jpg"


def main():
    ap = argparse.ArgumentParser(description="One-shot tidiness check.")
    ap.add_argument("--source", help="override the camera/image source")
    ap.add_argument("--room", type=int, default=0, help="room index in config.yaml (default 0)")
    args = ap.parse_args()

    load_dotenv(HERE / ".env")
    with open(HERE / "config.yaml") as fh:
        cfg = yaml.safe_load(fh)

    room = cfg["rooms"][args.room]
    source = args.source or room["source"]
    v = cfg["vision"]
    max_w = v.get("max_image_width", 1024)
    quality = v.get("jpeg_quality", 80)

    print(f"Room:   {room['name']}")
    print(f"Source: {_redact(source)}")
    print(f"Model:  {v['model']}  @ {v['base_url']}")
    print("-" * 60)

    # 1) Capture
    print("Grabbing a frame...")
    t0 = time.time()
    jpeg = grab_frame(source, max_w, quality)
    FRAME_OUT.write_bytes(jpeg)
    print(f"  saved {len(jpeg)//1024} KB to {FRAME_OUT}  ({time.time()-t0:.1f}s)")
    print("  -> open last_frame.jpg to confirm the camera is aimed well.")

    # Optional reference photo (room when tidy) for relative judgments.
    reference = None
    ref_path = room.get("reference_image")
    if ref_path:
        try:
            reference = grab_frame(ref_path, max_w, quality)
            print(f"  using reference image: {ref_path}")
        except Exception as exc:
            print(f"  WARNING: could not load reference image {ref_path}: {exc}")

    # 2) Assess
    print("\nAsking the vision model...")
    backend = VisionBackend(
        v["base_url"],
        v["model"],
        api_key=os.environ.get("VISION_API_KEY"),
        timeout=v.get("timeout_seconds", 120),
        force_json=v.get("force_json", True),
    )
    t0 = time.time()
    tidy, reason, items, checks = backend.assess(jpeg, room["checklist"], reference)
    dt = time.time() - t0

    print("-" * 60)
    for c in checks:
        mark = "✅" if c["pass"] else "❌"
        print(f"  {mark}  {c['label']}")
        if c["note"]:
            print(f"       └ {c['note']}")
    print("-" * 60)
    print(f"VERDICT: {'TIDY ✅' if tidy else 'UNTIDY ❌'}   ({dt:.1f}s)")
    if not tidy:
        print(f"failed:  {reason}")


def _redact(s):
    import re
    return re.sub(r"//[^@/]*@", "//***@", s)


if __name__ == "__main__":
    main()
