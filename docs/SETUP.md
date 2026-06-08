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

```bash
cd detector
cp .env.example .env
# edit .env and set VENICE_API_KEY=...  (get a key at https://venice.ai/settings/api)

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

- **What counts as untidy** — edit `rooms[0].criteria` in `config.yaml`.
- **How fast it reacts** — `poll_interval_seconds` (default 60) and
  `debounce_readings` (default 2: two identical readings in a row before the
  state flips, which prevents flicker).
- **Model** — `venice.model`. List current options:
  ```bash
  curl -H "Authorization: Bearer $VENICE_API_KEY" https://api.venice.ai/api/v1/models
  ```

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
      "reason": "a book is on the floor",
      "items": ["book on floor"],
      "last_checked": "2026-06-08T10:00:00",
      "last_error": null
    }
  ],
  "updated_at": "2026-06-08T10:00:05"
}
```

Adding more rooms later is just more entries under `rooms:` in `config.yaml`; the
screen already renders a list of untidy room names.
