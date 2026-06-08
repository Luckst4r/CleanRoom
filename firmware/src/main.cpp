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
  int cy = tft.height() / 2;
  int r = 55;
  tft.fillCircle(cx, cy, r, TFT_YELLOW);
  tft.drawCircle(cx, cy, r, TFT_BLACK);
  // eyes
  tft.fillCircle(cx - 20, cy - 18, 7, TFT_BLACK);
  tft.fillCircle(cx + 20, cy - 18, 7, TFT_BLACK);
  // smile: a thick downward arc
  tft.drawArc(cx, cy, 34, 26, 35, 145, TFT_BLACK, TFT_YELLOW, true);
}

void renderClean() {
  tft.fillScreen(GREEN);
  tft.setTextColor(TFT_WHITE, GREEN);
  drawSmiley();
  drawCentered("All clean", tft.height() - 22, 4);
}

void renderUntidy(JsonArray rooms) {
  tft.fillScreen(RED);
  tft.setTextColor(TFT_WHITE, RED);
  drawCentered("UNTIDY", 22, 4);

  int y = 64;
  for (JsonVariant room : rooms) {
    drawCentered(room.as<const char *>(), y, 4);
    y += 32;
    if (y > tft.height() - 16) break;  // don't overflow the panel
  }
}

void renderError(const String &msg) {
  tft.fillScreen(TFT_BLACK);
  tft.setTextColor(TFT_ORANGE, TFT_BLACK);
  drawCentered("No data", tft.height() / 2 - 16, 4);
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  drawCentered(msg, tft.height() / 2 + 14, 2);
}

// Build a short signature of the current state so we can skip redundant repaints.
String signatureOf(bool allClean, JsonArray rooms) {
  if (allClean) return "clean";
  String s = "untidy:";
  for (JsonVariant r : rooms) {
    s += r.as<const char *>();
    s += "|";
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
    if (lastRender != "err:json") {
      renderError("bad JSON");
      lastRender = "err:json";
    }
    return;
  }

  bool allClean = doc["all_clean"] | false;
  JsonArray untidy = doc["untidy_rooms"].as<JsonArray>();

  String sig = signatureOf(allClean, untidy);
  if (sig == lastRender) return;  // nothing changed; leave the screen as-is
  lastRender = sig;

  if (allClean) {
    renderClean();
  } else {
    renderUntidy(untidy);
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
  poll();
  delay(POLL_INTERVAL_MS);
}
