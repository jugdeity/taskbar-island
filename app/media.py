"""读取/控制播放器。

QQ音乐不向系统注册媒体会话(SMTC)，因此单独处理：
- 歌曲：读 QQ音乐隐藏窗口 QQMusic_Daemon_Wnd 的标题（"歌名 - 歌手"）
- 播放状态：用系统音频电平判断 QQMusic.exe 是否在出声
- 控制：发送键盘媒体键（播放/暂停、上一首、下一首）
其他播放器走 SMTC。
"""
import ctypes
import os
import time
import winreg

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


def _qq_playing():
    try:
        for s in AudioUtilities.GetAllSessions():
            if s.Process and s.Process.name().lower() == "qqmusic.exe":
                m = s._ctl.QueryInterface(IAudioMeterInformation)
                for _ in range(4):
                    if m.GetPeakValue() > 0.0005:
                        return True
                    time.sleep(0.03)
    except Exception:
        pass
    return False


async def _session():
    mgr = await Manager.request_async()
    return mgr.get_current_session()


async def info():
    t = _qq_title()
    if t:
        title, artist = t.rsplit(" - ", 1)
        return {"app": "QQMusic", "title": title.strip(), "artist": artist.strip(), "playing": _qq_playing()}
    s = await _session()
    if not s:
        return None
    p = await s.try_get_media_properties_async()
    return {
        "app": s.source_app_user_model_id,
        "title": p.title,
        "artist": p.artist,
        "playing": s.get_playback_info().playback_status == Status.PLAYING,
    }


def _vol():
    return AudioUtilities.GetSpeakers().EndpointVolume


def volume(delta=None, mute=None):
    """读取/调节系统主音量。delta 为百分比增量；mute=True 时切换静音。"""
    v = _vol()
    if delta is not None:
        level = min(1.0, max(0.0, v.GetMasterVolumeLevelScalar() + delta / 100))
        v.SetMasterVolumeLevelScalar(level, None)
        if level > 0:
            v.SetMute(0, None)
    if mute:
        v.SetMute(0 if v.GetMute() else 1, None)
    return {"level": round(v.GetMasterVolumeLevelScalar() * 100), "muted": bool(v.GetMute())}


async def control(action):
    # QQ 音乐没开时，点播放键直接打开它
    if action == "toggle" and not _qq_running():
        exe = _qq_exe()
        if exe:
            os.startfile(exe)
            return True
    if _qq_title():
        vk = VK[action]
        user32.keybd_event(vk, 0, 1, 0)
        user32.keybd_event(vk, 0, 3, 0)
        return True
    s = await _session()
    if not s:
        return False
    fn = {
        "toggle": s.try_toggle_play_pause_async,
        "next": s.try_skip_next_async,
        "prev": s.try_skip_previous_async,
    }[action]
    return await fn()
