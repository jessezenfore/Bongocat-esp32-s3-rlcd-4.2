// ---------------------------------------------------------------------------
// Transient 1-bit banner drawn over the cat scene.
//
// The host renders the text (any language, any font) into an XBM bitmap and
// ships it as base64.  Doing the rasterising on the PC keeps the firmware free
// of CJK fonts, which would never fit in flash.
//
//   host -> board :  B,<x>,<y>,<w>,<h>,<duration_ms>,<base64>
//                    BC                       (clear immediately)
//
// Bits are LSB-first per byte, rows padded to a byte boundary -- exactly what
// U8g2's drawXBM() expects.  A set bit is "ink", so the caller draws it with
// whichever colour ink currently means.
// ---------------------------------------------------------------------------
#pragma once

#include <Arduino.h>

namespace banner {

// Largest banner we accept.  4 KB covers a full-width 400x80 strip.
constexpr size_t kMaxBytes = 4096;

// Decode a base64 bitmap and make it current.  Returns false and leaves the
// existing banner untouched when the geometry or payload is unusable.
bool showFromBase64(int px, int py, int pw, int ph, uint32_t durationMs,
                    const char *base64);

// Hide it now.
void clear();

// True while a banner should be drawn.  Expiry is evaluated against the
// duration given to showFromBase64().
bool active(uint32_t nowMs);

// Bumps on every show/clear so the renderer knows to repaint.
uint32_t sequence();

int x();
int y();
int w();
int h();
const uint8_t *bits();

}  // namespace banner
