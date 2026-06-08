# CleanRoom setup

Three things to set up: the **camera**, the **detector** (on the Mac mini), and
the **screen** (LilyGo S3).

---

## 1. Tapo camera (RTSP)

1. In the **Tapo app**, open the camera → **Settings → Advanced Settings →
   Camera Account**. Create a username and password. This is *separate* from your
   TP-Link/cloud login — it's the RTSP credential.
2. Find the camera's IP (Tapo app, or your router). Give it a **static DHCP
   lease** on your router so the IP doesn't change.
3. Your RTSP URL is:
   ```
   rtsp://USERNAME:PASSWORD@CAMERA_IP:554/stream1
   ```
   - `stream1` = full 2K, `stream2` = lower resolution (either is fine).
4. Quick sanity check from the Mac (optional):
   ```bash
   ffplay "rtsp://USERNAME:PASSWORD@CAMERA_IP:554/stream2"
   ```

Put that URL into `detector/config.yaml` under `rooms[0].source`.

---

## 2. Detector (Mac mini M4)

First, the **local** vision model via [Ollama](https://ollama.com):

```bash
# install Ollama (download the macOS app or `brew install ollama`), then:
ollama pull qwen2.5vl:7b   # ~6 GB; fits comfortably in 16 GB alongside the OS
```

Ollama then serves an OpenAI-compatible API at `http://localhost:11434/v1`, which
is what `detector/config.yaml` points at by default. No API key, no cloud — frames
stay on the Mac.

> Model choice: `qwen2.5vl:7b` is a good default for 16 GB. Alternatives:
> `minicpm-v` (smaller/faster) or `llama3.2-vision` (larger, slower on 16 GB).
> Swap the `model:` value in `config.yaml` to try another — run `ollama list` to
> see what you've pulled.

Then the detector itself:

```bash
cd detector
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python app.py
```

You should see it serving on `http://0.0.0.0:8080`. Check it:

- Open `http://<mac-ip>:8080/` in a browser for a live preview page.
- `curl http://<mac-ip>:8080/status` returns the JSON the screen consumes.

### Testing without the camera

Set `source` in `config.yaml` to a local image path instead of an RTSP URL, e.g.
drop a photo at `detector/samples/childs_bedroom.jpg` and set
`source: "samples/childs_bedroom.jpg"`. Try a messy photo and a tidy one to
confirm the verdicts make sense, then point it back at the camera.

### Tuning

Detection uses a per-item **checklist** per room: the model judges each item
separately and the room is untidy if any item fails. `python check.py` prints a
✅/❌ line per item — that's the fastest way to tune.

- **What counts as untidy** — edit the `rooms[0].checklist` items in `config.yaml`
  (one clear, observable condition per line that should be TRUE when tidy).
- **Relative items** (furniture position/orientation, arrangement) — set
  `rooms[0].reference_image` to a photo of the room when tidy; the model compares
  against it. Capture one with `python check.py && cp last_frame.jpg reference.jpg`.
- **When/how often it checks** — see the global `schedule` (timezone + quiet
  hours, when no room is checked) and each room's `schedule` (`default_interval_seconds`,
  optional `peak_interval_seconds` with `weekday_windows`/`weekend_windows`). Rooms
  are checked round-robin by their own cadence.
- **Flicker** — `debounce_readings` (default 2: two identical readings in a row
  before the state flips).
- **Model** — `vision.model`. List what you've pulled with `ollama list`, or
  browse more vision models at https://ollama.com/search?c=vision.

### Run it on boot (optional)

Once you're happy, keep it running with a `launchd` plist or a `tmux`/`screen`
session so it survives logout.

---

## 3. Screen (LilyGo T-Display-S3)

Uses [PlatformIO](https://platformio.org/) (VS Code extension or the `pio` CLI).

```bash
cd firmware
cp src/config.h.example src/config.h
# edit src/config.h:
#   WIFI_SSID / WIFI_PASSWORD
#   STATUS_URL  ->  http://<mac-ip>:8080/status
```

Plug the LilyGo into the Mac over USB-C, then:

```bash
pio run -t upload      # build + flash
pio device monitor     # watch logs (115200 baud)
```

On boot it shows "CleanRoom starting…", connects to WiFi, then switches to
**green + smiley** (clean) or **red + room name** (untidy) and updates every few
seconds.

### If the screen stays black
- The T-Display-S3 needs GPIO15 held HIGH for LCD power — the firmware does this
  in `setup()`, so a black screen usually means the upload didn't take. Re-run
  `pio run -t upload`.
- If the panel colors look inverted/odd, the `build_flags` in `platformio.ini`
  are the LilyGo-recommended values; make sure you didn't override `User_Setup`.

---

## Data shape (`/status`)

```json
{
  "all_clean": false,
  "untidy_rooms": ["Child's Bedroom"],
  "rooms": [
    {
      "name": "Child's Bedroom",
      "tidy": false,
      "reason": "Items on floor; Books left out",
      "items": ["Items on floor", "Books left out"],
      "checks": [
        {"id": 1, "label": "Items on floor", "rule": "Nothing is left lying on the floor ...", "pass": false, "note": "a book is on the floor"},
        {"id": 2, "label": "Bed not made", "rule": "Compared to the reference photo ...", "pass": true, "note": "bedding roughly in place"}
      ],
      "last_checked": "2026-06-08T10:00:00",
      "last_error": null
    }
  ],
  "checking": false,            // true while a reading is in progress
  "checking_room": null,        // which room is being read right now
  "next_room": "Child's Bedroom", // which room is up next
  "next_check_in": 90,          // seconds until the next reading (screen counts this down)
  "quiet": false,               // true during quiet hours (no checks)
  "resume_time": null,          // when quiet hours end, e.g. "6:00 AM"
  "updated_at": "2026-06-08T10:00:05"
}
```

Adding more rooms later is just more entries under `rooms:` in `config.yaml`; the
screen already renders a list of untidy room names.
