# CleanRoom

A fully local room-tidiness monitor. A camera watches a room; a vision model
running on the Mac mini decides whether the room is tidy; a small screen shows
the result at a glance — **green with a smiley when clean, red with the room name
when untidy**. Nothing leaves your network.

This first version watches **one room (a child's bedroom)**. It's built so more
rooms can be added later by appending to `detector/config.yaml`.

## Hardware

| Part | Role |
|------|------|
| Mac mini M4 | runs the detector service |
| Tapo 2K camera | watches the room over RTSP |
| LilyGo T-Display-S3 | shows the green/red status |

## How it works

```
Tapo cam ──RTSP──> detector (Mac mini) ──HTTP /status──> LilyGo screen
                     │
                     └── sends a frame to a LOCAL vision model (Ollama): "is this room tidy?"
```

- **`detector/`** — Python service. Every 60s it grabs a frame, asks the vision
  model whether the room meets its tidiness criteria, debounces the result, and
  serves the state at `GET /status`.
- **`firmware/`** — PlatformIO project for the LilyGo S3. Polls `/status` and
  renders the screen.

"Untidy" for the child's bedroom is defined in `detector/config.yaml` as: a book
on the floor, a book left out on a surface, or clothes on the floor. Tune that
text to taste.

## Setup

See **[docs/SETUP.md](docs/SETUP.md)** for full step-by-step instructions
(Tapo RTSP, running the detector, flashing the screen). For a guided end-to-end
deploy on the Mac mini, see **[docs/DEPLOY.md](docs/DEPLOY.md)**.

Quick version:

```bash
# One-time: install Ollama (https://ollama.com) and pull a vision model
ollama pull qwen2.5vl:7b

# Detector (on the Mac mini)
cd detector
pip install -r requirements.txt
python app.py                 # serves http://<mac-ip>:8080/status

# Screen (flash the LilyGo)
cd firmware
cp src/config.h.example src/config.h   # add WiFi + the Mac's IP
pio run -t upload
```

## Privacy

Everything runs on your LAN: the camera, the Mac mini (which runs the vision model
locally via Ollama), and the screen. Camera frames are never sent to any cloud
service. The vision backend is isolated in `detector/detector.py` (`VisionBackend`)
and talks to any OpenAI-compatible endpoint, so you can point it at a different
local runtime (e.g. MLX) by editing `base_url`/`model` in `config.yaml`.
