# CleanRoom

A local room-tidiness monitor. A camera watches a room; a vision model decides
whether the room is tidy; a small screen shows the result at a glance — **green
with a smiley when clean, red with the room name when untidy**.

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
                     └── sends a frame to Venice.ai vision model: "is this room tidy?"
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
(Tapo RTSP, running the detector, flashing the screen).

Quick version:

```bash
# Detector (on the Mac mini)
cd detector
cp .env.example .env          # add your VENICE_API_KEY
pip install -r requirements.txt
python app.py                 # serves http://<mac-ip>:8080/status

# Screen (flash the LilyGo)
cd firmware
cp src/config.h.example src/config.h   # add WiFi + the Mac's IP
pio run -t upload
```

## A note on privacy

The detector currently sends camera frames to **Venice.ai** (a cloud service) for
analysis, so frames of the child's bedroom leave your network. The vision backend
is isolated in `detector/detector.py` (`VisionBackend`) so it can be swapped for a
fully local model later without changing anything else.
