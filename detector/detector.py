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
import os
import re
import threading
import time
from dataclasses import dataclass, field

import cv2
import requests

from schedule import Scheduler


# --------------------------------------------------------------------------- #
# Vision backend (local Ollama / any OpenAI-compatible endpoint)
# --------------------------------------------------------------------------- #

# A small local model is far more reliable when it judges ONE concrete thing at a
# time than when asked a single fuzzy "is this tidy?". So we hand it a numbered
# checklist and make it report pass/fail per item. The room is tidy only if every
# item passes — and we learn exactly which item failed, which makes tuning easy.
SYSTEM_INSTRUCTION = (
    "You are a meticulous tidiness inspector. You are given a CURRENT photo of a "
    "room and a numbered checklist of tidiness rules.\n\n"
    "If a REFERENCE photo is also provided, it shows the room in a state the owner "
    "considers ACCEPTABLE and tidy. In that case, judge each checklist item "
    "RELATIVE to the reference: an item FAILS only when the CURRENT photo is "
    "clearly and noticeably WORSE than the reference for that item — for example "
    "new clothes/books/toys/items left out that were not there before, the bed "
    "much more disheveled than in the reference, or furniture clearly moved out of "
    "place. If the current photo looks about the same as, or tidier than, the "
    "reference for an item, that item PASSES. Ignore minor differences, lighting "
    "changes, camera noise, and small position shifts.\n\n"
    "If no reference photo is provided, judge each item against the checklist text "
    "directly.\n\n"
    "Evaluate EACH checklist item independently, judging ONLY what is clearly "
    "visible in the CURRENT photo. If an item genuinely cannot be seen, mark it "
    "pass=true (never guess a violation you cannot see). Keep each note short and "
    "concrete about what you actually observe.\n\n"
    "Respond with a single JSON object and nothing else, with one entry per "
    "checklist item, in order:\n"
    '{"checks":[{"id":1,"pass":true,"note":"..."},{"id":2,"pass":false,"note":"..."}]}'
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

    def assess(self, jpeg_bytes, checklist, reference_jpeg=None):
        """Evaluate a room against a checklist.

        `checklist` is a list of {"label": short, "rule": detailed} dicts. The model
        is shown the detailed rules; the short labels are what we surface (screen,
        failed-item lists). Returns
        (tidy: bool, reason: str, failed_labels: list[str], checks: list[dict]).
        `checks` is the per-item detail: {id, label, rule, pass, note}. Raises on failure.
        """
        numbered = "\n".join(f"{i}. {it['rule']}" for i, it in enumerate(checklist, 1))
        content = [{"type": "text", "text": "Checklist:\n" + numbered}]
        if reference_jpeg is not None:
            content.append({"type": "text", "text": "REFERENCE photo (room when tidy):"})
            content.append(_image_part(reference_jpeg))
        content.append({"type": "text", "text": "CURRENT photo (judge this one):"})
        content.append(_image_part(jpeg_bytes))

        payload = {
            "model": self.model,
            "temperature": 0.1,
            "max_tokens": 700,
            "messages": [
                {"role": "system", "content": SYSTEM_INSTRUCTION},
                {"role": "user", "content": content},
            ],
        }
        if self.force_json:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json"}
        if self.api_key:  # local Ollama needs no auth; cloud backends do
            headers["Authorization"] = f"Bearer {self.api_key}"
        resp = requests.post(self.url, json=payload, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        reply = resp.json()["choices"][0]["message"]["content"]
        return _parse_checks(reply, checklist)


def _image_part(jpeg_bytes):
    uri = "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode()
    return {"type": "image_url", "image_url": {"url": uri}}


def _parse_checks(content, checklist):
    """Turn the model's per-item JSON into a verdict, defensively.

    Conservative by design: an item the model failed to report on is treated as a
    pass, so missing output never raises a false 'untidy' alarm.
    """
    match = re.search(r"\{.*\}", content.strip(), re.DOTALL)
    if not match:
        raise ValueError(f"no JSON found in model reply: {content!r}")
    data = json.loads(match.group(0))

    # Index the reported checks by their 1-based id.
    reported = {}
    for c in data.get("checks", []):
        try:
            reported[int(c.get("id"))] = c
        except (TypeError, ValueError):
            continue

    checks, failed = [], []
    for i, item in enumerate(checklist, 1):
        c = reported.get(i, {})
        passed = bool(c.get("pass", True))  # unseen/unreported -> assume ok
        note = str(c.get("note", "")).strip()
        label = item["label"]
        checks.append({"id": i, "label": label, "rule": item["rule"], "pass": passed, "note": note})
        if not passed:
            failed.append(label)

    tidy = len(failed) == 0
    reason = "all checks passed" if tidy else "; ".join(failed)
    return tidy, reason, failed, checks


# --------------------------------------------------------------------------- #
# Frame capture
# --------------------------------------------------------------------------- #

def grab_frame(source, max_width, jpeg_quality):
    """Grab one frame from `source` and return JPEG bytes.

    `source` may be an RTSP/HTTP stream URL or a local image file path (handy for
    testing without a camera). `${VAR}` references are expanded from the environment
    (e.g. the default config reads the camera URL from CLEANROOM_RTSP_URL so the
    password never lives in a git-tracked file). Raises on failure.
    """
    source = os.path.expandvars(source)
    if not source or "${" in source:
        raise RuntimeError(
            f"camera source is not set/expanded: {source!r} — "
            "set CLEANROOM_RTSP_URL in detector/.env"
        )
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
    checklist: list
    debounce: int
    reference_jpeg: bytes | None = None  # photo of this room when tidy (optional)
    schedule: dict = field(default_factory=dict)  # per-room cadence config
    last_ts: float = 0.0                 # monotonic-ish wall time of last check attempt
    tidy: bool = True                    # assume clean until proven otherwise
    reason: str = "not checked yet"
    items: list = field(default_factory=list)   # failed checklist items
    checks: list = field(default_factory=list)  # per-item detail for tuning
    last_checked: str | None = None
    last_error: str | None = None
    _recent: collections.deque = field(default_factory=collections.deque, repr=False)

    def record(self, tidy, reason, items, checks):
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
            self.checks = checks

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
            "checks": self.checks,
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
        debounce = cfg.get("debounce_readings", 2)
        self.sched = Scheduler(cfg.get("schedule", {}))
        self.rooms = [
            RoomState(
                name=r["name"],
                source=r["source"],
                checklist=r["checklist"],
                debounce=debounce,
                reference_jpeg=self._load_reference(r.get("reference_image")),
                schedule=r.get("schedule", {}),
            )
            for r in cfg["rooms"]
        ]
        self._lock = threading.Lock()
        self._stop = threading.Event()
        # Scheduling state surfaced to the screen so it can show what's happening.
        self.checking = False
        self.checking_room = None    # room being read right now
        self.next_room = None        # room that will be read next
        self.next_check_at = time.time()
        self.quiet = False           # true during quiet hours (no checks)
        self.resume_str = None       # when quiet hours end, e.g. "6:00 AM"

    def _load_reference(self, path):
        """Pre-load a room's 'tidy' reference photo, if configured."""
        if not path:
            return None
        try:
            ref = grab_frame(path, self.max_width, self.jpeg_quality)
            print(f"Loaded reference image: {path}", flush=True)
            return ref
        except Exception as exc:
            print(f"WARNING: could not load reference image {path}: {exc}", flush=True)
            return None

    def snapshot(self):
        """Thread-safe view of current state for the HTTP API."""
        with self._lock:
            rooms = [r.public() for r in self.rooms]
            checking = self.checking
            checking_room = self.checking_room
            next_room = self.next_room
            next_at = self.next_check_at
            quiet = self.quiet
            resume = self.resume_str
        untidy = [r["name"] for r in rooms if not r["tidy"]]
        next_in = 0 if checking else max(0, int(round(next_at - time.time())))
        return {
            "all_clean": len(untidy) == 0,
            "untidy_rooms": untidy,
            "rooms": rooms,
            "checking": checking,            # true while a reading is in progress
            "checking_room": checking_room,  # which room is being read
            "next_room": next_room,          # which room is up next
            "next_check_in": next_in,        # seconds until the next reading starts
            "quiet": quiet,                  # true during quiet hours
            "resume_time": resume,           # when quiet hours end (e.g. "6:00 AM")
            "updated_at": _now(),
        }

    def check_room(self, room):
        try:
            jpeg = grab_frame(room.source, self.max_width, self.jpeg_quality)
            tidy, reason, items, checks = self.backend.assess(
                jpeg, room.checklist, room.reference_jpeg
            )
            with self._lock:
                room.record(tidy, reason, items, checks)
            verdict = "TIDY" if tidy else "UNTIDY"
            print(f"[{_now()}] {room.name}: {verdict} ({reason})", flush=True)
        except Exception as exc:  # keep prior state; never crash the loop
            with self._lock:
                room.record_error(exc)
            print(f"[{_now()}] {room.name}: ERROR {exc}", flush=True)

    def run(self):
        print(
            f"Monitor started: {len(self.rooms)} room(s), model={self.backend.model}",
            flush=True,
        )
        while not self._stop.is_set():
            now_local = self.sched.now()

            # Quiet hours: don't check anything; tell the screen when we resume.
            if self.sched.is_quiet(now_local):
                with self._lock:
                    self.checking = False
                    self.checking_room = None
                    self.next_room = None
                    self.quiet = True
                    self.resume_str = self.sched.quiet_resume_str(now_local)
                self._stop.wait(20)  # re-evaluate periodically
                continue

            # Round-robin by due time: pick the room whose next check is soonest.
            now = time.time()
            due_room, due_at = None, None
            for room in self.rooms:
                interval = self.sched.room_interval(room.schedule, now_local)
                at = room.last_ts + interval
                if due_at is None or at < due_at:
                    due_room, due_at = room, at

            with self._lock:
                self.quiet = False
                self.resume_str = None

            if due_room is not None and due_at <= now:
                with self._lock:
                    self.checking = True
                    self.checking_room = due_room.name
                self.check_room(due_room)
                due_room.last_ts = time.time()
                with self._lock:
                    self.checking = False
                    self.checking_room = None
            else:
                # Nothing due yet — advertise the next room and wait until it's due
                # (capped, so window/interval changes are picked up promptly).
                with self._lock:
                    self.next_room = due_room.name if due_room else None
                    self.next_check_at = due_at if due_at else now
                self._stop.wait(min(max(due_at - now, 0.5), 15) if due_at else 15)

    def stop(self):
        self._stop.set()
