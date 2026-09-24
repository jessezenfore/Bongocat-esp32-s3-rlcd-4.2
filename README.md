# Bongo Cat 桌面监视器 · Waveshare ESP32-S3-RLCD-4.2

把 **[ayangweb/BongoCat](https://github.com/ayangweb/BongoCat)** 的猫搬到
**微雪 ESP32-S3-RLCD-4.2** 这块 4.2 寸全反射屏开发板上：
**敲主键盘区它会按左爪，敲方向键它会按右爪**，同时屏幕上显示
**时间 / CPU 占用 / 内存占用 / 实时网速**。

猫、桌子和键盘的画面都是**原版素材**提取的（不是照着画的），动作逻辑也照搬原版——
电脑端脚本根据按键属于哪一组，去驱动原版那两个 Live2D 参数
`CatParamLeftHandDown` / `CatParamRightHandDown`。

开发板本身不联网、不做任何计算，所有数据都由电脑上的一个 Python 脚本通过
**USB 串口**实时推送过去。

```
┌──────────────────────────────────────────────────────────────┐
│  09:41:23        CPU  ████████░░░░░░  62%                    │
│  Tue 2025-09-09  MEM  ██████░░░░░░░░  48%                    │
│                  NET  ▼███████████░░  1.2 MB/s              │
│                       ▲██░░░░░░░░░░░  32 KB/s               │
├──────────────────────────────────────────────────────────────┤
│ 240 keys/min                                     ● LINK      │
│                                                              │
│                      /\    /\                                │
│                    (  •  ω  •  )        ← 敲键盘时按爪子      │
│                   /|    ⌣    |\                              │
│                  ( |  ▢▢▢  | )                               │
│  ┌──┐┌──┐┌──┐     ╰─┬─────┬─╯                                │
│  │← ││↑ ││→ │       │     │                                  │
│  └──┘└──┘└──┘  ┌───────────────┐                             │
│  PC DESKTOP-ABC│  QWERTYUIOP   │        11.8 fps  mood typing │
└──────────────────────────────────────────────────────────────┘
```

（示意图。实际画面是 1-bit 黑白点阵，见 `docs/art_preview.png`）

![artwork preview](art_preview.png)

---

## 目录结构

```
bongocat-esp-rlcd/
├── firmware/bongocat_rlcd/       ESP32-S3 固件（PlatformIO 与 Arduino IDE 共用）
│   ├── bongocat_rlcd.ino         主程序：初始化 + 主循环
│   ├── bongo_config.h            引脚、屏幕几何、行为参数
│   ├── bongo_ui.cpp/.h           界面绘制 + 动画状态机
│   ├── pc_link.cpp/.h            串口协议解析与状态
│   ├── art_bongocat.h            自动生成的 6 帧 1-bit 点阵图
│   ├── ST7305_U8g2.cpp/.h        屏幕驱动（取自微雪官方例程，Apache-2.0）
│   ├── platformio.ini            PlatformIO 工程配置
│   ├── partitions.csv            与 Arduino IDE 一致的分区表
│   └── release/                  ★ 编译好的、可直接烧录的 bin
│       ├── bongocat_rlcd_esp32s3_rlcd42_merged.bin   合并固件，刷 0x0
│       └── FLASHING.md           烧录说明
├── host/
│   ├── gui.py                    ★ 图形界面 + 托盘（打包成 exe 的就是它）
│   ├── engine.py                 采集 + 串口 + 提醒 + 消息的核心引擎
│   ├── config.py                 设置持久化（%APPDATA%/BongoCat-RLCD/config.json）
│   ├── banner.py                 把文字渲染成 1-bit 横幅位图（支持中文）
│   ├── notify.py                 读取 Windows 通知（可选，需要 winsdk）
│   ├── bongocat_host.py          命令行版（无界面，适合脚本/开机自启）
│   ├── keymon.py                 键盘检测，区分主键盘区 / 方向键
│   ├── build_exe.py              PyInstaller 打包脚本
│   ├── dist/BongoCat.exe         打包产物（单文件，免安装）
│   └── requirements.txt
├── tools/
│   ├── extract_source_art.py     从原版 BongoCat 仓库提取猫和桌子图层
│   ├── make_art.py               图层 → 6 帧 1-bit 点阵 / 预览图
│   ├── pngmini.py                纯标准库 PNG 读写
│   ├── catch_boot_log.py         板子反复重启时抓复位日志
│   ├── assets/                   提取出来的源素材（desk.png / cat.png）
│   └── smoke_test.py             无硬件自检（38 项）
├── docs/
│   ├── PROTOCOL.md               串口协议完整说明
│   └── art_preview.png           6 帧动作预览
└── README.md
```

---

## 一、烧录

**已经编译好了**，直接刷合并固件：

```bash
pip install esptool
python esptool.py --chip esp32s3 --port COMx --baud 921600 write_flash 0x0 \
    firmware/bongocat_rlcd/release/bongocat_rlcd_esp32s3_rlcd42_merged.bin
```

完整的烧录说明（含 Flash Download Tool 图形界面、分开刷分区、自己重新编译）
见 **[firmware/bongocat_rlcd/release/FLASHING.md](firmware/bongocat_rlcd/release/FLASHING.md)**。

固件里已经烧好板卡参数：16 MB Flash、QIO 80 MHz、OPI PSRAM、USB CDC，

### 自己编译

**Arduino IDE**：打开 `firmware/bongocat_rlcd/bongocat_rlcd.ino`，
在库管理器装 **U8g2**（只用官方版，**不需要**微雪定制版），工具菜单设置：

| 选项 | 值 |
| --- | --- |
| Board | `ESP32S3 Dev Module` |
| **USB CDC On Boot** | **Enabled** ← 必须 |
| CPU Frequency | `240MHz (WiFi)` |
| Flash Mode | `QIO 80MHz` |
| Flash Size | `16MB (128Mb)` |
| Partition Scheme | `16M Flash (3MB APP/9.9MB FATFS)` |
| PSRAM | `OPI PSRAM` |
| Upload Speed | `921600` |
| USB Mode | `Hardware CDC and JTAG` |

**PlatformIO**：

```bash
cd firmware/bongocat_rlcd
pio run -t upload
```

---

## 二、运行电脑端

有两种前端，**共用同一个引擎和同一份配置**，二选一即可。

### 方式 A：图形界面（推荐）

免安装，直接双击：

```
host\dist\BongoCatEspHost.exe
```

或者从源码跑（需要先 `pip install -r host/requirements.txt`）：

```bash
python host/gui.py
```

界面里能设置：

| 分区 | 能做什么 |
| --- | --- |
| **连接** | 选串口 / 自动检测、开机自动连接、断线自动重连，实时显示握手状态 |
| **猫爪** | **交换左右手**——主键盘 → 右爪，方向键 → 左爪（原本是反过来的），并实时显示左右爪当前是按下还是抬起 |
| **喝水提醒** | 开关、间隔分钟数、提醒文字、是否同时弹桌面通知、下次提醒倒计时、「立即测试」 |
| **电脑消息** | 把 Windows 通知转发到屏幕、横幅显示时长、手动输入标题/内容发到屏幕、清除 |
| **后台运行** | 关闭窗口时最小化到系统托盘继续后台运行、一键最小化到托盘、打开配置文件夹 |
| **状态 / 日志** | CPU、内存、网速、按键速率、已发消息数、已提醒次数，以及带时间戳的运行日志 |

托盘图标（双击恢复窗口）右键菜单里还有：显示窗口、立即提醒喝水、发送测试消息、退出。

**关闭窗口默认最小化到托盘**，程序继续在后台跑。要真正退出：托盘右键 → 退出，
或者取消勾选「关闭窗口时最小化到托盘」后再关窗口。

配置存在 `%APPDATA%\BongoCat-RLCD\config.json`，界面里改任何东西都会立刻生效并保存。

### 方式 B：命令行（适合开机自启 / 无桌面环境）

```bash
python -m pip install -r host/requirements.txt
python host/bongocat_host.py
```

常用参数：

| 参数 | 说明 |
| --- | --- |
| `--list-ports` | 列出所有串口 |
| `--port COM7` | 手动指定串口 |
| `--demo` | 用模拟数据驱动（验证屏幕/协议时很方便） |
| `--print-only` | 只打印将要发送的协议行，不打开串口 |
| `--interval 1.0` | CPU/内存/网速的采样间隔（秒） |
| `--activity-hz 20` | 按键状态的发送频率 |
| `--keys auto\|win32\|pynput\|none` | 键盘检测方式，默认 `auto` |
| `--swap-paws` | 交换左右手（等价于界面里的那个勾） |
| `--message 该喝水啦` | 往屏幕发一条横幅后退出 |
| `--duration 5` | 跑 5 秒后自动退出（自检用） |

Windows 上默认用 `win32` 方式（ctypes 轮询 `GetAsyncKeyState`），**不需要装额外库**；
Linux/macOS 请 `pip install pynput`，会自动改用 `pynput`。

按 `Ctrl+C` 退出。串口断了（比如拔线）会自动重连，
期间开发板显示 `NO HOST` 并让猫咪闭眼睡觉。

### 自己打包 exe

```bash
python -m pip install pyinstaller
python host/build_exe.py            # → host/dist/BongoCatEspHost.exe（约 42 MB，单文件）
python host/build_exe.py --console  # 需要看报错时带上控制台
```

包里已经把 Python、tkinter、pyserial、psutil、Pillow、pystray 和 WinRT 通知绑定
全打进去了，拷到别的电脑上不用装任何东西。窗口模式没有控制台，
所以崩溃信息会写到 `%APPDATA%\BongoCat-RLCD\error.log`。


### 自检（无需硬件）

```bash
python tools/smoke_test.py
```

38 项检查：协议格式、6 帧点阵的几何与差异、横幅渲染与长度、引擎的提醒/消息/左右手交换、
以及（Windows 下）主键盘与方向键是否分别驱动左右爪。

---

## 三、猫咪怎么动

完全照搬原版 BongoCat 的逻辑：

| 你按下 | 猫咪 |
| --- | --- |
| 主键盘区的任意键（字母、数字、空格、修饰键……） | **左爪**压下去 |
| 方向键 ↑ ↓ ← → | **右爪**压下去 |
| 同时按住两组 | 两只爪子一起压下去 |
| 都不按 | 坐着不动，偶尔眨一下眼 |
| 脚本没在跑 / 串口断了 | 闭眼睡觉，右上角显示 `NO HOST` |

原版在 `useModel.ts` 里就是这么写的：

```ts
function handleKeyChange(isLeft = true, pressed = true) {
  const id = isLeft ? 'CatParamLeftHandDown' : 'CatParamRightHandDown'
  live2d.setParameterValue(id, pressed)
}
```

而左右是按按键素材所在目录分的——`resources/left-keys/` 里是 55 个主键盘按键，
`resources/right-keys/` 里只有 4 个方向键。我们照抄了这个分组。

因为爪子是「沉到桌子后面」，所以动作就是把爪子往桌子下沿滑一段，
桌子挡住的部分自然看不见——这也是原版模型的视觉效果。

---

## 四、屏幕上的内容

| 区域 | 内容 |
| --- | --- |
| 左上 | 大号时间 `HH:MM:SS`，下面一行是星期与日期 |
| 右上 | 四行条形图：`CPU`、`MEM`、`NET ▼`（下行）、`NET ▲`（上行） |
| 右上角 | 链路指示灯：实心方块 + `LINK`；断连时空心方块 + `NO HOST` |
| 猫区左上 | 当前打字速度，如 `240 keys/min`；空闲时显示 `idle` |
| 猫区左下 | 电脑主机名 |
| 猫区右下 | 实际刷新率与动画状态（`idle` / `typing` / `sleep`） |

几个细节：

- **网速条是线性刻度**：0 到 100 MB/s 均匀铺满整条，每 1 MB/s 走的距离一样。
  好处是一眼就能判断"现在到底多快"，代价是日常几十 KB/s ~ 几 MB/s 的流量条子几乎不动
  （具体数值还是照常显示，所以不影响读数）。想换回"每个数量级占 1/7 宽"的对数刻度，
  改 `bongo_ui.cpp` 里的 `rateFraction()` 即可，注释里写了怎么改。
- **时间由电脑校准**：板子收到 `T` 消息后用自己的 `millis()` 走时，断连也不会跳变，
  重新连上自动校准。
- **没有变化就不刷屏**：待机时如果画面内容完全一致，固件会跳过整帧 SPI 传输，
  既省电又避免残影。

---

## 五、画面是怎么来的

这块屏是 1 bit 单色，所以没法直接用原版的 Live2D。做法是：

1. **提取原版素材**（`tools/extract_source_art.py`）
   原版渲染分三层：`background.png`（桌子+方向键+键盘）、Live2D 猫、按键高亮贴图。
   猫只有 Live2D 模型，于是用 `cover.png - background.png` 把猫的像素抠出来，
   得到精确的原版画稿。同时算出桌子下沿每列的 y 坐标，用来做遮挡。
2. **合成姿势**（`tools/make_art.py`）
   把爪子（拱形轮廓 + 肉垫）沿 y 轴下滑，再用桌子下沿裁掉，得到「按下去」的姿势；
   眨眼就是把两个眼点压扁——原版把 `ParamEyeLOpen` 乘到 0.32 也是这个效果。
   肉垫原本是粉色，单色屏没有专色，改成描边画法。
3. **降采样成 1 bit**
   612×354 按面积平均降到 400×232，再按阈值二值化，输出成 U8g2 `drawXBM()` 用的 XBM 数组。

整个流程只依赖标准库，重跑一遍：

```bash
python tools/extract_source_art.py --repo ../../BongoCat --preview
python tools/make_art.py --preview docs/art_preview.png
```

调 `tools/make_art.py` 顶部的常量就能改动作幅度：

| 常量 | 作用 |
| --- | --- |
| `CAT_SCALE` | **猫相对原图的大小**，默认 `0.78`。嫌猫太大/太小就改这个，1.0 是原版比例 |
| `PRESS_DY` | 爪子往下滑多少像素（源图尺度，默认 30） |
| `PAW_REGIONS` | 每只爪子的轮廓区域，决定了抠图的干净程度 |
| `EYES` / `BLINK_RY` | 眼睛位置和眨眼高度 |
| `--threshold` | 二值化阈值，调大线条更粗 |

缩放只作用于**猫本身**，桌子和键盘保持原尺寸；缩放锚点取在桌沿线上的一个点，
因为「绕直线上一点缩放会把该直线映射到自身」，所以猫的底边在任何缩放比例下
都正好压在桌沿上，不会浮空也不会陷进桌子。

改完重新生成一次即可（不用改固件）：

```bash
python tools/make_art.py                          # 用默认 0.78
python tools/make_art.py --cat-scale 0.65         # 再小一点
python tools/make_art.py --cat-scale 1.0          # 回到原版比例
pio run -t upload                                 # 在 firmware/bongocat_rlcd 下
```

### 黑白反相

原版画稿是**白底黑线**。有些 ST7305 面板上电时自带的显示反转会把画面翻成
黑底白线，看着就是「反的」。固件里用一个开关处理：

```cpp
// bongo_config.h
#define SCREEN_INVERT 1     // 0 = 白底黑线，1 = 黑底白线
```

**不用为了试哪个对而反复烧录**——烧一次之后按板子侧边的 **KEY** 键就能实时切换，
屏幕上立刻能看到两种效果，选好之后再改上面的宏重新编译。

（实现上不是发面板命令，而是把缓冲区填满、再用「纸色」画所有内容，
所以插图、文字、状态条会一起翻转。）

### KEY 按键

板子侧边的 `KEY` 键（GPIO18，低电平有效）现在用来切换黑白反相。
`bongo_config.h` 里的 `KEY_BUTTON_PIN` 可以改成别的功能。

### 改界面布局

`bongo_ui.cpp` 顶部集中了所有布局常量和四周留白：

```cpp
const int kPadLeft = 12, kPadRight = 12, kPadTop = 10;  // 四周留白
const int kRowTop[4] = {7, 22, 37, 52};                 // 四行状态条
const int kLabelX = 152, kBarX = 190, kBarW = 130, kValueX = 328;
```

有个坑值得记一下：**这个表头放不下大号时钟**。左列是「时间 + 日期」上下叠放，
`logisoso42_tn` 行高 53 px、日期行高 11 px，加起来 64 px，而表头总共只有 68 px——
几乎没有余量，这正是原来时钟「顶格」的原因。所以时钟换成了 `logisoso34_tn`（43 px），
换来上下 7 px / 3 px 的留白。

想换回大号数字，就把 `FONT_CLOCK` 改回 `u8g2_font_logisoso42_tn` **并去掉日期行**；
如果只改字体不改布局，`kClockGap` 下面的 `static_assert` 会直接编译报错，
而不是悄悄把日期裁掉半行。

配色是单色屏，只有黑/白，所以视觉层次靠**线条粗细**和**填充/描边对比**来做。

### 调节动画手感

`bongo_config.h`：

| 宏 | 作用 |
| --- | --- |
| `TARGET_FPS` | 全屏刷新率上限，默认 12。屏幕刷新耗时约 20–25 ms |
| `LINK_TIMEOUT_MS` | 多久收不到数据就认为断连（触发睡觉动画） |
| `STATS_STALE_MS` | 数据多久没更新就把数值显示成 `--` |
| `ACTIVITY_HOLD_MS` | 最后一次按键后，`keys/min` 还显示多久 |

`bongo_ui.cpp` 里的 `kHandHoldMs` 决定爪子按下后保持多久（默认 120 ms），
让很快的敲击也能落到某一帧上。

---

## 六、常见问题

**屏幕全白 / 花屏**
确认 `USB CDC On Boot` 为 `Enabled`、`PSRAM` 为 `OPI PSRAM`，
并且用的是官方 U8g2（本项目不需要微雪定制版）。

**串口找不到**
先 `python host/bongocat_host.py --list-ports`。ESP32-S3 用的是原生 USB-CDC，
Windows 下一般不需要额外驱动。

**屏幕一直显示 `NO HOST`**
脚本没连上，或者串口被别的程序占用（例如 Arduino IDE 的串口监视器）。
关掉串口监视器再运行脚本。也可以先用 `--print-only` 确认脚本本身正常。

**猫咪不跟着打字动**
Windows 上确认 `--keys` 不是 `none`；用 `python host/keymon.py` 单独测一下，
它会实时显示检测到的按键速率和左右爪状态。远程桌面/无头环境里注入的按键
可能检测不到。

**刷新率显示很低（< 5 fps）**
正常范围是 10–12 fps。过低通常是 `TARGET_FPS` 被调得很高，
或者 SPI 时钟被人为改小。

---

## 七、许可与致谢

- **猫、桌子、键盘的画面来自 [ayangweb/BongoCat](https://github.com/ayangweb/BongoCat)**
  （MIT License, Copyright (c) 2025 ayangweb），动作逻辑（左右爪参数、
  主键盘/方向键分组、眨眼）同样来自该项目。
  本项目只把它的素材转换成了适合 1 bit 反射屏的形式。
- `firmware/bongocat_rlcd/ST7305_U8g2.{h,cpp}` 来自
  [waveshareteam/ESP32-S3-RLCD-4.2](https://github.com/waveshareteam/ESP32-S3-RLCD-4.2)
  （Apache-2.0），未作改动。ST7305 在 U8g2 上游没有驱动，微雪自己实现了一个
  u8x8 display callback。
- 硬件资料：[ESP32-S3-RLCD-4.2 官方文档](https://docs.waveshare.com/ESP32-S3-RLCD-4.2)
- 图形库：[U8g2](https://github.com/olikraus/u8g2) (BSD-2-Clause)
- 辅助编程：Deepseek-V4-Flash
