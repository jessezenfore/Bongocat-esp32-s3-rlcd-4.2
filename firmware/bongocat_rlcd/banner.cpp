#include "banner.h"

#include <string.h>

namespace banner {
namespace {

uint8_t s_bits[kMaxBytes];
int s_x = 0, s_y = 0, s_w = 0, s_h = 0;
size_t s_len = 0;
uint32_t s_expiresMs = 0;    // 0 == no expiry
bool s_visible = false;
uint32_t s_seq = 0;

int8_t b64Value(char c) {
  if (c >= 'A' && c <= 'Z') return (int8_t)(c - 'A');
  if (c >= 'a' && c <= 'z') return (int8_t)(c - 'a' + 26);
  if (c >= '0' && c <= '9') return (int8_t)(c - '0' + 52);
  if (c == '+') return 62;
  if (c == '/') return 63;
  return -1;
}

// Decode into `out`, stopping at `cap` bytes.  Returns the byte count, or -1
// when the input contains a character outside the alphabet.
int decodeBase64(const char *in, uint8_t *out, size_t cap) {
  uint32_t acc = 0;
  int bits = 0;
  size_t n = 0;
  for (const char *p = in; *p != '\0'; p++) {
    const char c = *p;
    if (c == '=' ) {
      break;
    }
    const int8_t v = b64Value(c);
    if (v < 0) {
      return -1;                    // also skips anything unexpected
    }
    acc = (acc << 6) | (uint32_t)v;
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      if (n >= cap) {
        return -1;                  // payload longer than the geometry needs
      }
      out[n++] = (uint8_t)((acc >> bits) & 0xFF);
    }
  }
  return (int)n;
}

}  // namespace

bool showFromBase64(int px, int py, int pw, int ph, uint32_t durationMs,
                    const char *base64) {
  if (pw <= 0 || ph <= 0) {
    return false;
  }
  const size_t need = (size_t)((pw + 7) / 8) * (size_t)ph;
  if (need == 0 || need > kMaxBytes) {
    return false;
  }

  // Scratch copy so a malformed payload cannot leave a half-drawn banner.
  static uint8_t scratch[kMaxBytes];
  const int got = decodeBase64(base64, scratch, need);
  if (got < 0 || (size_t)got != need) {
    return false;
  }

  memcpy(s_bits, scratch, need);
  s_len = need;
  s_x = px;
  s_y = py;
  s_w = pw;
  s_h = ph;
  s_visible = true;
  s_expiresMs = durationMs ? (millis() + durationMs) : 0;
  s_seq++;
  return true;
}

void clear() {
  if (!s_visible) {
    return;
  }
  s_visible = false;
  s_len = 0;
  s_expiresMs = 0;
  s_seq++;
}

bool active(uint32_t nowMs) {
  if (!s_visible) {
    return false;
  }
  if (s_expiresMs != 0 && (int32_t)(nowMs - s_expiresMs) >= 0) {
    clear();                        // expire lazily; sequence bumps so we repaint
    return false;
  }
  return true;
}

uint32_t sequence() { return s_seq; }
int x() { return s_x; }
int y() { return s_y; }
int w() { return s_w; }
int h() { return s_h; }
const uint8_t *bits() { return s_bits; }

}  // namespace banner
