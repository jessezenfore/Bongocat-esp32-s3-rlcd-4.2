// ---------------------------------------------------------------------------
// Screen composition: stats header + animated bongo-cat scene.
// ---------------------------------------------------------------------------
#pragma once

#include <U8g2lib.h>

#include "pc_link.h"

namespace bongo_ui {

// One-time initialisation.  `g` is the U8G2 instance owned by ST7305_U8g2.
void begin(U8G2 *g);

// Advance the animation and, at most once every 1000/TARGET_FPS ms, redraw and
// flush the panel.  Returns true when this call actually pushed a frame.
// `force` bypasses both the frame limiter and the "nothing changed" check.
bool render(U8G2 *g, const pc_link::Payload &p, uint32_t nowMs, bool force);

// Most recently measured refresh rate, multiplied by 10 (118 == 11.8 fps).
uint32_t fpsX10();

// Panel polarity.  The default comes from SCREEN_INVERT in bongo_config.h;
// the board's KEY button toggles it at runtime.
void setInverted(bool inverted);
bool inverted();
void toggleInverted();

}  // namespace bongo_ui
