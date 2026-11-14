"""V2Ray 流量统计：只读，不改 v2rayN / xray / sing-box 的任何配置。

v2rayN 开 TUN 时由 sing-box 接管全部流量，并开着 Clash 兼容接口（127.0.0.1:10814，无密码）；
xray 自带的统计 API 默认关闭，所以读 sing-box 的 /connections。每条连接带出站标记，只累计走节点（非 direct）的。
接口只给“当前存活连接”的累计字节，所以每秒轮询、按连接 id 算增量；连接在两次轮询之间关闭时，最后不到 1 秒的流量会漏计。
套餐与重置日同 Clash（1 TB，每月 28 日）。
"""
import json
import threading
import time
import urllib.request
from datetime import date

from . import db
from .clash import TOTAL, cycle_start, next_reset

API = "http://127.0.0.1:10814"
KEYS = ("v2ray_cycle", "v2ray_day", "v2ray_up", "v2ray_down", "v2ray_today")

_seen = None   # 连接 id -> (上传, 下载)；None = 刚启动，首轮只记基线，不计入
_last_t = 0
_speed = None  # (上行 B/s, 下行 B/s)；接口读不到时为 None，卡片隐藏
_st = None     # 累计值的内存副本，有变化就写回数据库


def _connections():
    d = json.loads(urllib.request.urlopen(API + "/connections", timeout=2).read())
    return d.get("connections") or []  # 没有连接时是 null


def _add(du, dd):
    global _st
    if _st is None:
        _st = {k: db.get_setting(k) for k in KEYS}
        for k in ("v2ray_up", "v2ray_down", "v2ray_today"):
            _st[k] = int(_st[k] or 0)
    cyc, day = cycle_start().isoformat(), date.today().isoformat()
    changed = bool(du or dd)
    if _st["v2ray_cycle"] != cyc:  # 新周期：清零
        _st.update(v2ray_cycle=cyc, v2ray_up=0, v2ray_down=0)
        changed = True
    if _st["v2ray_day"] != day:    # 新的一天：今日清零
        _st.update(v2ray_day=day, v2ray_today=0)
        changed = True
    _st["v2ray_up"] += du
    _st["v2ray_down"] += dd
    _st["v2ray_today"] += du + dd
    if changed:
        with db.conn() as c:
            c.executemany("INSERT OR REPLACE INTO setting VALUES (?,?)", [(k, str(v)) for k, v in _st.items()])


def poll():
    global _seen, _last_t, _speed
    try:
        conns = _connections()
    except Exception:
        _speed = None
        return
    now = time.monotonic()
    cur = {c["id"]: (c["upload"], c["download"]) for c in conns if "direct" not in (c.get("chains") or [])}
    du = dd = 0
    if _seen is not None:
        for k, (u, d) in cur.items():
            pu, pd = _seen.get(k, (0, 0))  # 上一轮之后新建的连接：全部计入
            du += max(u - pu, 0)
            dd += max(d - pd, 0)
        dt = now - _last_t
        _speed = (du / dt, dd / dt)
    else:
        _speed = (0, 0)
    _seen, _last_t = cur, now
    _add(du, dd)


def stats():
    if _speed is None or _st is None:
        return None
    up, down = _st["v2ray_up"], _st["v2ray_down"]
    used = up + down
    nr = next_reset()
    return {"up": up, "down": down, "used": used, "total": TOTAL, "left": max(TOTAL - used, 0),
            "percent": round(used / TOTAL * 100), "today": _st["v2ray_today"],
            "reset": f"{nr.month}/{nr.day} 重置",
            "up_speed": round(_speed[0]), "down_speed": round(_speed[1])}


def loop():
    while True:
        try:
            poll()
        except Exception:
            pass
        time.sleep(1)


def start():
    threading.Thread(target=loop, daemon=True).start()
