// CleanRoom status screen — LilyGo T-Display-S3
//
// Polls the detector's /status endpoint and renders:
//   * all clean  -> green, a happy face, "ALL ROOMS TIDY", each room with a check
//   * any untidy -> red, a sad face, "ATTENTION NEEDED", the room + what to do
// A footer shows Ollama connection status and a live countdown to the next reading.
//
// Copy src/config.h.example to src/config.h before building.

#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <TFT_eSPI.h>

#include "config.h"

// The T-Display-S3 needs GPIO15 driven HIGH to power the LCD rail.
static const int PIN_POWER_ON = 15;

TFT_eSPI tft = TFT_eSPI();

static const uint16_t GREEN = 0x05A0;  // pleasant dark green
static const uint16_t RED   = 0xC000;  // strong red

// Remember the last thing drawn so we only repaint on change (avoids flicker).
static String lastRender = "<init>";

// Live state shown in the footer (redrawn every second without touching the body).
static uint16_t curBg = TFT_BLACK;   // current background colour, so the footer matches
static int secsToNext = -1;          // seconds until the next reading (-1 = unknown)
static bool checking = false;        // true while the detector is mid-reading
static bool ollamaOk = true;         // whether the local model is reachable
static unsigned long lastPollMs = 0;
static unsigned long lastTickMs = 0;

void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("WiFi connecting");
  while (WiFi.status() != WL_CONNECTED) {
    delay(400);
    Serial.print(".");
  }
  Serial.printf("\nWiFi connected: %s\n", WiFi.localIP().toString().c_str());
}

void drawCentered(const String &text, int y, uint8_t font, uint8_t datum = MC_DATUM) {
  tft.setTextDatum(datum);
  tft.drawString(text, tft.width() / 2, y, font);
}

// A mouth drawn as overlapping dots along an arc we compute ourselves, so it is
// always upright. happy = smile (U), !happy = frown (n).
void drawMouth(int cx, int mouthCy, int mr, bool happy, uint16_t color) {
  int start = happy ? 205 : 25;
  int end   = happy ? 335 : 155;
  for (int deg = start; deg <= end; deg += 4) {
    float a = deg * 0.01745329f;  // degrees -> radians
    int mx = cx + (int)(mr * cosf(a));
    int my = mouthCy - (int)(mr * sinf(a));
    tft.fillCircle(mx, my, 2, color);
  }
}

// A round outline face (white) with eyes and a smile or frown.
void drawFace(int cx, int cy, int r, bool happy, uint16_t color) {
  tft.drawCircle(cx, cy, r, color);
  tft.drawCircle(cx, cy, r - 1, color);  // 2px ring
  int eyeDx = r * 2 / 5;
  int eyeDy = r / 4;
  int eyeR = r / 8;
  if (eyeR < 2) eyeR = 2;
  tft.fillCircle(cx - eyeDx, cy - eyeDy, eyeR, color);
  tft.fillCircle(cx + eyeDx, cy - eyeDy, eyeR, color);
  int mr = r / 2;
  int mouthCy = happy ? (cy + r / 4) : (cy + r * 2 / 3);
  drawMouth(cx, mouthCy, mr, happy, color);
}

// A small checkmark whose vertical centre is `yc`.
void drawCheck(int x, int yc, uint16_t color) {
  tft.drawLine(x,     yc + 1, x + 4,  yc + 5, color);
  tft.drawLine(x,     yc + 2, x + 4,  yc + 6, color);
  tft.drawLine(x + 4, yc + 5, x + 11, yc - 4, color);
  tft.drawLine(x + 4, yc + 6, x + 11, yc - 3, color);
}

// Footer: Ollama status on the left, countdown / "Checking..." on the right.
// Redrawn every second to tick the countdown without disturbing the body.
void drawFooter() {
  int h = tft.height();
  int w = tft.width();
  tft.fillRect(0, h - 18, w, 18, curBg);
  tft.setTextColor(TFT_WHITE, curBg);

  tft.setTextDatum(BL_DATUM);
  tft.drawString(ollamaOk ? "Ollama Connected" : "Ollama Offline", 6, h - 3, 2);

  String right;
  if (checking) {
    right = "Checking...";
  } else if (secsToNext >= 0) {
    char b[16];
    snprintf(b, sizeof(b), "Next %d:%02d", secsToNext / 60, secsToNext % 60);
    right = b;
  }
  if (right.length()) {
    tft.setTextDatum(BR_DATUM);
    tft.drawString(right, w - 6, h - 3, 2);
  }
}

void renderClean(JsonArray rooms) {
  curBg = GREEN;
  tft.fillScreen(GREEN);
  drawFace(tft.width() / 2, 34, 22, true, TFT_WHITE);
  tft.setTextColor(TFT_WHITE, GREEN);
  drawCentered("ALL ROOMS TIDY", 72, 4);

  int n = rooms.size();
  uint8_t font = (n <= 2) ? 4 : 2;
  int fh = (font == 4) ? 26 : 16;
  int rowH = fh + 6;
  int y = 96;
  for (JsonObject room : rooms) {
    const char *name = room["name"] | "Room";
    int blockW = tft.textWidth(name, font) + 22;
    int x0 = (tft.width() - blockW) / 2;
    if (x0 < 6) x0 = 6;
    drawCheck(x0, y + fh / 2, TFT_GREEN);
    tft.setTextColor(TFT_WHITE, GREEN);
    tft.setTextDatum(TL_DATUM);
    tft.drawString(name, x0 + 22, y, font);
    y += rowH;
    if (y > tft.height() - 22) break;
  }
  drawFooter();
}

void renderUntidy(JsonArray rooms) {
  curBg = RED;
  tft.fillScreen(RED);
  drawFace(tft.width() / 2, 26, 18, false, TFT_WHITE);
  tft.setTextColor(TFT_WHITE, RED);
  drawCentered("ATTENTION NEEDED", 50, 2);

  // First untidy room gets the spotlight; count any others for a "+N more" line.
  JsonObject first;
  bool found = false;
  int extra = 0;
  for (JsonObject room : rooms) {
    if (room["tidy"] | true) continue;
    if (!found) {
      first = room;
      found = true;
    } else {
      extra++;
    }
  }
  if (!found) {
    drawFooter();
    return;
  }

  String name = String((const char *)(first["name"] | "Room"));
  name.toUpperCase();
  tft.setTextColor(TFT_WHITE, RED);
  drawCentered(name, 70, 4);

  int maxBullets = (extra > 0) ? 2 : 3;  // leave a line for "+N more" when needed
  int y = 94;
  int bullets = 0;
  for (JsonVariant a : first["actions"].as<JsonArray>()) {
    if (bullets >= maxBullets) break;
    int by = y + 7;
    tft.fillCircle(12, by, 2, TFT_WHITE);
    tft.setTextDatum(TL_DATUM);
    tft.setTextColor(TFT_WHITE, RED);
    tft.drawString(a.as<const char *>(), 22, by - 7, 2);
    y += 20;
    bullets++;
  }
  if (extra > 0) {
    char b[28];
    snprintf(b, sizeof(b), "+%d more room%s untidy", extra, extra > 1 ? "s" : "");
    tft.setTextColor(TFT_WHITE, RED);
    drawCentered(String(b), y + 4, 2);
  }
  drawFooter();
}

void renderError(const String &msg) {
  curBg = TFT_BLACK;
  tft.fillScreen(TFT_BLACK);
  tft.setTextColor(TFT_ORANGE, TFT_BLACK);
  drawCentered("No data", tft.height() / 2 - 16, 4);
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  drawCentered(msg, tft.height() / 2 + 14, 2);
}

// Signature of the displayed body, so we only repaint when it actually changes
// (the footer ticks separately every second).
String signatureOf(bool allClean, JsonArray rooms) {
  String s = allClean ? "clean:" : "untidy:";
  for (JsonObject r : rooms) {
    bool tidy = r["tidy"] | true;
    if (allClean) {
      s += r["name"].as<const char *>();
      s += ",";
    } else if (!tidy) {
      s += r["name"].as<const char *>();
      s += "[";
      for (JsonVariant a : r["actions"].as<JsonArray>()) {
        s += a.as<const char *>();
        s += ",";
      }
      s += "]";
    }
  }
  return s;
}

void poll() {
  if (WiFi.status() != WL_CONNECTED) {
    connectWifi();
  }

  HTTPClient http;
  http.setConnectTimeout(4000);
  http.setTimeout(6000);
  http.begin(STATUS_URL);
  int code = http.GET();

  if (code != 200) {
    String msg = "HTTP " + String(code);
    checking = false;
    secsToNext = -1;
    ollamaOk = false;
    if (lastRender != "err:" + msg) {
      renderError(msg);
      lastRender = "err:" + msg;
    }
    http.end();
    return;
  }

  String payload = http.getString();
  http.end();

  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, payload);
  if (err) {
    checking = false;
    secsToNext = -1;
    if (lastRender != "err:json") {
      renderError("bad JSON");
      lastRender = "err:json";
    }
    return;
  }

  bool allClean = doc["all_clean"] | false;
  JsonArray rooms = doc["rooms"].as<JsonArray>();
  // Resync footer state to the server's authoritative values on every poll.
  checking = doc["checking"] | false;
  secsToNext = doc["next_check_in"] | -1;
  ollamaOk = doc["ollama_ok"] | true;

  String sig = signatureOf(allClean, rooms);
  if (sig != lastRender) {  // only repaint the body when it changes
    lastRender = sig;
    if (allClean) {
      renderClean(rooms);
    } else {
      renderUntidy(rooms);
    }
  } else {
    drawFooter();  // body unchanged, but refresh footer (status may have changed)
  }
}

void setup() {
  Serial.begin(115200);

  pinMode(PIN_POWER_ON, OUTPUT);
  digitalWrite(PIN_POWER_ON, HIGH);

  tft.init();
  tft.setRotation(1);  // landscape, 320x170
  tft.fillScreen(TFT_BLACK);
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  drawCentered("CleanRoom", tft.height() / 2 - 14, 4);
  drawCentered("starting...", tft.height() / 2 + 12, 2);

  connectWifi();
}

void loop() {
  unsigned long now = millis();

  // Hit /status every POLL_INTERVAL_MS...
  if (lastPollMs == 0 || now - lastPollMs >= POLL_INTERVAL_MS) {
    poll();
    lastPollMs = now;
  }

  // ...but tick the footer countdown every second.
  if (now - lastTickMs >= 1000) {
    lastTickMs = now;
    if (!checking && secsToNext > 0) secsToNext--;
    drawFooter();
  }

  delay(40);
}
