"""按“歌名 + 歌手”查封面：QQ 音乐搜索接口优先，iTunes Search 兜底。结果缓存，后台线程查询不阻塞轮询。"""
import json
import threading
import urllib.parse
import urllib.request

_cache = {}      # (title, artist) -> 封面 URL；"" 表示没查到
_pending = set()


def _get(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", **(headers or {})})
    return json.loads(urllib.request.urlopen(req, timeout=8).read())


def _qq(title, artist):
    q = urllib.parse.quote(f"{title} {artist}")
    d = _get(f"https://c.y.qq.com/soso/fcgi-bin/client_search_cp?w={q}&format=json&n=5&p=1",
             {"Referer": "https://y.qq.com/"})
    songs = d["data"]["song"]["list"]
    if not songs:
        return ""
    hit = next((s for s in songs if s["songname"].strip().lower() == title.strip().lower()), songs[0])
    mid = hit.get("albummid")
    return f"https://y.gtimg.cn/music/photo_new/T002R300x300M000{mid}.jpg" if mid else ""


def _itunes(title, artist):
    q = urllib.parse.quote(f"{title} {artist}")
    d = _get(f"https://itunes.apple.com/search?term={q}&entity=song&limit=1")
    r = d.get("results") or []
    return r[0]["artworkUrl100"].replace("100x100", "300x300") if r else ""


def _fetch(key):
    url = ""
    for fn in (_qq, _itunes):
        try:
            url = fn(*key)
        except Exception:
            url = ""
        if url:
            break
    _cache[key] = url
    _pending.discard(key)


def get(title, artist):
    """立即返回已缓存的封面 URL（没有则返回 None 并在后台开始查询）。"""
    key = (title or "", artist or "")
    if key in _cache:
        return _cache[key] or None
    if key not in _pending and key[0]:
        _pending.add(key)
        threading.Thread(target=_fetch, args=(key,), daemon=True).start()
    return None
