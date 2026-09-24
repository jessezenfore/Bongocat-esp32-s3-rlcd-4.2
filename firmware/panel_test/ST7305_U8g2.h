// ---------------------------------------------------------------------------
// ST7305 (4.2" reflective LCD, 300x400) driver wrapped around U8g2.
//
// Vendored unchanged from Waveshare's ESP32-S3-RLCD-4.2 example package,
// 02_Example/Arduino/10_U8G2_Test/ST7305_U8g2.{h,cpp}
//   https://github.com/waveshareteam/ESP32-S3-RLCD-4.2   (Apache-2.0)
//
// The panel has no U8g2 driver upstream, so Waveshare installs its own u8x8
// display callback (u8x8_d_st7305_custom) into a private U8G2 instance and
// hands that instance out through getU8g2().  We keep this file compatible
// with the vendor original so it can be dropped into an Arduino IDE sketch
// folder exactly as shipped.
// ---------------------------------------------------------------------------
#pragma once

#include <Arduino.h>
#include <SPI.h>
#include <U8g2lib.h>

class ST7305_U8g2 {
private:
  int _sck;
  int _mosi;
  int _dc;
  int _cs;
  int _rst;
  SPIClass *_spi = nullptr;
  U8G2 u8g2_wrapper;
  uint8_t *_my_buf = nullptr;

  void _cmd(uint8_t cmd);
  void _data(const uint8_t *data, size_t len);
  void _cmd_data(uint8_t cmd, const uint8_t *data, size_t len);

  static uint8_t u8x8_d_st7305_custom(u8x8_t *u8x8, uint8_t msg, uint8_t arg_int, void *arg_ptr);
  static uint8_t u8x8_byte_custom(u8x8_t *u8x8, uint8_t msg, uint8_t arg_int, void *arg_ptr);

public:
  ST7305_U8g2(int sck = 11, int mosi = 12, int dc = 5, int cs = 40, int rst = 41);
  ~ST7305_U8g2();

  // tile_buf_height 0 means full-buffer mode, about 15 KB RAM for 300x400.
  // A smaller value can be used with firstPage()/nextPage(), but this demo uses full-buffer mode.
  void begin(uint8_t tile_buf_height = 0, const u8g2_cb_t *rotation = U8G2_R0);
  void reset();
  void fullInit();

  U8G2 *getU8g2()
  {
    return &u8g2_wrapper;
  }
};
