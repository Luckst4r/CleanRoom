# CleanRoom — notes for Claude

## What this is
A **fully local** room-tidiness monitor. Tapo cameras watch rooms; a vision model
running locally on the user's Mac mini (M4, 16 GB) decides if each room is tidy; a
LilyGo T-Display-S3 screen shows the result: **green + smiley when all clean, red +
the untidy room and what to pick up**. Nothing leaves the LAN — never introduce a
cloud API.

```
Tapo 2K cams --RTSP--> detector (Mac mini, Ollama qwen2.5vl:7b) --HTTP /status--> LilyGo S3
```

## Current state (LIVE on real hardware)
- **Deployed and running** on the user's Mac mini as a launchd service.
- **Three rooms**: `Child's Bedroom`, `Living Room`, `Butler Pantry`. Designed to
  scale (kitchen, closet next) by adding entries under `rooms:` in `detector/config.yaml`.
  Butler Pantry uses **absolute rules, no reference photo** (shoes off the tile floor,
  empty counter); the other two are reference-relative.
- Detection is **reference-relative**: each room has a `reference_<room>.jpg`
  baseline photo (gitignored) and most checklist rules mean "compared to the
  reference photo." This is what makes "acceptable state = tidy" work.
- **Scheduling** (`detector/schedule.py`): timezone-aware (America/Chicago) quiet
  hours (00:00–06:00, nothing checked) + per-room cadence (kid's room every 2 min
  during active windows, 15 min otherwise; living room every 2 min; butler pantry
  every 5 min). The loop is a
  due-based **round-robin** across rooms (one warm model = one inference at a time).

## Layout
- `detector/` — Python service.
  - `detector.py` — capture (`grab_frame`, RTSP or file), `VisionBackend`, debounced
    `RoomState`, `Monitor` (round-robin scheduler loop + `/status` snapshot).
  - `schedule.py` — quiet hours + per-room interval logic.
  - `app.py` — runs the Monitor thread + Flask `GET /status` (the screen polls this)
    and `/` HTML preview.
  - `check.py` — one-shot capture+assess for a room (`python check.py [--room N]
    [--source URL]`); prints per-item ✅/❌ and saves `last_frame.jpg`. **Primary
    tuning tool.**
  - `config.yaml` — rooms, per-item `checklist` ({label, rule}), schedules.
  - `.env` (gitignored) — per-room RTSP URLs: `CLEANROOM_RTSP_URL`,
    `CLEANROOM_RTSP_URL_LIVINGROOM`, etc. `config.yaml` `source:` reads `${VAR}`.
- `firmware/` — PlatformIO project for the LilyGo S3 (`src/main.cpp`). Polls
  `/status`; green/red, room + cleanup bullets, footer countdown showing which room
  is next / "Checking …" / "Sleeping until 6:00 AM". `src/config.h` (WiFi + Mac IP)
  is gitignored; `config.h.example` is the template.
- `scripts/preflight.sh` — environment check. `scripts/install-service.sh` — installs
  the launchd auto-start service.
- `docs/SETUP.md` — reference setup. `docs/DEPLOY.md` — step-by-step deploy runbook.

## Operating it (on the Mac)
- **Restart after any config change:** `launchctl kickstart -k gui/$(id -u)/com.cleanroom.detector`
- **Logs:** `~/CleanRoom/detector.log`  •  **Status:** `curl -s localhost:8080/status`
- **Tune detection:** edit a room's `checklist` rule in `config.yaml`, then
  `cd detector && source .venv/bin/activate && python check.py --room N` for instant
  feedback. Re-capture a baseline with `python check.py --room N && cp last_frame.jpg reference_<room>.jpg`.
- Flashing the LilyGo is done from the user's **laptop** (PlatformIO), not the Mac mini.

## Conventions
- **Push directly to `main`** (the user chose this; no PRs/branches). Author commits
  as `Claude <noreply@anthropic.com>`. Never push to another branch without asking.
- Keep it **local-only**. `VisionBackend` speaks to any OpenAI-compatible `base_url`,
  so swapping runtimes (Ollama ↔ MLX) is config, not code.
- **Never commit real credentials** (RTSP creds, WiFi) — they live in gitignored
  `.env` / `config.h`. Committed values stay placeholders.
- Do not put the model identifier or internal session detail in commits/PRs.

## Known model limits (don't over-promise)
The local 7B can't reliably read fine detail at distance: exact couch-pillow color
order and far/small objects (kitchen bar stools from the living-room cam) are out of
scope — relaxed or dropped on purpose. Presence/position changes vs the reference are
reliable.
