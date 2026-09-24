// ---------------------------------------------------------------------------
// Minimal ST7305 panel test for the Waveshare ESP32-S3-RLCD-4.2.
//
// This exists purely as a diagnostic: it drives the panel with nothing else
// going on.  If the screen stays blank with this flashed, the problem is the
// panel / wiring / power / flashed image -- not the bongo cat application.
//
// It deliberately does NOT touch Serial before the first frame, and it keeps
// redrawing a live counter so a frozen image is obvious.
// ---------------------------------------------------------------------------
#include "ST7305_U8g2.h"

#define LCD_SCK_PIN  11
#define LCD_MOSI_PIN 12
#define LCD_DC_PIN   5
#define LCD_CS_PIN   40
#define LCD_RST_PIN  41

// Side button, same pin the main firmware uses (GPIO18, active low).
#define KEY_BUTTON_PIN 18

static ST7305_U8g2 lcd(LCD_SCK_PIN, LCD_MOSI_PIN, LCD_DC_PIN, LCD_CS_PIN,
                       LCD_RST_PIN);
static U8G2 *g = nullptr;

static uint32_t frames = 0;
static bool g_invert = true;      // KEY toggles this, same as the main firmware

static void beginFrame() {
  g->clearBuffer();
  if (g_invert) {
    g->setDrawColor(1);
    g->drawBox(0, 0, 400, 300);
    g->setDrawColor(0);
  } else {
    g->setDrawColor(1);
  }
}

static void draw(uint32_t n) {
  char buf[40];

  beginFrame();

  // outer border proves the full 400x300 area is addressable
  g->drawFrame(0, 0, 400, 300);
  g->drawFrame(3, 3, 394, 294);

  g->setFont(u8g2_font_logisoso42_tn);
  snprintf(buf, sizeof(buf), "%lu", (unsigned long)(n / 10));
  g->drawStr(16, 62, buf);
  g->drawStr(150, 62, ".");

  g->setFont(u8g2_font_7x13B_tr);
  g->drawStr(16, 92, "ST7305 PANEL TEST");
  g->drawStr(16, 112, "GPIO 11/12/5/40/41");
  g->drawStr(16, 132, g_invert ? "POLARITY: INVERTED" : "POLARITY: NORMAL");

  // checkerboard: shows 1-bit contrast across the whole width
  for (int row = 0; row < 7; row++) {
    for (int col = 0; col < 15; col++) {
      if ((row + col) & 1) {
        g->drawBox(16 + col * 24, 146 + row * 18, 24, 18);
      }
    }
  }

  // a block that marches left to right, so a frozen panel is obvious
  g->drawBox(16 + (int)(n % 360), 284, 24, 12);

  g->sendBuffer();
}

void setup() {
  // Panel first, before anything else can get in the way.
  lcd.begin(0, U8G2_R1);
  g = lcd.getU8g2();

  pinMode(KEY_BUTTON_PIN, INPUT_PULLUP);

  draw(0);

  Serial.begin(115200);
  Serial.println();
  Serial.println("panel test: first frame sent");
}

// KEY (GPIO18) flips the panel polarity so both variants can be tried on the
// spot instead of reflashing.
static void pollKey() {
  static bool lastRaw = true;
  static bool stable = true;
  static uint32_t lastEdge = 0;
  const bool raw = digitalRead(KEY_BUTTON_PIN) != LOW;
  const uint32_t now = millis();
  if (raw != lastRaw) {
    lastRaw = raw;
    lastEdge = now;
    return;
  }
  if (raw != stable && (uint32_t)(now - lastEdge) >= 40) {
    stable = raw;
    if (!stable) {
      g_invert = !g_invert;
      Serial.printf("polarity -> %s\n", g_invert ? "inverted" : "normal");
    }
  }
}

void loop() {
  pollKey();

  const uint32_t now = millis();
  if ((uint32_t)(now - (frames * 250u)) >= 250u) {
    frames++;
    draw(frames);
    if ((frames % 4) == 0) {
      Serial.printf("panel test alive: frame %lu\n", (unsigned long)frames);
    }
  }
  delay(5);
}
