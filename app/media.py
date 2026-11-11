"""读取/控制播放器。

QQ音乐不向系统注册媒体会话(SMTC)，因此单独处理：
- 歌曲：读 QQ音乐隐藏窗口 QQMusic_Daemon_Wnd 的标题（"歌名 - 歌手"）
- 播放状态：QQMusic.exe 的音频会话处于 Active 且有电平
- 控制：发送键盘媒体键（播放/暂停、上一首、下一首）
其他播放器走 SMTC。
"""
import asyncio
import ctypes
import os
import threading
import time
import winreg

import comtypes
from pycaw.pycaw import AudioUtilities, IAudioMeterInformation
from winrt.windows.media.control import (
    GlobalSystemMediaTransportControlsSessionManager as Manager,
    GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status,
)

user32 = ctypes.windll.user32
user32.FindWindowW.restype = ctypes.c_void_p
user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
VK = {"toggle": 0xB3, "next": 0xB0, "prev": 0xB1}


def _qq_title():
    h = user32.FindWindowW("QQMusic_Daemon_Wnd", None)
    if not h:
        return None
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(h, buf, 512)
    t = buf.value.strip()
    return t if " - " in t else None


def _qq_running():
    return bool(user32.FindWindowW("QQMusic_Daemon_Wnd", None))


def _qq_exe():
    """从卸载注册表里找 QQ 音乐的安装位置。"""
    base = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    for root, sub in ((winreg.HKEY_LOCAL_MACHINE, base),
                      (winreg.HKEY_LOCAL_MACHINE, base.replace("Software\\", "Software\\WOW6432Node\\")),
                      (winreg.HKEY_CURRENT_USER, base)):
        try:
            with winreg.OpenKey(root, sub) as k:
                for i in range(winreg.QueryInfoKey(k)[0]):
                    try:
                        with winreg.OpenKey(k, winreg.EnumKey(k, i)) as s:
                            if winreg.QueryValueEx(s, "DisplayName")[0] in ("QQ音乐", "QQMusic"):
                                exe = os.path.join(winreg.QueryValueEx(s, "InstallLocation")[0], "QQMusic.exe")
                                if os.path.exists(exe):
                                    return exe
                    except OSError:
                        continue
        except OSError:
            continue
    return None


def _qq_sessions():
    """QQMusic.exe 的音频会话。已退出进程留下的过期会话取进程名会抛异常，
    必须逐个跳过——否则排在它后面的 QQ 音乐会话永远读不到。"""
    out = []
    try:
        sessions = AudioUtilities.GetAllSessions()
    except Exception:
        return out
    for s in sessions:
        try:
            if s.Process and s.Process.name().lower() == "qqmusic.exe":
                out.append(s)
        except Exception:
            continue
    return out


_last_sound = 0.0


def _qq_playing():
    """会话 Active 且有电平 = 播放中。暂停后会话还会保持 Active 十几秒，所以不能只看状态；
    电平取的是应用音量之前的值，静音/音量为 0 时照样有读数。
    歌曲里短暂的无声段落：2 秒内出过声仍算播放中，避免图标闪跳。"""
    global _last_sound
    for s in _qq_sessions():
        try:
            if s.State != 1:  # 1 = AudioSessionStateActive
                continue
            m = s._ctl.QueryInterface(IAudioMeterInformation)
            for _ in range(4):
                if m.GetPeakValue() > 0.0005:
                    _last_sound = time.time()
                    return True
                time.sleep(0.03)
        except Exception:
            continue
    return time.time() - _last_sound < 2


_smtc_ok = True


async def _wait(op):
    """等 WinRT 异步操作，最多 1 秒。有的机器上它永远不完成（取消也会卡住），
    所以不用 wait_for；超时后不再尝试 SMTC。"""
    global _smtc_ok
    task = asyncio.ensure_future(op)
    done, _ = await asyncio.wait({task}, timeout=1)
    if not done:
        _smtc_ok = False
        return None
    return task.result()


async def _session():
    if not _smtc_ok:
        return None
    mgr = await _wait(Manager.request_async())
    return mgr.get_current_session() if mgr else None


async def info():
    t = _qq_title()
    if t:
        title, artist = t.rsplit(" - ", 1)
        return {"app": "QQMusic", "title": title.strip(), "artist": artist.strip(), "playing": _qq_playing()}
    s = await _session()
    if not s:
        return None
    p = await _wait(s.try_get_media_properties_async())
    if not p:
        return None
    return {
        "app": s.source_app_user_model_id,
        "title": p.title,
        "artist": p.artist,
        "playing": s.get_playback_info().playback_status == Status.PLAYING,
    }


def _qq_volumes():
    return [s.SimpleAudioVolume for s in _qq_sessions()]


_last = {"level": 100, "muted": False}
_dirty = False  # QQ 音乐没出声时调过音量，等它的音频会话出现后再应用


def volume(delta=None, mute=None, level=None):
    """读取/调节 QQ 音乐的应用音量（音量合成器里那一项），不动系统主音量。
    delta 为百分比增量；level 为 0~100 的绝对值；mute=True 时切换静音。"""
    global _dirty
    vs = _qq_volumes()
    if vs and not _dirty:
        _last["level"] = round(vs[0].GetMasterVolume() * 100)
        _last["muted"] = bool(vs[0].GetMute())
    if delta is not None:
        level = _last["level"] + delta
    change = level is not None or bool(mute)
    if level is not None:
        _last["level"] = min(100, max(0, level))
        if _last["level"] > 0:
            _last["muted"] = False
    if mute:
        _last["muted"] = not _last["muted"]
    if change or _dirty:
        for v in vs:
            v.SetMasterVolume(_last["level"] / 100, None)
            v.SetMute(int(_last["muted"]), None)
        _dirty = not vs
    return dict(_last)


def _key(action):
    vk = VK[action]
    user32.keybd_event(vk, 0, 1, 0)
    user32.keybd_event(vk, 0, 3, 0)


_launching = False


def _autoplay():
    """QQ 音乐启动后，等它载入歌曲再自动按一次播放。"""
    global _launching
    comtypes.CoInitialize()
    try:
        end = time.time() + 30
        while time.time() < end and not _qq_title():
            time.sleep(0.5)
        time.sleep(1.5)
        if _qq_running() and not _qq_playing():
            _key("toggle")
    finally:
        _launching = False


async def control(action):
    # QQ 音乐没开时，点播放键直接打开它并自动开始播放
    global _launching
    if action == "toggle" and not _qq_running():
        if _launching:
            return True
        exe = _qq_exe()
        if exe:
            _launching = True
            os.startfile(exe)
            threading.Thread(target=_autoplay, daemon=True).start()
            return True
    if _qq_title():
        _key(action)
        return True
    s = await _session()
    if not s:
        return False
    fn = {
        "toggle": s.try_toggle_play_pause_async,
        "next": s.try_skip_next_async,
        "prev": s.try_skip_previous_async,
    }[action]
    return bool(await _wait(fn()))
