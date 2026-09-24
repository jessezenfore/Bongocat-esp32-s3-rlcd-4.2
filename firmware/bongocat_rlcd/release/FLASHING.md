# 烧录说明

这个目录里是**已经编译好**的固件，不需要装 Arduino IDE 或 PlatformIO 就能刷进
Waveshare ESP32-S3-RLCD-4.2。

| 文件 | 大小 | 烧录地址 | 说明 |
| --- | --- | --- | --- |
| `bongocat_rlcd_esp32s3_rlcd42_merged.bin` | 430 KB | `0x0` | **只刷这一个就够了**，四个分区已合并 |
| `bootloader.bin` | 15 KB | `0x0` | 二级引导 |
| `partitions.bin` | 3 KB | `0x8000` | 分区表 |
| `boot_app0.bin` | 8 KB | `0xe000` | OTA 引导数据 |
| `app_firmware.bin` | 365 KB | `0x10000` | 应用程序本体 |
| `diag_panel_test.bin` | 345 KB | `0x0` | 诊断用：极简屏幕测试，屏幕不亮时先刷这个 |

合并固件里保留的是构建产物自己的 flash 参数（**80 MHz / 16 MB**），
和 `pio run -t upload` 写进去的完全一致，用下面的命令不需要再指定。

> **屏幕看着是反的（黑底白字）？** 按一下板子侧边的 **KEY** 键就能实时切换黑白反相，
> 不用重新烧录。选好之后再改 `bongo_config.h` 里的 `SCREEN_INVERT` 重新编译。

---

## 方式一：esptool（推荐，命令行）

先装一次 esptool，然后插上 Type-C 线：

```bash
pip install esptool

# Windows 上是 COMx，Linux/macOS 上是 /dev/ttyACM0
esptool.py --chip esp32s3 --port COM7 --baud 921600 write_flash 0x0 \
    bongocat_rlcd_esp32s3_rlcd42_merged.bin
```

如果提示连接不上，按住板子上的 **BOOT** 键不放，再按一下 **PWR**（或重新插拔 USB），
松开 BOOT 让板子进入下载模式，然后重试。

烧完板子会自动重启，屏幕先显示 `bongo cat booting...`，然后猫咪出场。

---

## 方式二：Flash Download Tool（Windows 图形界面）

1. 下载乐鑫的 [Flash Download Tool](https://www.espressif.com/en/support/download/other-tools)。
2. 打开后选 **ESP32-S3** → **Develop**。
3. 按下表填写，然后点 **START**：

   | 项 | 值 |
   | --- | --- |
   | SPI SPEED | `80MHz` |
   | SPI MODE | `QIO` |
   | Flash Size | `16MB` |
   | DoNotChgBin | 勾选 |

   | 文件 | 地址 |
   | --- | --- |
   | `bongocat_rlcd_esp32s3_rlcd42_merged.bin` | `0x0` |

4. 右上角选对 COM 口，波特率 `921600` 一般没问题。

---

## 方式三：分开刷四个分区

`DoNotChgBin` 不勾选时，或想手工控制每个分区，用：

```bash
esptool.py --chip esp32s3 --port COM7 --baud 921600 write_flash \
    --flash_mode qio --flash_freq 80m --flash_size 16MB \
    0x0     bootloader.bin \
    0x8000  partitions.bin \
    0xe000  boot_app0.bin \
    0x10000 app_firmware.bin
```

---

## 烧完之后

电脑上运行配套的脚本，屏幕才会显示时间 / CPU / 内存 / 网速：

```bash
pip install -r ../../../host/requirements.txt
python ../../../host/bongocat_host.py
```

烧完但不运行脚本时，屏幕会显示 `NO HOST` 并让猫咪闭眼睡觉——这是正常的。

---

## 重新编译

改完源码后自己出固件：

```bash
cd ..            # 进入 firmware/bongocat_rlcd
pio run          # 只编译，产物在 .pio/build/esp32-s3-rlcd-42/
pio run -t upload    # 编译并直接烧录
```

或者直接用 Arduino IDE 打开 `bongocat_rlcd.ino`，板卡设置见根目录 README。
Arduino IDE 里用「导出已编译的二进制文件」也能得到一份合并好的 bin。

想重新生成这个目录里的合并固件：

```bash
pip install esptool
cd firmware/bongocat_rlcd

BD=.pio/build/esp32-s3-rlcd-42
BOOTAPP=$(python -c "import os,glob;print(glob.glob(os.path.expanduser('~/.platformio/packages/framework-arduinoespressif32/tools/partitions/boot_app0.bin'))[0])")

esptool.py --chip esp32s3 merge_bin \
    -o release/bongocat_rlcd_esp32s3_rlcd42_merged.bin \
    --flash_mode qio --flash_freq 80m --flash_size 16MB \
    0x0     $BD/bootloader.bin \
    0x8000  $BD/partitions.bin \
    0xe000  "$BOOTAPP" \
    0x10000 $BD/firmware.bin
```
