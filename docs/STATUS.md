# CleanRoom — current status (handoff)

Snapshot for picking the project up in a new session (e.g. Cowork on the Mac mini).
See `CLAUDE.md` for architecture and conventions.

## Live right now
- Two rooms monitored: **Child's Bedroom**, **Living Room**. The detector runs as a
  launchd service on the Mac mini; the LilyGo screen shows status + a per-room
  countdown ("Next: <room> M:SS" / "Checking <room>…") and "Sleeping until 6:00 AM"
  overnight.
- **Scheduler**: quiet 00:00–06:00 Central (nothing checked); kid's room every 2 min
  during Mon–Fri 7–10am & 3–8pm and Sat–Sun 7am–8pm, else every 15 min; living room
  every 2 min. Round-robin across rooms (one warm model at a time).
- Detection is **reference-relative** against `reference_<room>.jpg` baselines
  (gitignored, captured via `check.py`).

## Hardware / network (credentials are in `detector/.env`, NOT here)
- Mac mini serves `:8080`; user account `atlas`; repo at `~/CleanRoom`.
- Two Tapo cameras on the LAN (RTSP `/stream1`); URLs are in `.env` as
  `CLEANROOM_RTSP_URL` (kid) and `CLEANROOM_RTSP_URL_LIVINGROOM`.
- LilyGo is flashed from the user's **MacBook** (PlatformIO in `~/pio-venv`), not the
  Mac mini.

## Recently changed — verify on next run
- Removed Child's Bedroom **Desk chair** check (false positives).
- **Books left out** made reference-relative + conservative (was false-positiving on
  the desk) — confirm it stopped.
- Art-supplies broadened to **Desk clutter** (pencils/pens/loose papers/art supplies,
  reference-relative) — confirm it catches a stray pencil/paper and passes when clear.
- Scheduler + room-aware footer shipped; the **laptop may still need a reflash** to
  show the new footer.

## Pending / next
- **Mockup-style screen UI** is on branch **`ui-mockup-wip`** (white outline faces,
  "ALL ROOMS TIDY" + per-room checklist on the clean screen, "ATTENTION NEEDED" +
  action-phrased bullets when untidy, Ollama-status + countdown footer). It is **stale
  vs `main`** (predates the scheduler and the room-aware footer) and was untested —
  prefer rebuilding fresh on current `main` over cherry-picking. Detector bits in that
  branch worth reusing: `ollama_ok` in `/status`, per-item `action` phrases, and the
  split camera-vs-model error handling in `check_room`.
- **Kitchen** camera + room — will cover the bar stools up close (dropped from the
  Living Room because too far for the cam).
- **Closet** camera + room.
- Off-peak kid's-room rate is **15 min** (a default I chose) — confirm or adjust.

## Known model limits (don't over-promise)
`qwen2.5vl:7b` can't read fine detail at distance — exact couch-pillow color order and
far/small objects (kitchen bar stools from the living-room cam) are out of scope and
were relaxed/dropped on purpose. Presence/position changes vs the reference are solid.

## Operating cheatsheet
- Restart after a config change: `launchctl kickstart -k gui/$(id -u)/com.cleanroom.detector`
- Logs: `~/CleanRoom/detector.log`  ·  Status: `curl -s localhost:8080/status`
- Tune a room: `cd detector && source .venv/bin/activate && python check.py --room N`
- Re-capture a baseline: `python check.py --room N && cp last_frame.jpg reference_<room>.jpg`
