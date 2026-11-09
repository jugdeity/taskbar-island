"""Clash 流量统计：读本地控制接口的累计流量，按每月 28 日为周期累加，套餐总量 1 TB。

Clash Verge Rev 默认只开命名管道（\\\\.\\pipe\\verge-mihomo-*），也兼容普通 external-controller 的 HTTP 接口。
内核只给“自启动以来”的累计值，所以这里每 5 秒记一次增量，自行累计到周期/今日；内核重启（累计值变小）按新值计入。
"""
import json
import os
import threading
import time
import urllib.request
from datetime import date

from . import db

TOTAL = 1024 ** 4        # 套餐总量 1 TB
RESET_DAY = 28           # 每月 28 日重置
HTTP = ("http://127.0.0.1:9097", "set-your-secret")  # 无管道时的备用：地址, secret


def _pipe_totals():
    names = [n for n in os.listdir("\\\\.\\pipe") if "mihomo" in n.lower() and "service" not in n.lower()]
    if not names:
        raise OSError("no pipe")
    with open("\\\\.\\pipe\\" + names[0], "r+b", buffering=0) as f:
        f.write(b"GET /traffic HTTP/1.1\r\nHost: mihomo\r\nConnection: close\r\n\r\n")
        raw = f.read(4096).decode("utf-8", "ignore")
    return json.loads(raw[raw.index("{"):raw.rindex("}") + 1])


def _http_totals():
    req = urllib.request.Request(HTTP[0] + "/connections", headers={"Authorization": "Bearer " + HTTP[1]})
    d = json.loads(urllib.request.urlopen(req, timeout=3).read())
    return {"upTotal": d["uploadTotal"], "downTotal": d["downloadTotal"]}


def totals():
    for fn in (_pipe_totals, _http_totals):
        try:
            d = fn()
            return d["upTotal"], d["downTotal"]
        except Exception:
            continue
    return None


def cycle_start(today=None):
    t = today or date.today()
    if t.day >= RESET_DAY:
        return date(t.year, t.month, RESET_DAY)
    y, m = (t.year, t.month - 1) if t.month > 1 else (t.year - 1, 12)
    return date(y, m, RESET_DAY)


def next_reset(today=None):
    s = cycle_start(today)
    y, m = (s.year, s.month + 1) if s.month < 12 else (s.year + 1, 1)
    return date(y, m, RESET_DAY)


def _num(key):
    return int(db.get_setting(key) or 0)


_alive = False


def poll():
    global _alive
    cur = totals()
    _alive = cur is not None
    if cur is None:
        return False
    up, down = cur
    lu, ld = db.get_setting("clash_last_up"), db.get_setting("clash_last_down")
    if lu is not None:
        du = up - int(lu) if up >= int(lu) else up
        dd = down - int(ld) if down >= int(ld) else down
        if cycle_start().isoformat() != db.get_setting("clash_cycle"):  # 新周期：清零
            db.set_setting("clash_cycle", cycle_start().isoformat())
            db.set_setting("clash_up", 0)
            db.set_setting("clash_down", 0)
        if date.today().isoformat() != db.get_setting("clash_day"):     # 新的一天：今日清零
            db.set_setting("clash_day", date.today().isoformat())
            db.set_setting("clash_today", 0)
        db.set_setting("clash_up", _num("clash_up") + du)
        db.set_setting("clash_down", _num("clash_down") + dd)
        db.set_setting("clash_today", _num("clash_today") + du + dd)
    else:  # 首次运行：只记基线，从现在开始统计
        db.set_setting("clash_cycle", cycle_start().isoformat())
        db.set_setting("clash_day", date.today().isoformat())
    db.set_setting("clash_last_up", up)
    db.set_setting("clash_last_down", down)
    return True


def stats():
    if not _alive:  # 由后台轮询维护，接口不再现场读管道（读一次要约 1 秒）
        return None
    up, down = _num("clash_up"), _num("clash_down")
    used = up + down
    nr = next_reset()
    return {"up": up, "down": down, "used": used, "total": TOTAL, "left": max(TOTAL - used, 0),
            "percent": round(used / TOTAL * 100), "today": _num("clash_today"),
            "reset": f"{nr.month}/{nr.day} 重置"}


def loop():
    while True:
        try:
            poll()
        except Exception:
            pass
        time.sleep(5)


def start():
    threading.Thread(target=loop, daemon=True).start()
