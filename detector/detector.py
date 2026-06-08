"""Room tidiness detection.

For each configured room this module grabs a still frame (from an RTSP camera or,
for testing, a local image file), asks a vision model whether the room meets its
tidiness criteria, and keeps a debounced "tidy / untidy" state.

The vision backend is intentionally isolated in `VisionBackend` so it can be
swapped (e.g. a local Ollama model -> a different runtime) without touching the rest.
"""

from __future__ import annotations

import base64
import collections
import datetime
import json
import re
import threading
import time
from dataclasses import dataclass, field

import cv2
import requests


# --------------------------------------------------------------------------- #
# Vision backend (local Ollama / any OpenAI-compatible endpoint)
# --------------------------------------------------------------------------- #

SYSTEM_INSTRUCTION = (
    "You are a tidiness inspector. You are shown one photo of a room and a set "
    "of criteria for what counts as untidy. Judge ONLY by what is clearly "
    "visible in the photo. Respond with a single JSON object and nothing else, "
    'in the form {"tidy": true|false, "reason": "<short explanation>", '
    '"items": ["<offending item>", ...]}. If the room is tidy, "items" is an '
    "empty list."
)


class VisionBackend:
    """Calls a local (or any OpenAI-compatible) vision model.

    Defaults target Ollama on the Mac mini so frames never leave the machine.
    `api_key` is optional — local Ollama ignores it.
    """

    def __init__(self, base_url, model, api_key=None, timeout=120, force_json=True):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.force_json = force_json

    def assess(self, jpeg_bytes, criteria):
        """Return (tidy: bool, reason: str, items: list[str]). Raises on failure."""
        data_uri = "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode()
        payload = {
            "model": self.model,
            "temperature": 0.1,
            "max_tokens": 300,
            "messages": [
                {"role": "system", "content": SYSTEM_INSTRUCTION},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Criteria:\n" + criteria},
                        {"type": "image_url", "image_url": {"url": data_uri}},
                    ],
                },
            ],
        }
        if self.force_json:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json"}
        if self.api_key:  # local Ollama needs no auth; cloud backends do
            headers["Authorization"] = f"Bearer {self.api_key}"
        resp = requests.post(self.url, json=payload, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return _parse_assessment(content)


def _parse_assessment(content):
    """Pull the JSON verdict out of the model's reply, defensively."""
    text = content.strip()
    # Models sometimes wrap JSON in ```json fences or add prose; grab the first {...}.
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"no JSON found in model reply: {content!r}")
    data = json.loads(match.group(0))
    tidy = bool(data.get("tidy"))
    reason = str(data.get("reason", "")).strip()
    items = [str(x) for x in data.get("items", []) if str(x).strip()]
    return tidy, reason, items


# --------------------------------------------------------------------------- #
# Frame capture
# --------------------------------------------------------------------------- #

def grab_frame(source, max_width, jpeg_quality):
    """Grab one frame from `source` and return JPEG bytes.

    `source` may be an RTSP/HTTP stream URL or a local image file path (handy for
    testing without a camera). Raises on failure.
    """
    if source.startswith(("rtsp://", "http://", "https://")):
        frame = _grab_stream_frame(source)
    else:
        frame = cv2.imread(source)
        if frame is None:
            raise RuntimeError(f"could not read image file: {source}")

    h, w = frame.shape[:2]
    if w > max_width:
        scale = max_width / w
        frame = cv2.resize(frame, (max_width, int(h * scale)), interpolation=cv2.INTER_AREA)

    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
    if not ok:
        raise RuntimeError("JPEG encode failed")
    return buf.tobytes()


def _grab_stream_frame(url):
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    try:
        if not cap.isOpened():
            raise RuntimeError(f"could not open stream: {_redact(url)}")
        # First frames after connecting can be stale/garbage; skip a few.
        frame = None
        for _ in range(5):
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError(f"could not read frame from: {_redact(url)}")
        return frame
    finally:
        cap.release()


def _redact(url):
    """Hide credentials when an RTSP URL appears in logs/errors."""
    return re.sub(r"//[^@/]*@", "//***@", url)


# --------------------------------------------------------------------------- #
# Per-room debounced state
# --------------------------------------------------------------------------- #

@dataclass
class RoomState:
    name: str
    source: str
    criteria: str
    debounce: int
    tidy: bool = True            # assume clean until proven otherwise
    reason: str = "not checked yet"
    items: list = field(default_factory=list)
    last_checked: str | None = None
    last_error: str | None = None
    _recent: collections.deque = field(default_factory=collections.deque, repr=False)

    def record(self, tidy, reason, items):
        self.last_checked = _now()
        self.last_error = None
        self._recent.append(tidy)
        while len(self._recent) > self.debounce:
            self._recent.popleft()
        # Only flip the confirmed state once the debounce window is unanimous.
        if len(self._recent) >= self.debounce and len(set(self._recent)) == 1:
            self.tidy = tidy
            self.reason = reason
            self.items = items

    def record_error(self, err):
        self.last_checked = _now()
        self.last_error = str(err)
        self._recent.clear()  # don't let a stale reading count toward a flip

    def public(self):
        return {
            "name": self.name,
            "tidy": self.tidy,
            "reason": self.reason,
            "items": self.items,
            "last_checked": self.last_checked,
            "last_error": self.last_error,
        }


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# Monitor: background loop + shared snapshot
# --------------------------------------------------------------------------- #

class Monitor:
    def __init__(self, cfg, api_key=None):
        v = cfg["vision"]
        self.backend = VisionBackend(
            v["base_url"],
            v["model"],
            api_key=api_key,
            timeout=v.get("timeout_seconds", 120),
            force_json=v.get("force_json", True),
        )
        self.max_width = v.get("max_image_width", 1024)
        self.jpeg_quality = v.get("jpeg_quality", 80)
        self.poll_interval = cfg.get("poll_interval_seconds", 60)
        debounce = cfg.get("debounce_readings", 2)
        self.rooms = [
            RoomState(
                name=r["name"], source=r["source"], criteria=r["criteria"], debounce=debounce
            )
            for r in cfg["rooms"]
        ]
        self._lock = threading.Lock()
        self._stop = threading.Event()

    def snapshot(self):
        """Thread-safe view of current state for the HTTP API."""
        with self._lock:
            rooms = [r.public() for r in self.rooms]
        untidy = [r["name"] for r in rooms if not r["tidy"]]
        return {
            "all_clean": len(untidy) == 0,
            "untidy_rooms": untidy,
            "rooms": rooms,
            "updated_at": _now(),
        }

    def check_room(self, room):
        try:
            jpeg = grab_frame(room.source, self.max_width, self.jpeg_quality)
            tidy, reason, items = self.backend.assess(jpeg, room.criteria)
            with self._lock:
                room.record(tidy, reason, items)
            verdict = "TIDY" if tidy else "UNTIDY"
            print(f"[{_now()}] {room.name}: {verdict} ({reason})", flush=True)
        except Exception as exc:  # keep prior state; never crash the loop
            with self._lock:
                room.record_error(exc)
            print(f"[{_now()}] {room.name}: ERROR {exc}", flush=True)

    def run(self):
        print(
            f"Monitor started: {len(self.rooms)} room(s), "
            f"every {self.poll_interval}s, model={self.backend.model}",
            flush=True,
        )
        while not self._stop.is_set():
            for room in self.rooms:
                if self._stop.is_set():
                    break
                self.check_room(room)
            self._stop.wait(self.poll_interval)

    def stop(self):
        self._stop.set()
