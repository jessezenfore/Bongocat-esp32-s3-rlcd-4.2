// ---------------------------------------------------------------------------
// Line-oriented serial protocol between the PC host and the board.
//
// Everything is ASCII, one message per line, fields separated by commas and
// terminated by '\n'.  See docs/PROTOCOL.md for the full specification.
//
//   host -> board :  HELLO,<ver>,<hostname>
//                    T,<epoch>,<tz_offset_minutes>
//                    S,<cpu%>,<mem%>,<down_Bps>,<up_Bps>
//                    K,<left_down>,<right_down>
//                    A,<keys_per_second>
//                    B,<x>,<y>,<w>,<h>,<duration_ms>,<base64 1-bit bitmap>
//                    BC
//                    PING
//
//   board -> host :  READY,<name>,<version>
//                    HB,<uptime_ms>,<fps_x10>
//                    PONG
//                    ERR,<reason>
// ---------------------------------------------------------------------------
#pragma once

#include <Arduino.h>

#include "bongo_config.h"

namespace pc_link {

// Longest accepted host line.  A banner bitmap arrives as one long base64 line
// (~3.6 kB for a 384x56 strip), so this has to be generous.
constexpr size_t kMaxLine = 6144;

// Must comfortably exceed kMaxLine, otherwise a burst of bitmap data can
// overflow the CDC queue while the display is being flushed.
constexpr size_t kRxBuffer = 8192;

struct Payload {
  // -- link bookkeeping ---------------------------------------------------
  bool     hostSeen     = false;
  uint32_t lastLineMs   = 0;      // millis() of the last accepted line
  uint32_t linesRx      = 0;
  uint32_t linesBad     = 0;
  uint8_t  protoVersion = 0;
  char     host[20]     = {0};

  // -- wall clock ---------------------------------------------------------
  bool     timeValid    = false;
  int64_t  epoch        = 0;      // UTC seconds since 1970-01-01
  int16_t  tzMinutes    = 0;      // local offset from UTC, in minutes
  uint32_t timeStampMs  = 0;      // millis() when `epoch` was received

  // -- host load ----------------------------------------------------------
  bool     statsValid   = false;
  float    cpuPercent   = 0.0f;
  float    memPercent   = 0.0f;
  uint32_t netDownBps   = 0;      // bytes per second arriving at the PC
  uint32_t netUpBps     = 0;      // bytes per second leaving the PC
  uint32_t statsStampMs = 0;

  // -- keyboard activity --------------------------------------------------
  // The original BongoCat app drives two parameters, CatParamLeftHandDown and
  // CatParamRightHandDown: keys on the main keyboard push the left paw down,
  // the arrow cluster pushes the right paw down.  We mirror those exactly.
  bool     handsValid   = false;
  bool     leftDown     = false;
  bool     rightDown    = false;
  uint32_t handsStampMs = 0;

  float    keysPerSec   = 0.0f;
  uint32_t keysStampMs  = 0;
};

// Prepare the USB-CDC serial port.  Call once from setup().
void begin(unsigned long baud);

// Drain whatever the host has sent and fold it into `out`.  Never blocks.
void poll(Payload &out);

// True while the host is still talking to us.
bool isLinked(const Payload &p, uint32_t nowMs);

// True when the most recent stats sample is still fresh enough to display.
bool statsFresh(const Payload &p, uint32_t nowMs);

void sendReady();
void sendHeartbeat(uint32_t uptimeMs, uint32_t fpsX10);
void sendError(const char *reason);

}  // namespace pc_link
