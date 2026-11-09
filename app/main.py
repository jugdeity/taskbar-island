import threading
import time
import winreg
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from . import clash, cover, db, lyric, media
from . import quota as quota_src

app = FastAPI()
db.init()


_quota_cache = []


def _quota_loop():
    # 后台刷新额度（查进程/请求接口较慢），接口直接返回缓存，面板弹出不再卡顿
    global _quota_cache
    while True:
        try:
            on = quota_src.running()
            real = {q["key"]: q for q in [quota_src.claude(), quota_src.codex()] if q}
            _quota_cache = [real.get(k, {"key": k, "name": k.capitalize(), "h5": None, "wk": None}) for k in ("claude", "codex") if k in on]
        except Exception:
            pass
        time.sleep(5)


@app.on_event("startup")
def _start():
    clash.start()
    threading.Thread(target=_quota_loop, daemon=True).start()


@app.get("/api/media")
async def get_media():
    m = await media.info()
    if m:
        m["liked"] = db.is_liked(m["title"], m["artist"])
        m["cover"] = cover.get(m["title"], m["artist"])
        m["lyric"], m["lyric_dur"], m["lyric_at"] = lyric.current(m["title"], m["artist"], m["playing"])
    return m


@app.post("/api/media/{action}")
async def control(action: str):
    if action not in ("toggle", "next", "prev"):
        raise HTTPException(400)
    return {"ok": await media.control(action)}


@app.get("/api/theme")
def theme():
    # 任务栏跟随“Windows 模式”(SystemUsesLightTheme)，所以读这一项
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
    try:
        light = winreg.QueryValueEx(key, "SystemUsesLightTheme")[0] == 1
    except OSError:
        light = False
    return {"light": light}


@app.get("/api/volume")
async def get_volume():
    return media.volume()


@app.post("/api/volume")
async def set_volume(delta: int = 0, mute: bool = False, level: int | None = None):
    return media.volume(delta=delta or None, mute=mute, level=level)


@app.post("/api/like")
async def like():
    m = await media.info()
    if not m:
        raise HTTPException(404)
    return {"liked": db.toggle_like(m["title"], m["artist"])}


@app.get("/api/quota")
def quota():
    return _quota_cache


@app.get("/api/clash")
def clash_stats():
    return clash.stats()


@app.get("/api/haze")
def get_haze():
    return {"haze": int(db.get_setting("haze") or 45)}


@app.post("/api/haze")
def set_haze(v: int):
    db.set_setting("haze", max(0, min(100, v)))
    return get_haze()


@app.get("/api/card")
def get_card():
    v = db.get_setting("card")
    return {"card": 55 if v is None else int(v)}


@app.post("/api/card")
def set_card(v: int):
    db.set_setting("card", max(0, min(100, v)))
    return get_card()


app.mount("/", StaticFiles(directory=Path(__file__).parent.parent / "static", html=True))
