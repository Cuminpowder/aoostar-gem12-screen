# gem12-subscreen

![screenshot](docs/screenshot.jpg)

Turn the otherwise useless little display on an **AOOSTAR GEM12** mini-PC into
a personal dashboard: pick any picture, choose a layout, crop it like a chat
avatar, and push it to the 960×376 front panel — with live time, CPU
temperature, CPU load and memory drawn on top.

Works on Linux (Proxmox VE, Debian/Ubuntu, Unraid, …) because AOOSTAR's own
Windows installer happens to bundle a Linux build of its agent. This project
does not redistribute that agent; it drives it.

```
┌──────────────────────────── 960 × 376 ─────────────────────────────┐
│  J U S T   M O N I K A                                  ╭────────╮  │
│                                                         │        │  │
│  21:47                                                  │  photo │  │
│  2026/11/05                                             │  card  │  │
│                                                         │        │  │
│  CPU 温度                       57 ℃                    │        │  │
│  CPU 占用                       12 %                    ╰────────╯  │
│  内     存                      43 %                               │
│  今天也辛苦了。                                                     │
└────────────────────────────────────────────────────────────────────┘
```

## Features

* **Three layouts** — rounded photo card on a dark gradient, full-bleed image,
  or image as background *under* the photo card.
* **Avatar-style cropping** — drag to pan, scroll/slider to zoom, live
  whole-screen preview (the preview is rendered by the same server-side
  compositor that pushes to the panel, so WYSIWYG is literal).
* **Live readouts** — clock, date, CPU temperature, CPU load, memory usage.
* **Rotation** — upload several images and they cycle on a timer.
* **Survives reboots** — a systemd guard re-applies the two settings the vendor
  agent gets wrong on a GEM12 (see *Troubleshooting*).
* **No reverse-engineering needed at runtime** — but the [protocol notes](docs/protocol.md)
  document the USB framing anyway, plus a tool to decode captured frames.

## How it fits together

```
┌──────────────┐   HTTP :5124   ┌───────────────┐   HTTP :5123   ┌──────────────────┐
│   browser    │ ─────────────▶ │  webui/app.py │ ─────────────▶ │  AOOSTAR-X agent │
│ (upload/crop)│                │  (this repo)  │ save_custom_   │  (vendor binary) │
└──────────────┘                └───────────────┘ panels +       └────────┬─────────┘
                                        │ restart_cmd                     │ USB bulk
                                        └───────────────────────────────▶ │
                                                                  ┌───────▼────────┐
                                                                  │ 960×376 panel  │
                                                                  └────────────────┘
```

The agent renders the numbers; this project renders the picture and tells the
agent where to put them.

## Install

### 1. Host side (the machine the screen is plugged into)

Download `AOOSTAR-X V1.3.5.zip` from AOOSTAR's support page for your model and
extract `AOOSTAR-X-linux/` to e.g. `/root/AOOSTAR-X-linux`.

```bash
sudo ./host/install.sh /root/AOOSTAR-X-linux 60
```

This installs:

* `aoostar-x-service.service` — runs the vendor agent.
* `gem12-screen-fix.service` — one-shot guard, ordered **before** the agent:
  forces `type=2` (GEM12), clears the built-in panel rotation, and mirrors the
  built-in panels to your current custom panel.

The agent's own UI is then on `http://127.0.0.1:5123` (default
`admin` / `123456` — please change it).

### 2. Web UI side (any box that can reach port 5123)

```bash
python3 -m pip install -r webui/requirements.txt
cp config.example.json config.json      # edit it
python3 webui/app.py                    # http://0.0.0.0:5124
```

If the web UI does not run on the same machine as the agent, point
`restart_cmd` at it, e.g.:

```json
"restart_cmd": "ssh root@screen-host 'GEM12_SWITCH=60 python3 /usr/local/lib/gem12/fix_config.py && systemctl restart aoostar-x-service'"
```

## Configuration

`config.json` (or `GEM12_*` environment variables):

| key | default | meaning |
|---|---|---|
| `aoostar_url` | `http://127.0.0.1:5123` | agent web API |
| `username` / `password` | `admin` / `123456` | agent credentials |
| `restart_cmd` | `systemctl restart aoostar-x-service` | run after pushing panels |
| `data_dir` | `./data` | uploads + `panels.json` + `defaults.json` |
| `switch_time` | `60` | seconds per panel when rotating |
| `header` | `JUST MONIKA` | small letter-spaced label at the top |
| `fonts` | `[]` | extra font paths, tried before the built-in candidates |

## Usage

1. Drop an image on the start page.
2. Pick a layout: `card`, `full-bleed`, or `bg + card` (the last one lets you
   upload a separate background image).
3. Drag / zoom until the framing looks right — the right-hand preview is the
   exact bytes that go to the panel.
4. **Apply to screen.** The panel blanks for a second while the agent restarts.
5. *Save as default* makes that panel set what *Restore default* returns to.

## Troubleshooting

| symptom | cause | fix |
|---|---|---|
| panel stays black | agent thinks it is a WTR MAX (`type=1`) | `fix_config.py` sets `type=2` |
| it keeps jumping back to the vendor dashboard | `mianban` rotation list still populated, and the 8 built-in `diy` panels are still theirs | guard clears `mianban` and rewrites `diy` |
| new image does not appear | the agent caches panels at start-up | restart it (`restart_cmd`) |
| image appears shifted / garbled | agent left in a bad state after many rapid pushes | restart the agent; it does a clean full repaint |

## Notes on assets

* No vendor binaries, fonts or game artwork are included. Bring your own images.
* MIT licensed code. AOOSTAR-X is AOOSTAR's software; DDLC and its characters
  belong to Team Salvato — respect their fan-work guidelines if you publish
  screenshots.

## License

MIT — see [LICENSE](LICENSE).

---

## 中文说明

把 AOOSTAR GEM12 机箱正面那块「没什么用」的 960×376 小屏，变成自己的副屏：
选一张图 → 选版式 → 像换头像一样拖动/缩放裁切 → 上屏，左上角实时显示时间、CPU 温度、CPU 占用和内存。

**三种版式**：圆角照片框 / 整屏铺满（左侧自动压暗保证文字可读）/ 背景图 + 照片框（背景和前景分开传）。

**为什么要 `host/fix_config.py`**：AOOSTAR 自带的 Linux 代理有两个坑——
1. 默认把屏当成 WTR MAX（`type=1`），在 GEM12 上直接黑屏，必须改成 `type=2`；
2. 它会在自定义面板之间插播自带性能看板（`mianban` 轮播列表），清空并把内置 `diy` 面板改写成当前图，才不会"时不时跳回去"。

**安装**：
```bash
# 1) 屏幕所在的机器（宿主）
sudo ./host/install.sh /root/AOOSTAR-X-linux 60

# 2) 能访问 5123 端口的任意机器（Web 界面）
pip install -r webui/requirements.txt
cp config.example.json config.json    # 按需修改
python3 webui/app.py                  # http://0.0.0.0:5124
```

**中文标签需要中文字体**：`apt install fonts-noto-cjk`（或在 `config.json` 的 `fonts` 里指定字体路径），否则中文会变成方块。

**本仓库不包含**：AOOSTAR 的任何二进制/字体、DDLC 的图片素材。协议细节见 [docs/protocol.md](docs/protocol.md)。
