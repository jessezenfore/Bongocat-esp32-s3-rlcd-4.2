#include "pc_link.h"

#include <stdlib.h>
#include <string.h>

#include "banner.h"

namespace pc_link {
namespace {

char   s_line[kMaxLine];
size_t s_len = 0;

// Split a NUL-terminated line on commas, in place.  Returns the field count.
int splitFields(char *s, char **argv, int maxFields) {
  int n = 0;
  char *p = s;
  while (n < maxFields) {
    argv[n++] = p;
    char *comma = strchr(p, ',');
    if (comma == nullptr) {
      break;
    }
    *comma = '\0';
    p = comma + 1;
  }
  return n;
}

// strtof/strtoul wrappers that treat an empty field as 0.
float fieldFloat(const char *s) { return *s ? strtof(s, nullptr) : 0.0f; }

uint32_t fieldU32(const char *s) {
  return *s ? (uint32_t)strtoul(s, nullptr, 10) : 0u;
}

int64_t fieldI64(const char *s) {
  return *s ? (int64_t)strtoll(s, nullptr, 10) : 0;
}

void handleLine(char *line, Payload &p, uint32_t now) {
  char *f[8];
  const int n = splitFields(line, f, 8);
  if (n == 0 || f[0][0] == '\0') {
    return;
  }

  const char *verb = f[0];
  bool ok = true;

  if (strcmp(verb, "HELLO") == 0) {
    p.protoVersion = (uint8_t)fieldU32(n > 1 ? f[1] : "");
    if (n > 2) {
      strncpy(p.host, f[2], sizeof(p.host) - 1);
      p.host[sizeof(p.host) - 1] = '\0';
    }
    sendReady();
  } else if (strcmp(verb, "T") == 0 && n >= 2) {
    p.epoch       = fieldI64(f[1]);
    p.tzMinutes   = (int16_t)(n > 2 ? (int32_t)fieldI64(f[2]) : 0);
    p.timeStampMs = now;
    p.timeValid   = true;
  } else if (strcmp(verb, "S") == 0 && n >= 5) {
    p.cpuPercent   = constrain(fieldFloat(f[1]), 0.0f, 100.0f);
    p.memPercent   = constrain(fieldFloat(f[2]), 0.0f, 100.0f);
    p.netDownBps   = fieldU32(f[3]);
    p.netUpBps     = fieldU32(f[4]);
    p.statsStampMs = now;
    p.statsValid   = true;
  } else if (strcmp(verb, "K") == 0 && n >= 3) {
    p.leftDown     = fieldU32(f[1]) != 0;
    p.rightDown    = fieldU32(f[2]) != 0;
    p.handsStampMs = now;
    p.handsValid   = true;
  } else if (strcmp(verb, "A") == 0 && n >= 2) {
    p.keysPerSec  = fieldFloat(f[1]);
    p.keysStampMs = now;
  } else if (strcmp(verb, "B") == 0 && n >= 7) {
    // B,<x>,<y>,<w>,<h>,<duration_ms>,<base64>
    const bool ok2 = banner::showFromBase64(
        (int)fieldI64(f[1]), (int)fieldI64(f[2]), (int)fieldI64(f[3]),
        (int)fieldI64(f[4]), fieldU32(f[5]), f[6]);
    if (!ok2) {
      sendError("bad-banner");
    }
  } else if (strcmp(verb, "BC") == 0) {
    banner::clear();
  } else if (strcmp(verb, "PING") == 0) {
    Serial.print(F("PONG\n"));
  } else {
    ok = false;
  }

  p.linesRx++;
  p.lastLineMs = now;
  p.hostSeen   = true;
  if (!ok) {
    p.linesBad++;
    sendError("bad-line");
  }
}

}  // namespace

void begin(unsigned long baud) {
  // Enlarge the RX ring before begin() so a burst of banner bitmap can never be
  // dropped while the display is mid-flush.
  Serial.setRxBufferSize(kRxBuffer);
  Serial.begin(baud);
}

void poll(Payload &out) {
  while (Serial.available() > 0) {
    const int c = Serial.read();
    if (c < 0) {
      break;
    }
    if (c == '\r') {
      continue;
    }
    if (c == '\n') {
      s_line[s_len] = '\0';
      if (s_len > 0) {
        handleLine(s_line, out, millis());
      }
      s_len = 0;
      continue;
    }
    if (s_len < kMaxLine - 1) {
      s_line[s_len++] = (char)c;
    } else {
      s_len = 0;  // overlong line: drop it and resynchronise on the next '\n'
    }
  }
}

bool isLinked(const Payload &p, uint32_t nowMs) {
  return p.hostSeen && (uint32_t)(nowMs - p.lastLineMs) < LINK_TIMEOUT_MS;
}

bool statsFresh(const Payload &p, uint32_t nowMs) {
  return p.statsValid && (uint32_t)(nowMs - p.statsStampMs) < STATS_STALE_MS;
}

void sendReady() {
  Serial.print(F("READY,"));
  Serial.print(F(FW_NAME));
  Serial.print(',');
  Serial.print(F(FW_VERSION));
  Serial.print('\n');
}

void sendHeartbeat(uint32_t uptimeMs, uint32_t fpsX10) {
  char buf[48];
  snprintf(buf, sizeof(buf), "HB,%lu,%lu\n", (unsigned long)uptimeMs,
           (unsigned long)fpsX10);
  Serial.print(buf);
}

void sendError(const char *reason) {
  Serial.print(F("ERR,"));
  Serial.print(reason);
  Serial.print('\n');
}

}  // namespace pc_link
