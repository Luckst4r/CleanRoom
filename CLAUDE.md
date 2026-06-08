# CleanRoom — notes for Claude

## What this is
A **fully local** room-tidiness monitor. A Tapo camera watches a room; a vision
model running locally on the user's Mac mini (M4, 16 GB) decides if the room is
tidy; a LilyGo T-Display-S3 screen shows the result: **green + smiley when clean,
red + room name(s) when untidy**. Nothing leaves the LAN — do not introduce any
cloud API.

```
Tapo 2K cam --RTSP--> detector (Mac mini, Ollama vision model) --HTTP /status--> LilyGo S3
```

## Current state
- Scope: **one room (Child's Bedroom)**. Designed to scale to 4 (child's room,
  closet, living room, kitchen) by adding entries under `rooms:` in
  `detector/config.yaml`.
- Detection: local **Ollama** (`qwen2.5vl:7b`) via its OpenAI-compatible endpoint.
- Built and merged but **not yet verified on real hardware** — cameras arrive, then
  we deploy.

## Layout
- `detector/` — Python service. `detector.py` (capture + `VisionBackend` + debounced
  state), `app.py` (background loop + Flask `/status` and `/` preview),
  `check.py` (one-shot capture+assess helper for setup/tuning), `config.yaml`.
- `firmware/` — PlatformIO project for the LilyGo S3 (`src/main.cpp`). Polls
  `/status`, renders red/green. `src/config.h` (WiFi + Mac IP) is gitignored;
  `config.h.example` is the template.
- `scripts/preflight.sh` — checks the Mac has the needed tooling.
- `docs/SETUP.md` — reference setup. `docs/DEPLOY.md` — see below.

## ➜ Deploying to the Mac mini?
**Follow `docs/DEPLOY.md`.** It's the runbook for guiding the user through an
end-to-end deploy step by step (the user is my hands; I have no shell on the Mac).
Start with its "Kickoff: collect this first" checklist, then go one gated step at a
time.

## Conventions
- Develop on a feature branch; open a **draft PR**, then **merge** (the user has
  authorized auto-merge). Squash-merge.
- Keep it **local-only**. The vision backend is intentionally isolated in
  `VisionBackend` and speaks to any OpenAI-compatible `base_url`, so swapping local
  runtimes (Ollama ↔ MLX) is a config change, not a code change.
- **Never commit real credentials** (RTSP URL with password, WiFi). Keep committed
  values as placeholders; the user fills them in locally.
- Do not put the model identifier or any internal session detail in commits/PRs.
