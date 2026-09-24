// ---------------------------------------------------------------------------
// Bongo Cat desktop monitor for the Waveshare ESP32-S3-RLCD-4.2
//
//   * 4.2" 300x400 reflective LCD (ST7305), driven through U8g2
//   * animated bongo cat whose paws tap along with your typing
//   * wall clock, CPU load, memory load and network throughput streamed from
//     a PC over USB serial by host/bongocat_host.py
//
// The board does no networking of its own: every value on screen arrives from
// the host script.  See docs/PROTOCOL.md for the wire format.
// ---------------------------------------------------------------------------
#include "ST7305_U8g2.h"
#include "bongo_config.h"
#include "bongo_ui.h"
#include "pc_link.h"

static ST7305_U8g2 lcd(RLCD_SCK_PIN, RLCD_MOSI_PIN, RLCD_DC_PIN, RLCD_CS_PIN,
                       RLCD_RST_PIN);

static pc_link::Payload g_payload;

static uint32_t g_lastHeartbeatMs = 0;

// How often the board volunteers a heartbeat to the host (also proves the
// USB link works in both directions).
static const uint32_t kHeartbeatIntervalMs = 5000;

// The board's KEY button toggles the panel polarity, so you can find the right
// one without reflashing.  Active low with the internal pull-up.
static void pollKeyButton() {
  static bool lastRaw = true;
  static bool stable = true;
  static uint32_t lastEdgeMs = 0;

  const bool raw = digitalRead(KEY_BUTTON_PIN) != LOW;
  const uint32_t now = millis();
  if (raw != lastRaw) {
    lastRaw = raw;
    lastEdgeMs = now;
    return;
  }
  if (raw != stable && (uint32_t)(now - lastEdgeMs) >= 40) {
    stable = raw;
    if (!stable) {                 // pressed
      bongo_ui::toggleInverted();
    }
  }
}

void setup() {
  // Bring the panel up *first*.  If anything on the USB-serial side ever goes
  // wrong we still want a picture on screen, and there is nothing to gain by
  // waiting for a host before the first frame.
  lcd.begin(0, U8G2_R1);          // 0 == full-frame buffer, rotated landscape
  bongo_ui::begin(lcd.getU8g2());

  pinMode(KEY_BUTTON_PIN, INPUT_PULLUP);

  pc_link::begin(SERIAL_BAUD);
  pc_link::sendReady();
}

void loop() {
  const uint32_t now = millis();

  pollKeyButton();
  pc_link::poll(g_payload);
  bongo_ui::render(lcd.getU8g2(), g_payload, now, /*force=*/false);

  if ((uint32_t)(now - g_lastHeartbeatMs) >= kHeartbeatIntervalMs) {
    g_lastHeartbeatMs = now;
    pc_link::sendHeartbeat(now, bongo_ui::fpsX10());
  }

  // Nothing to do until the next animation or clock tick; yielding keeps the
  // idle task (and therefore the USB stack) fed.
  delay(1);
}
