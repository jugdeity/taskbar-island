"""歌词：QQ 音乐接口取 LRC（后台线程 + 缓存）。QQ 音乐不对外提供播放进度，
所以按「换歌时从 0 开始、出声时累计」估算当前进度。"""
import base64
import json
import re
import threading
import time
import urllib.parse
import urllib.request

_H = {"User-Agent": "Mozilla/5.0", "Referer": "https://y.qq.com/"}
_cache = {}      # (title, artist) -> [(秒, 歌词)]；[] 表示没有
_pending = set()
_state = {"key": None, "pos": 0.0, "t": 0.0}
_SKIP = re.compile(r"^(词|曲|作词|作曲|编曲|制作人|监制|混音|录音|母带|OP|SP)\s*[:：]")


def _req(url, data=None):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, data=data, headers=_H), timeout=8).read())


def _parse(lrc):
    out = []
    for line in lrc.splitlines():
        m = re.match(r"^((?:\[\d+:\d+(?:\.\d+)?\])+)(.*)$", line.strip())
        if not m:
            continue
        text = m.group(2).strip()
        if not text or _SKIP.match(text):
            continue
        for mm, ss in re.findall(r"\[(\d+):(\d+(?:\.\d+)?)\]", m.group(1)):
            out.append((int(mm) * 60 + float(ss), text))
    out.sort()
    if out and " - " in out[0][1] and out[0][0] < 1:  # 首行「歌名 - 歌手」不是歌词
        out.pop(0)
    return out


def _fetch(key):
    title, artist = key
    lines = []
    try:
        q = urllib.parse.quote(f"{title} {artist}")
        songs = _req(f"https://c.y.qq.com/soso/fcgi-bin/client_search_cp?w={q}&format=json&n=5&p=1")["data"]["song"]["list"]
        if songs:
            hit = next((s for s in songs if s["songname"].strip().lower() == title.strip().lower()), songs[0])
            body = json.dumps({"comm": {"ct": 24, "cv": 0}, "req": {
                "module": "music.musichallSong.PlayLyricInfo", "method": "GetPlayLyricInfo",
                "param": {"songMID": hit["songmid"], "songID": 0}}}).encode()
            lrc = _req("https://u.y.qq.com/cgi-bin/musicu.fcg", body)["req"]["data"].get("lyric", "")
            if lrc:
                lines = _parse(base64.b64decode(lrc).decode("utf-8", "replace"))
    except Exception:
        pass
    _cache[key] = lines
    _pending.discard(key)


def current(title, artist, playing):
    """返回 (当前歌词, 本句时长, 本句已播秒数)；没有则歌词为空串。每次轮询调用一次以累计播放进度。"""
    key = (title or "", artist or "")
    now = time.time()
    if _state["key"] != key:
        _state.update(key=key, pos=0.0, t=now)
    else:
        dt = now - _state["t"]
        if playing and dt < 3:
            _state["pos"] += dt
        _state["t"] = now
    if key not in _cache:
        if key not in _pending and key[0]:
            _pending.add(key)
            threading.Thread(target=_fetch, args=(key,), daemon=True).start()
        return "", 0, 0
    lines, pos = _cache[key], _state["pos"] + 0.3
    for i, (t, text) in enumerate(lines):
        if t <= pos and (i + 1 == len(lines) or lines[i + 1][0] > pos):
            dur = lines[i + 1][0] - t if i + 1 < len(lines) else 5.0
            return text, dur, pos - t   # 歌词、这句持续秒数、已播放秒数
    return "", 0, 0
