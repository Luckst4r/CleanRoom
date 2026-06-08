# CleanRoom — Deployment Runbook

> **This document is written for Claude (future me) to drive an end-to-end deploy
> on the user's Mac mini, with the user acting as my hands.** The user runs the
> commands I give and reports back. I do not have shell access to the Mac.

## How I should run this session

- **One step at a time.** Give the user a single, copy-pasteable command (or one
  physical action), say what output to expect, and wait. Do not dump a whole phase
  at once.
- **Gate on verification.** Each step has a ✅ check. Don't advance until it passes.
  If it fails, go to the step's **If it fails** notes before moving on.
- **Ask for outputs, not guesses.** When something looks off, have the user paste
  the actual command output or a photo of the screen.
- **Stay local.** Never introduce a cloud API. Detection runs on the Mac via Ollama.
- **Branch + PR as usual.** Any code/config changes go on the feature branch with a
  draft PR, then merge (the user has authorized auto-merge).

## Kickoff: collect this first

Before Phase 1, ask the user for these and record them in the chat:

```
[ ] macOS version (Apple menu → About This Mac)
[ ] Mac mini LAN IP            (System Settings → Network, or: ipconfig getifaddr en0)
[ ] WiFi SSID + password       (the network the LilyGo screen will join)
[ ] Tapo camera placed in the child's bedroom and powered on
[ ] Tapo "Camera Account" username + password  (set in step 2.1)
[ ] Tapo camera LAN IP                          (found in step 2.1)
[ ] LilyGo T-Display-S3 + a USB-C data cable
```

> Note: the Mac and the LilyGo must be on the **same network/subnet** so the screen
> can reach the detector. If the user runs a "guest" or IoT VLAN, flag it.

---

## Phase 0 — Get the code on the Mac

**0.1** Clone (or update) the repo and run preflight.

```bash
# pick a folder, e.g. ~/code
git clone https://github.com/Luckst4r/CleanRoom.git ~/CleanRoom 2>/dev/null || \
  (cd ~/CleanRoom && git pull)
cd ~/CleanRoom
bash scripts/preflight.sh
```

✅ Preflight prints the system info and a checklist. **Expect ✗ for things not yet
installed** — that's fine, the next phases install them. Note which are missing.

---

## Phase 1 — Local vision model (Ollama)

**1.1** Install Ollama if preflight flagged it missing: download from
<https://ollama.com> (or `brew install ollama`), then launch the Ollama app once so
the background server starts.

✅ `curl -fsS http://localhost:11434/api/tags` returns JSON (even if empty).
**If it fails:** the server isn't running — open the Ollama app, or run `ollama serve`
in a spare terminal.

**1.2** Pull the vision model (~6 GB, one-time).

```bash
ollama pull qwen2.5vl:7b
```

✅ Ends with `success`. **If too slow / low on disk:** fall back to `minicpm-v`
(smaller) and set `model: minicpm-v` in `detector/config.yaml`.

**1.3** Smoke-test the model with a text prompt.

```bash
ollama run qwen2.5vl:7b "reply with the single word: ready"
```

✅ It replies. The model and runtime work.

---

## Phase 2 — Camera (Tapo RTSP)

**2.1** In the **Tapo phone app**: open the child's-bedroom camera →
**Settings → Advanced Settings → Camera Account** → create a username + password.
This is the RTSP credential (separate from the TP-Link cloud login). While there,
note the camera's **IP** (Tapo app device info, or the router's client list) and set
a **static DHCP lease** for it on the router so the IP won't change.

Record: `CAM_IP`, `CAM_USER`, `CAM_PASS`.

**2.2** Verify the RTSP stream from the Mac (install ffmpeg first if needed:
`brew install ffmpeg`).

```bash
# grabs one still from the camera; lower-res substream is fine for this
ffmpeg -y -rtsp_transport tcp -i "rtsp://CAM_USER:CAM_PASS@CAM_IP:554/stream2" \
  -frames:v 1 /tmp/cam_test.jpg && open /tmp/cam_test.jpg
```

✅ `/tmp/cam_test.jpg` opens and shows the room. **If it fails:**
- auth error → re-check Camera Account user/pass (case-sensitive).
- timeout → wrong IP, camera on a different VLAN, or RTSP disabled. Confirm `CAM_IP`
  pings; confirm the camera is on the same subnet as the Mac.
- try `/stream1` (2K) instead of `/stream2`.

---

## Phase 3 — Detector service

**3.1** Install Python deps (use a venv).

```bash
cd ~/CleanRoom/detector
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

✅ Installs without error. **If `opencv` fails to import later:** ensure it's
`opencv-python-headless` from requirements (already pinned).

**3.2** Point the config at the real camera. Edit `detector/config.yaml`:
- set `rooms[0].source` to `rtsp://CAM_USER:CAM_PASS@CAM_IP:554/stream1`
- leave `vision.base_url`/`model` as the Ollama defaults.

(I'll make this edit on the branch and have the user `git pull`, OR walk them through
editing it locally — prefer the branch route so it's version-controlled. Credentials
in the URL are local-only and the file is on their machine; that's acceptable for a
home LAN, but do **not** commit real credentials — keep the committed value a
placeholder and have the user fill it in locally, which `.gitignore` does not cover,
so instead consider an env-substituted source if the user prefers.)

**3.3** One-shot sanity check BEFORE running the full service — first with a known
photo, then live.

```bash
# (optional) prove the pipeline end-to-end with a deliberately messy photo
python check.py --source samples/messy.jpg      # expect UNTIDY
python check.py --source samples/tidy.jpg        # expect TIDY

# now the live camera (uses rooms[0].source from config.yaml)
python check.py
open last_frame.jpg
```

✅ `last_frame.jpg` shows the room well-framed, and the printed VERDICT is sensible.
**This is the camera-aim + criteria-tuning loop:** if the framing is bad, have the
user physically reaim the camera and rerun. If the verdict is wrong, adjust
`rooms[0].criteria` wording in `config.yaml` and rerun `python check.py` until it's
reliable on both a messy and a tidy version of the real room.

**3.4** Run the service.

```bash
python app.py
```

✅ Logs `Serving status on http://0.0.0.0:8080/status` and, each cycle, a line like
`Child's Bedroom: TIDY (...)`.

**3.5** Verify from a browser/another device on the LAN:
- `http://MAC_IP:8080/` → green smiley or red page.
- `curl http://MAC_IP:8080/status` → the JSON.

✅ Both reachable from another device (proves the LilyGo will reach it too).
**If unreachable from another device but works on `localhost`:** macOS firewall is
blocking Python — System Settings → Network → Firewall → allow incoming for Python,
or temporarily disable to confirm.

---

## Phase 4 — The screen (LilyGo T-Display-S3)

**4.1** Install PlatformIO if needed: VS Code + the **PlatformIO IDE** extension, or
`pip3 install platformio` for the `pio` CLI.

**4.2** Create the firmware config (not committed):

```bash
cd ~/CleanRoom/firmware
cp src/config.h.example src/config.h
```
Edit `src/config.h`:
- `WIFI_SSID` / `WIFI_PASSWORD`
- `STATUS_URL` → `http://MAC_IP:8080/status`

**4.3** Plug the LilyGo into the Mac with a **data** USB-C cable, then build + flash:

```bash
pio run -t upload
```

✅ Ends with `SUCCESS`. **If upload fails / board not found:** hold the **BOOT**
button while plugging in (enters download mode), then retry. Confirm a data cable
(not charge-only). On the CLI you may need to accept the serial-port permission
prompt on macOS.

**4.4** Watch the screen and serial log:

```bash
pio device monitor
```

✅ Screen shows "CleanRoom starting…", connects to WiFi (IP printed in the log), then
switches to **green + smiley** or **red + room name**, matching `/status`.
**If the screen stays black:** re-run `pio run -t upload` (the firmware drives the
LCD power pin on boot, so black usually means the flash didn't take).
**If it shows "No data":** WiFi or `STATUS_URL` wrong — check SSID/pass and that the
Mac IP in `STATUS_URL` is current and reachable (Phase 3.5).

---

## Phase 5 — End-to-end acceptance test

With the detector running and the screen live, do the real-world loop:

1. Tidy the room → within ~1–2 cycles (≈ a couple minutes, given the 60s poll +
   2-reading debounce) the screen is **green + smiley**.
2. Drop a book on the floor (or clothes) → screen goes **red** and lists
   "Child's Bedroom".
3. Tidy it again → back to green.

✅ Transitions both ways are correct and reasonably prompt.
**Tuning knobs** (in `detector/config.yaml`): `poll_interval_seconds` (faster
reaction), `debounce_readings` (fewer = snappier, more = steadier), and the
`criteria` text (what counts as untidy). Re-run `python check.py` against the live
camera while tuning.

---

## Phase 6 — Keep it running

Make the detector survive logout/reboot with a `launchd` agent.

**6.1** I'll generate `~/Library/LaunchAgents/com.cleanroom.detector.plist` for the
user that runs `~/CleanRoom/detector/.venv/bin/python ~/CleanRoom/detector/app.py`,
with `KeepAlive` true and logs to `~/CleanRoom/detector.log`. Then:

```bash
launchctl load -w ~/Library/LaunchAgents/com.cleanroom.detector.plist
```

✅ `curl http://localhost:8080/status` works after a reboot, with no terminal open.
Also confirm the Ollama app is set to launch at login (so the model server is up).

**Done.** The system is deployed: camera → local model on the Mac → screen, all on
the LAN.

---

## Quick troubleshooting index

| Symptom | Likely cause / fix |
|---|---|
| `check.py`/service: can't open stream | wrong RTSP creds/IP, VLAN split, or RTSP off (Phase 2.2) |
| Verdict wrong/flaky | tune `criteria`; try a sharper model; raise `debounce_readings` |
| `/status` works locally, not from phone | macOS firewall blocking Python (Phase 3.5) |
| Screen "No data" | WiFi creds or `STATUS_URL`/Mac IP wrong (Phase 4.4) |
| Screen black | re-flash; bad/charge-only cable; BOOT-button download mode |
| Ollama errors / slow | server not running (`ollama serve`); model too big — use `minicpm-v` |
| Mac IP changed, screen stopped | set a static DHCP lease for the Mac; reflash `STATUS_URL` |
