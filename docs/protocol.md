# AOOSTAR GEM12 sub-screen — protocol notes

Everything below was derived by observing a GEM12 running AOOSTAR's own Linux
agent (`AOOSTAR-X`, a PyInstaller bundle that is **not** redistributed here).
No vendor binaries or artwork are included in this repository.

## Hardware

| what | how it shows up |
|---|---|
| Front sub-screen | `0416:90a1 Winbond Electronics — USB Virtual COM` → `/dev/ttyACM0` (cdc_acm) |
| Fingerprint button | `3274:8012 MicroarrayTechnology MAFP General Device` — **not** the screen |
| Panel | 960 × 376 px, RGB565 |
| Link | full speed USB (12 Mbps), bulk out (0x03) / bulk in (0x83) |

The MCU keeps its own framebuffer. The agent therefore only streams the rows
that actually changed, which is why the traffic volume is bursty.

## Wire format

Every packet starts with a 12-byte header:

```
aa 55 aa 55 | cmd (u32 LE) | offset (u32 LE) | payload...
```

* `cmd = 8` — framebuffer bytes. `offset` is the byte offset inside one frame
  (`960 * 376 * 2 = 721,920` bytes). The agent writes ~47 payload bytes per
  `write(2)` call (about 190 KB/s); the offset increases monotonically and wraps
  to 0 when the next frame starts.
* `cmd = 5` — parameters (16-byte payload, observed at start-up).
* `cmd = 6` — status poll (8 bytes).

Pixels are little-endian RGB565: `r = (v >> 11) & 0x1f`, `g = (v >> 5) & 0x3f`,
`b = v & 0x1f`.

Because only dirty regions are sent, you cannot reconstruct a full frame from a
short capture unless you first force a full repaint (e.g. push an all-white
panel, then your real one).

## Vendor agent internals worth knowing

* Web UI on `:5123` (Flask, default `admin` / `123456`), state in
  `Monitor3.json` and `custom_panels.json`, images in `img/<uuid>.jpg`.
* `POST /save_custom_panels` with `{"panels":[{"id","name","checked","imgData","sensor":[...]}]}`
  is the supported way to install a panel; `imgData` is a `data:image/jpeg;base64,…` URL.
* Panels are re-read **only at start-up** — restart the service after pushing.
* `setup.type`: `1` = WTR MAX, `2` = GEM12. Wrong value ⇒ black panel.
* `mianban`: list of built-in panels that keep rotating in between your custom
  ones. Clear it, otherwise the vendor dashboard pops back up every so often.
* `diy`: the 8 built-in panels (`default_N_index.jpg` / `default_N_hdd.jpg`).
  Rewrite these entries to make the "system" panels render your own image.
* Sensor element geometry: `x, y` is the **top-left of the element box**,
  `width`/`height` size that box, text is centred inside it according to
  `textAlign`, and `fontSize` is in pixels. To centre text at `(cx, cy)`:
  `x = cx - w/2`, `y = cy - h/2 + 2`.

## Capturing traffic yourself

```bash
sudo modprobe usbmon
PID=$(fuser /dev/ttyACM0 2>/dev/null | tr -d ' ')
sudo strace -f -p "$PID" -e trace=write -xx -s 300 -o /tmp/cap.log &
# …trigger a repaint (restart the agent, or push a new panel)…
sudo kill %1
python3 tools/decode_capture.py /tmp/cap.log out.png
```
