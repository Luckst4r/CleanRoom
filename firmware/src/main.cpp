// CleanRoom status screen — LilyGo T-Display-S3
//
// Polls the detector's /status endpoint and renders:
//   * all clean  -> green background + smiley face
//   * any untidy -> red background + the names of the untidy rooms
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

// Live countdown + state shown in the bottom strip.
static uint16_t curBg = TFT_BLACK;   // current background colour, so the strip matches
static int secsToNext = -1;          // seconds until the next reading (-1 = unknown)
static bool checking = false;        // true while the detector is mid-reading
static bool quiet = false;           // true during quiet hours (no checks)
static char checkingRoom[28] = "";   // room being read right now
static char nextRoom[28] = "";       // room up next
static char resumeTime[12] = "";     // when quiet hours end, e.g. "6:00 AM"
static unsigned long lastPollMs = 0; // when we last hit /status
static unsigned long lastTickMs = 0; // when we last ticked the countdown

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

void drawSmiley() {
  int cx = tft.width() / 2;
  int cy = tft.height() / 2 - 12;   // shifted up to leave room for the countdown strip
  int r = 52;
  tft.fillCircle(cx, cy, r, TFT_YELLOW);
  tft.drawCircle(cx, cy, r, TFT_BLACK);
  tft.drawCircle(cx, cy, r - 1, TFT_BLACK);
  // eyes
  tft.fillCircle(cx - 18, cy - 14, 6, TFT_BLACK);
  tft.fillCircle(cx + 18, cy - 14, 6, TFT_BLACK);
  // smile: bottom arc plotted from our own math (deg 210..330, 270 = straight down),
  // drawn as overlapping dots so the mouth is always upright and the right way up.
  int mr = 28;
  for (int deg = 210; deg <= 330; deg += 4) {
    float a = deg * 0.01745329f;  // degrees -> radians
    int mx = cx + (int)(mr * cosf(a));
    int my = cy - (int)(mr * sinf(a));
    tft.fillCircle(mx, my, 3, TFT_BLACK);
  }
}

// The bottom strip: redrawn every second to tick the countdown without disturbing
// the face above it.
void drawCountdown() {
  int h = tft.height();
  tft.fillRect(0, h - 22, tft.width(), 22, curBg);  // clear strip in the current bg colour
  tft.setTextColor(TFT_WHITE, curBg);
  char buf[44];
  if (quiet) {
    if (resumeTime[0]) snprintf(buf, sizeof(buf), "Sleeping until %s", resumeTime);
    else               snprintf(buf, sizeof(buf), "Sleeping");
    drawCentered(String(buf), h - 13, 2);
  } else if (checking) {
    if (checkingRoom[0]) snprintf(buf, sizeof(buf), "Checking %s...", checkingRoom);
    else                 snprintf(buf, sizeof(buf), "Checking now...");
    drawCentered(String(buf), h - 13, 2);
  } else if (secsToNext >= 0) {
    if (nextRoom[0])
      snprintf(buf, sizeof(buf), "Next: %s %d:%02d", nextRoom, secsToNext / 60, secsToNext % 60);
    else
      snprintf(buf, sizeof(buf), "Next reading in %d:%02d", secsToNext / 60, secsToNext % 60);
    drawCentered(String(buf), h - 13, 2);
  }
}

void renderClean() {
  curBg = GREEN;
  tft.fillScreen(GREEN);
  drawSmiley();
  drawCountdown();
}

// Render each untidy room as a name header followed by a short bulleted list of
// what needs picking up (capped at 3 bullets so it fits the panel).
void renderUntidy(JsonArray rooms) {
  curBg = RED;
  tft.fillScreen(RED);
  tft.setTextColor(TFT_WHITE, RED);

  int y = 6;
  int bullets = 0;
  for (JsonObject room : rooms) {
    if (room["tidy"] | true) continue;  // only the untidy ones
    drawCentered(room["name"].as<const char *>(), y + 12, 4);
    y += 34;
    for (JsonVariant item : room["items"].as<JsonArray>()) {
      if (bullets >= 3) break;
      int by = y + 8;
      tft.fillCircle(12, by, 2, TFT_WHITE);  // bullet dot
      tft.setTextDatum(TL_DATUM);
      tft.drawString(item.as<const char *>(), 22, by - 7, 2);
      y += 22;
      bullets++;
    }
    if (bullets >= 3) break;
  }
  drawCountdown();
}

void renderError(const String &msg) {
  curBg = TFT_BLACK;
  tft.fillScreen(TFT_BLACK);
  tft.setTextColor(TFT_ORANGE, TFT_BLACK);
  drawCentered("No data", tft.height() / 2 - 16, 4);
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  drawCentered(msg, tft.height() / 2 + 14, 2);
}

// Build a short signature of the current state so we only repaint the face when
// the verdict OR the specific untidy items change.
String signatureOf(bool allClean, JsonArray rooms) {
  if (allClean) return "clean";
  String s = "untidy:";
  for (JsonObject r : rooms) {
    if (r["tidy"] | true) continue;
    s += r["name"].as<const char *>();
    s += "[";
    for (JsonVariant item : r["items"].as<JsonArray>()) {
      s += item.as<const char *>();
      s += ",";
    }
    s += "]";
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
  // Resync the countdown + schedule state to the server on every poll.
  checking = doc["checking"] | false;
  secsToNext = doc["next_check_in"] | -1;
  quiet = doc["quiet"] | false;
  strlcpy(checkingRoom, doc["checking_room"] | "", sizeof(checkingRoom));
  strlcpy(nextRoom, doc["next_room"] | "", sizeof(nextRoom));
  strlcpy(resumeTime, doc["resume_time"] | "", sizeof(resumeTime));

  String sig = signatureOf(allClean, rooms);
  if (sig != lastRender) {  // only repaint the face when the verdict/items change
    lastRender = sig;
    if (allClean) {
      renderClean();
    } else {
      renderUntidy(rooms);
    }
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

  // ...but tick the countdown every second so it visibly counts down between polls.
  if (now - lastTickMs >= 1000) {
    lastTickMs = now;
    if (!checking && secsToNext > 0) secsToNext--;
    drawCountdown();
  }

  delay(40);
}
