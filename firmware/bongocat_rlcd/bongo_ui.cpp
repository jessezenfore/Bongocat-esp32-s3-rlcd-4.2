#include "bongo_ui.h"

#include <math.h>
#include <stdio.h>
#include <string.h>

#include "art_bongocat.h"
#include "banner.h"
#include "bongo_config.h"

namespace bongo_ui {
namespace {

// ---- fonts ----------------------------------------------------------------
// All of these ship with the stock U8g2 library.
//
// The clock size is what sets the header's margins: the left column stacks the
// time and the date, and their two line heights plus the margins must fit the
// header.  logisoso42 is 53 px tall and the date adds 11, which fills a 68 px
// header completely -- hence logisoso34 (43 px), which leaves a real top and
// bottom margin.  Swap it back for u8g2_font_logisoso42_tn if you would rather
// have the bigger digits and no date line.
const uint8_t *const FONT_CLOCK     = u8g2_font_logisoso34_tn;
const uint8_t *const FONT_CLOCK_SEC = u8g2_font_7x13B_tr;
const uint8_t *const FONT_LABEL     = u8g2_font_6x12_tf;
const uint8_t *const FONT_TINY      = u8g2_font_5x7_tf;

// ---- layout margins -------------------------------------------------------
// Breathing room around everything.  The cat bitmap's top is plain white now
// that the artwork no longer carries a black band, so the header can end a few
// pixels above the scene boundary without any visible divider.
const int kPadLeft  = 12;
const int kPadRight = 12;
const int kPadTop   = 10;   // cap height of the clock and of the first row
const int kPadBottom = 3;   // left below the clock's date line

// The left column stacks the time and the date, so their two line heights plus
// the margins have to fit the header exactly.  These numbers come from the font
// metrics (logisoso34_tn is 34 above / 9 below the baseline, 7x13B_tr is 9/2);
// if you change FONT_CLOCK this fires instead of silently clipping the date.
//
// kClockGap is only 1 px because the time's descender band is empty for digits:
// "09:41" has no descenders, so the gap you actually see is the date's cap
// height plus this, about 10 px of white between the two lines.  Spending those
// pixels on kPadTop instead buys a visibly larger top margin.
const int kClockGap = 1;    // between the time's descender and the date
static_assert(kPadTop + 34 + 9 + kClockGap + 9 + 2 + kPadBottom == SCENE_Y,
              "clock + date no longer fit the header: pick a smaller FONT_CLOCK "
              "or drop the date line");

// ---- header layout --------------------------------------------------------
// Four 15 px rows: CPU, MEM, network-down, network-up.  Their labels line up
// with the clock's cap height (kPadTop), and the last row's glyphs end at 64.
const int kRowTop[4] = {7, 22, 37, 52};
const int kRowH      = 15;
const int kLabelX    = 152;
const int kTriX      = 174;
const int kBarX      = 190;
const int kBarW      = 130;
const int kBarH      = 9;
const int kValueX    = 328;   // widest value ("999.5 MB/s") reaches 388

// ---- cat frames -----------------------------------------------------------
// Order matches the FRAMES list in tools/make_art.py.
const uint8_t *const kFrames[] = {
    bongo_frame_rest, bongo_frame_rest_blink,
    bongo_frame_left, bongo_frame_right, bongo_frame_both,
    bongo_frame_sleep,
};
enum FrameId : uint8_t {
  F_REST, F_REST_BLINK, F_LEFT, F_RIGHT, F_BOTH, F_SLEEP,
  F_COUNT
};

enum Mood : uint8_t { MOOD_SLEEP, MOOD_IDLE, MOOD_TYPING };
const char *const kMoodName[3] = {"sleep", "idle", "typing"};

// How long a paw stays down after the last "hand down" report, so a short tap
// is still visible at our frame rate.
const uint32_t kHandHoldMs = 120;
// Idle blink cadence.
const uint32_t kIdleStepMs = 600;

// ---- animation state ------------------------------------------------------
uint8_t  s_frame       = F_SLEEP;
uint8_t  s_step        = 0;
Mood     s_mood        = MOOD_SLEEP;
uint32_t s_nextFrameMs = 0;

// ---- render bookkeeping ---------------------------------------------------
uint32_t s_lastPushMs   = 0;
uint32_t s_frames       = 0;
uint32_t s_fpsWindowMs  = 0;
uint32_t s_fpsX10       = 0;

// Snapshot of everything that influences the picture, used to skip refreshes
// when the image would be byte-identical (saves power and avoids ghosting).
struct Snapshot {
  int64_t  epoch;
  uint32_t second;
  uint32_t statsStamp;
  uint32_t keysStamp;
  uint8_t  frame;
  uint32_t bannerSeq;
  bool     linked;
  bool     timeValid;
  bool     statsValid;

  bool operator!=(const Snapshot &o) const {
    return epoch != o.epoch || second != o.second ||
           statsStamp != o.statsStamp || keysStamp != o.keysStamp ||
           frame != o.frame || bannerSeq != o.bannerSeq ||
           linked != o.linked ||
           timeValid != o.timeValid || statsValid != o.statsValid;
  }
};
Snapshot s_snapshot = {};

// --------------------------------------------------------------------------
// Calendar maths (Howard Hinnant's civil-from-days algorithm)
// --------------------------------------------------------------------------
struct DateTime {
  int year, month, day, hour, minute, second, weekday;  // weekday: 0 = Sunday
};

void civilFromDays(int64_t z, int &y, int &m, int &d) {
  z += 719468;
  const int64_t era = (z >= 0 ? z : z - 146096) / 146097;
  const unsigned doe = (unsigned)(z - era * 146097);
  const unsigned yoe =
      (doe - doe / 1460u + doe / 36524u - doe / 146096u) / 365u;
  y = (int)yoe + (int)(era * 400);
  const unsigned doy = doe - (365u * yoe + yoe / 4u - yoe / 100u);
  const unsigned mp = (5u * doy + 2u) / 153u;
  d = (int)(doy - (153u * mp + 2u) / 5u + 1u);
  m = (int)(mp < 10u ? mp + 3u : mp - 9u);
  y += (m <= 2) ? 1 : 0;
}

bool localDateTime(const pc_link::Payload &p, uint32_t nowMs, DateTime &dt) {
  if (!p.timeValid) {
    return false;
  }
  const int64_t secs = p.epoch +
                       (int64_t)((uint32_t)(nowMs - p.timeStampMs) / 1000u) +
                       (int64_t)p.tzMinutes * 60;
  int64_t days = secs / 86400;
  int64_t rem = secs % 86400;
  if (rem < 0) {
    rem += 86400;
    days -= 1;
  }
  civilFromDays(days, dt.year, dt.month, dt.day);
  dt.hour    = (int)(rem / 3600);
  dt.minute  = (int)((rem % 3600) / 60);
  dt.second  = (int)(rem % 60);
  dt.weekday = (int)(((days % 7) + 4 + 7) % 7);
  return true;
}

// --------------------------------------------------------------------------
// Animation
// --------------------------------------------------------------------------
void tickAnimation(const pc_link::Payload &p, uint32_t now) {
  if (!pc_link::isLinked(p, now)) {
    s_mood = MOOD_SLEEP;
    s_frame = F_SLEEP;
    return;
  }

  // The original app maps the two Live2D parameters CatParamLeftHandDown and
  // CatParamRightHandDown straight onto the pressed key groups.  We hold the
  // pose briefly so a 10 ms tap still lands on a rendered frame.
  const bool fresh = p.handsValid &&
                     (uint32_t)(now - p.handsStampMs) < kHandHoldMs;
  const bool left = fresh && p.leftDown;
  const bool right = fresh && p.rightDown;

  if (left || right) {
    if (s_mood != MOOD_TYPING) {
      s_mood = MOOD_TYPING;
      s_step = 0;
    }
    s_frame = (left && right) ? F_BOTH : (left ? F_LEFT : F_RIGHT);
    s_nextFrameMs = now;
    return;
  }

  if (s_mood != MOOD_IDLE) {
    s_mood = MOOD_IDLE;
    s_step = 0;
    s_nextFrameMs = now;
  }
  if ((int32_t)(now - s_nextFrameMs) < 0) {
    return;
  }

  // Sitting still: an occasional blink, like the upstream idle motion.
  static const uint8_t cycle[6] = {F_REST, F_REST, F_REST_BLINK,
                                   F_REST, F_REST, F_REST};
  s_frame = cycle[s_step % 6];
  s_step++;
  s_nextFrameMs = now + kIdleStepMs;
}

// --------------------------------------------------------------------------
// Drawing helpers
// --------------------------------------------------------------------------
void drawBar(U8G2 *g, int x, int y, int w, int h, float fraction) {
  g->drawFrame(x, y, w, h);
  if (!(fraction > 0.0f)) {
    return;
  }
  if (fraction > 1.0f) {
    fraction = 1.0f;
  }
  const int fill = (int)((float)(w - 4) * fraction + 0.5f);
  if (fill > 0) {
    g->drawBox(x + 2, y + 2, fill, h - 4);
  }
}

// Network throughput scale: linear, 0 .. 100 MB/s across the full bar, so every
// MB/s moves the bar by the same amount.
//
// This replaces the earlier logarithmic mapping.  A linear bar spends most of
// its travel on speeds you rarely reach, so ordinary browsing sits near empty --
// that is the trade-off for it being easy to read at a glance.  Swap in
//   (log10f(bps) - 1.0f) / 7.0f
// if you would rather have each decade take an equal share again.
const float kNetFullScaleBps = 100.0f * 1000.0f * 1000.0f;   // 100 MB/s

float rateFraction(uint32_t bps) {
  return constrain((float)bps / kNetFullScaleBps, 0.0f, 1.0f);
}

void formatRate(char *out, size_t n, uint32_t bps) {
  if (bps < 1000u) {
    snprintf(out, n, "%lu B/s", (unsigned long)bps);
  } else if (bps < 999500u) {
    snprintf(out, n, "%lu KB/s", (unsigned long)((bps + 500u) / 1000u));
  } else if (bps < 999500000u) {
    snprintf(out, n, "%.1f MB/s", (double)bps / 1e6);
  } else {
    snprintf(out, n, "%.1f GB/s", (double)bps / 1e9);
  }
}

void drawHeader(U8G2 *g, const pc_link::Payload &p, const DateTime &dt,
                bool haveTime, bool linked, bool fresh) {
  char buf[32];

  // ---- big clock (top-left) ---------------------------------------------
  g->setFont(FONT_CLOCK);
  const int clockAscent = g->getAscent();
  const int clockDescent = g->getDescent();
  const int clockBase = kPadTop + clockAscent;

  if (haveTime) {
    snprintf(buf, sizeof(buf), "%02d:%02d", dt.hour, dt.minute);
  } else {
    snprintf(buf, sizeof(buf), "--:--");
  }
  g->drawStr(kPadLeft, clockBase, buf);
  const int clockW = g->getStrWidth(buf);

  g->setFont(FONT_CLOCK_SEC);
  if (haveTime) {
    snprintf(buf, sizeof(buf), ":%02d", dt.second);
  } else {
    snprintf(buf, sizeof(buf), ":--");
  }
  g->drawStr(kPadLeft + clockW + 5, clockBase, buf);

  // ---- date + host state (under the clock) -------------------------------
  static const char *const kDow[7] = {"Sun", "Mon", "Tue", "Wed",
                                      "Thu", "Fri", "Sat"};
  g->setFont(FONT_CLOCK_SEC);
  if (haveTime) {
    snprintf(buf, sizeof(buf), "%s %04d-%02d-%02d", kDow[dt.weekday], dt.year,
             dt.month, dt.day);
  } else if (linked) {
    snprintf(buf, sizeof(buf), "syncing time...");
  } else {
    snprintf(buf, sizeof(buf), "waiting for host");
  }
  g->drawStr(kPadLeft, clockBase + (-clockDescent) + kClockGap
                          + g->getAscent(), buf);

  // ---- four stat rows ----------------------------------------------------
  g->setFont(FONT_LABEL);
  const int textBase = g->getAscent() + 3;  // relative to a row's top edge

  const char *labels[4] = {"CPU", "MEM", "NET", ""};
  const float values[4] = {
      fresh ? p.cpuPercent / 100.0f : 0.0f,
      fresh ? p.memPercent / 100.0f : 0.0f,
      fresh ? rateFraction(p.netDownBps) : 0.0f,
      fresh ? rateFraction(p.netUpBps) : 0.0f,
  };
  const uint32_t rates[4] = {0, 0, p.netDownBps, p.netUpBps};

  for (int row = 0; row < 4; row++) {
    const int top = kRowTop[row];

    if (labels[row][0] != '\0') {
      g->drawStr(kLabelX, top + textBase, labels[row]);
    }

    // Throughput rows get a direction arrow; CPU/MEM leave the slot blank.
    if (row == 2) {
      g->drawTriangle(kTriX, top + 3, kTriX + 9, top + 3, kTriX + 4, top + 11);
    } else if (row == 3) {
      g->drawTriangle(kTriX, top + 11, kTriX + 9, top + 11, kTriX + 4, top + 3);
    }

    drawBar(g, kBarX, top + 3, kBarW, kBarH, values[row]);

    g->setFont(FONT_LABEL);
    if (row < 2) {
      if (fresh) {
        snprintf(buf, sizeof(buf), "%d%%", (int)(values[row] * 100.0f + 0.5f));
      } else {
        snprintf(buf, sizeof(buf), "--");
      }
    } else {
      if (fresh) {
        formatRate(buf, sizeof(buf), rates[row]);
      } else {
        snprintf(buf, sizeof(buf), "--");
      }
    }
    g->drawStr(kValueX, top + textBase, buf);
  }
}

void drawSceneOverlays(U8G2 *g, const pc_link::Payload &p, uint32_t now,
                       bool linked) {
  char buf[40];
  // Keep the same left/right margins as the header so the whole screen lines
  // up on a common grid.
  const int topBase = SCENE_Y + 6 + 9;   // 6x12 ascent is 9
  const int botBase = SCREEN_H - 6;

  // ---- keyboard rate, top-left ------------------------------------------
  g->setFont(FONT_LABEL);
  const bool active = (uint32_t)(now - p.keysStampMs) < ACTIVITY_HOLD_MS;
  if (linked && active && p.keysPerSec > 0.2f) {
    snprintf(buf, sizeof(buf), "%d keys/min", (int)(p.keysPerSec * 60.0f + 0.5f));
  } else {
    snprintf(buf, sizeof(buf), "idle");
  }
  g->drawStr(kPadLeft, topBase, buf);

  // ---- link state, top-right --------------------------------------------
  g->setFont(FONT_LABEL);
  snprintf(buf, sizeof(buf), "%s", linked ? "LINK" : "NO HOST");
  const int linkW = g->getStrWidth(buf);
  const int linkX = SCREEN_W - kPadRight - linkW;
  g->drawStr(linkX, topBase, buf);
  // a filled square next to it doubles as a link LED
  if (linked) {
    g->drawBox(linkX - 14, topBase - 9, 8, 8);
  } else {
    g->drawFrame(linkX - 14, topBase - 9, 8, 8);
  }

  // ---- footer ------------------------------------------------------------
  g->setFont(FONT_TINY);
  if (p.host[0] != '\0') {
    snprintf(buf, sizeof(buf), "PC %s", p.host);
  } else {
    snprintf(buf, sizeof(buf), "PC -");
  }
  g->drawStr(kPadLeft, botBase, buf);

  snprintf(buf, sizeof(buf), "%lu.%lu fps  mood %s", (unsigned long)(s_fpsX10 / 10),
           (unsigned long)(s_fpsX10 % 10), kMoodName[s_mood]);
  const int fpsW = g->getStrWidth(buf);
  g->drawStr(SCREEN_W - kPadRight - fpsW, botBase, buf);
}

}  // namespace

// --------------------------------------------------------------------------
// Public API
// --------------------------------------------------------------------------
namespace {

bool s_inverted = (SCREEN_INVERT != 0);
bool s_forceRedraw = true;

// "Ink" is whatever colour currently draws the artwork; "paper" is the
// background.  They swap when the panel polarity is flipped.
inline uint8_t inkColor() { return s_inverted ? 0 : 1; }
inline uint8_t paperColor() { return s_inverted ? 1 : 0; }

// Start a frame honouring the panel polarity.  U8G2 has no global invert, so
// "inverted" means filling the buffer with ink and then drawing everything in
// the paper colour -- the artwork and the text both come out flipped.
void beginFrame(U8G2 *g) {
  g->clearBuffer();
  if (s_inverted) {
    g->setDrawColor(1);
    g->drawBox(0, 0, SCREEN_W, SCREEN_H);
    g->setDrawColor(0);
  } else {
    g->setDrawColor(1);
  }
}

}  // namespace

void begin(U8G2 *g) {
  // U8G2 was already initialised by ST7305_U8g2::begin(); just paint a
  // splash so the panel is not blank while we wait for the host.
  beginFrame(g);
  g->setFont(FONT_LABEL);
  g->drawStr(10, SCENE_Y + 20, "bongo cat booting...");
  g->sendBuffer();
  s_fpsWindowMs = millis();
}

uint32_t fpsX10() { return s_fpsX10; }

bool inverted() { return s_inverted; }

void setInverted(bool inv) {
  if (inv == s_inverted) {
    return;
  }
  s_inverted = inv;
  s_forceRedraw = true;   // the snapshot is unchanged, so ask for a repaint
}

void toggleInverted() { setInverted(!s_inverted); }

bool render(U8G2 *g, const pc_link::Payload &p, uint32_t now, bool force) {
  tickAnimation(p, now);

  if (!force && !s_forceRedraw &&
      (uint32_t)(now - s_lastPushMs) < (1000u / TARGET_FPS)) {
    return false;
  }

  const bool linked = pc_link::isLinked(p, now);
  const bool fresh  = pc_link::statsFresh(p, now);
  DateTime dt{};
  const bool haveTime = localDateTime(p, now, dt);

  Snapshot snap{};
  snap.epoch      = haveTime ? p.epoch : 0;
  snap.second     = haveTime ? (uint32_t)dt.second : 255u;
  snap.statsStamp = fresh ? p.statsStampMs : 0u;
  snap.keysStamp  = (uint32_t)(now - p.keysStampMs) < ACTIVITY_HOLD_MS
                        ? p.keysStampMs : 0u;
  snap.frame      = s_frame;
  snap.bannerSeq  = banner::sequence();
  snap.linked     = linked;
  snap.timeValid  = haveTime;
  snap.statsValid = fresh;

  if (!force && !s_forceRedraw && !(snap != s_snapshot)) {
    return false;  // identical picture: skip the SPI burst entirely
  }
  s_snapshot = snap;
  s_forceRedraw = false;

  s_lastPushMs = now;

  beginFrame(g);

  drawHeader(g, p, dt, haveTime, linked, fresh);
  g->drawXBM(0, SCENE_Y, BONGO_FRAME_W, BONGO_FRAME_H, kFrames[s_frame]);
  drawSceneOverlays(g, p, now, linked);

  // The host-rendered message banner sits on top of everything else.  Its
  // bitmap only carries the 1 bits (border + glyphs), so cover the rectangle
  // with the paper colour first, otherwise the cat shows through the text.
  if (banner::active(now)) {
    g->setDrawColor(paperColor());
    g->drawBox(banner::x(), banner::y(), banner::w(), banner::h());
    g->setDrawColor(inkColor());
    g->drawXBM(banner::x(), banner::y(), banner::w(), banner::h(),
               banner::bits());
  }

  g->sendBuffer();

  // ---- fps measurement ---------------------------------------------------
  s_frames++;
  const uint32_t elapsed = now - s_fpsWindowMs;
  if (elapsed >= 1000u) {
    s_fpsX10 = (uint32_t)((uint64_t)s_frames * 10000ULL / elapsed);
    s_frames = 0;
    s_fpsWindowMs = now;
  }
  return true;
}

}  // namespace bongo_ui
