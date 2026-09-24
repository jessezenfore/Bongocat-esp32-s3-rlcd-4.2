// ---------------------------------------------------------------------------
// Board + behaviour configuration for the ESP32-S3-RLCD-4.2 bongo cat.
// ---------------------------------------------------------------------------
#pragma once

// ---- panel wiring (Waveshare ESP32-S3-RLCD-4.2) ---------------------------
#define RLCD_SCK_PIN  11
#define RLCD_MOSI_PIN 12
#define RLCD_DC_PIN   5
#define RLCD_CS_PIN   40
#define RLCD_RST_PIN  41

// Spare side button on the board (GPIO18, active low).  Unused by the default
// firmware -- handy if you want to add a page toggle of your own.
#define KEY_BUTTON_PIN 18

// ---- screen geometry ------------------------------------------------------
// The ST7305 is a 300x400 panel; U8G2_R1 rotates it into 400x300 landscape.
#define SCREEN_W 400
#define SCREEN_H 300
#define SCENE_W  400
#define SCENE_H  232
#define SCENE_Y  (SCREEN_H - SCENE_H)   // 68: the height of the stats header

// ---- identity -------------------------------------------------------------
#define FW_NAME    "BongoCat-RLCD"
#define FW_VERSION "1.0.0"

// Native USB-CDC ignores the baud rate, but the number must still match what
// the host opens the port with (the Python client defaults to 115200).
#define SERIAL_BAUD 115200

// ---- behaviour ------------------------------------------------------------
#define LINK_TIMEOUT_MS 4000   // no bytes from the host -> show the sleeping cat
#define STATS_STALE_MS  5000   // stats older than this render as "--"
#define TARGET_FPS      12     // full-screen refresh rate (one SPI burst each)
#define ACTIVITY_HOLD_MS 1500  // keep tapping this long after the last keystroke

// ---- panel polarity -------------------------------------------------------
// 0 = black ink on a white background (what the artwork is designed as).
// 1 = inverted: white ink on black.
// Some ST7305 panels come up with display inversion on, which flips the
// picture; flip this if the screen looks inverted.  You do not have to
// reflash to find out -- pressing the board's KEY button toggles it live.
#define SCREEN_INVERT 1
