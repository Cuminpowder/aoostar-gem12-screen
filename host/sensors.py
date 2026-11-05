#!/usr/bin/env python3
"""Minimal sensor writer for asterctl (no vendor dependencies).

Writes the three values our panel needs, in asterctl's "label: value" format:

    cpu_temperature: 47
    cpu_percent: 12
    memory_usage: 43

argv: <output file> [interval seconds]
"""
import os
import sys
import time

OUT = sys.argv[1] if len(sys.argv) > 1 else "/run/aster/sensors.txt"
INTERVAL = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0


def cpu_times():
    with open("/proc/stat") as f:
        parts = f.readline().split()[1:]
    idle = int(parts[3]) + int(parts[4])
    total = sum(int(x) for x in parts)
    return idle, total


def cpu_temp():
    base = "/sys/class/hwmon"
    for hw in sorted(os.listdir(base)):
        try:
            name = open(os.path.join(base, hw, "name")).read().strip()
        except OSError:
            continue
        if name in ("k10temp", "zenpower", "coretemp", "it87"):
            for f in sorted(os.listdir(os.path.join(base, hw))):
                if f.startswith("temp") and f.endswith("_input"):
                    try:
                        v = int(open(os.path.join(base, hw, f)).read()) / 1000.0
                    except OSError:
                        continue
                    if 0 < v < 120:
                        return v
    return 0.0


def mem_usage():
    info = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, _, v = line.partition(":")
            info[k] = int(v.split()[0])
    total = info.get("MemTotal", 1)
    avail = info.get("MemAvailable", 0)
    return (1 - avail / total) * 100


def main():
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    i0, t0 = cpu_times()
    last_temp = 0.0
    while True:
        time.sleep(INTERVAL)
        try:
            i1, t1 = cpu_times()
            d_total = max(1, t1 - t0)
            busy = 100.0 * (1 - (i1 - i0) / d_total)
            i0, t0 = i1, t1
            if int(time.time()) % 10 == 0:
                last_temp = cpu_temp() or last_temp
            now = time.localtime()
            lines = [
                f"DATE_h_m_2: {now.tm_hour:02d}:{now.tm_min:02d}",
                f"DATE_y_m_d_3: {now.tm_year}/{now.tm_mon:02d}/{now.tm_mday:02d}",
                f"cpu_temperature: {last_temp:.0f}",
                f"cpu_percent: {busy:.0f}",
                f"memory_usage: {mem_usage():.0f}",
            ]
            # 原地写（不要 rename）：asterctl 用 inotify 盯这个 inode，
            # 原子替换会换 inode，watcher 就再也收不到事件了。
            with open(OUT, "r+") as f:
                f.seek(0)
                f.truncate()
                f.write("\n".join(lines) + "\n")
        except Exception as e:      # keep running no matter what
            print("sensor error:", e, file=sys.stderr)


if __name__ == "__main__":
    main()
