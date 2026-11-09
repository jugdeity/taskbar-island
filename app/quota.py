"""真实额度来源。"""
import ctypes
import json
from ctypes import wintypes
import subprocess
import time
import urllib.request
from datetime import datetime
from pathlib import Path

CODEX_SESSIONS = Path.home() / ".codex" / "sessions"
CLAUDE_CRED = Path.home() / ".claude" / ".credentials.json"
_LAST = Path(__file__).with_name("claude_last.json")  # 上次成功的额度，重启后限流/断网时先用它
try:
    _claude_cache = {"t": 0, "v": json.loads(_LAST.read_text(encoding="utf-8"))}
except Exception:
    _claude_cache = {"t": 0, "v": None}
_TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"  # Claude Code 的 OAuth 客户端


def _read_cred():
    return json.loads(CLAUDE_CRED.read_text(encoding="utf-8"))


def _refresh_token():
    """访问令牌过期时用 refresh token 续期并写回凭据文件，这样不必再手动 /login。
    先重读文件：若 Claude Code 已经自己续过期就直接用，避免两边同时轮换 refresh token。"""
    cred = _read_cred()
    o = cred["claudeAiOauth"]
    if o["expiresAt"] / 1000 - time.time() > 120:
        return o["accessToken"]
    body = json.dumps({"grant_type": "refresh_token", "refresh_token": o["refreshToken"], "client_id": _CLIENT_ID}).encode()
    req = urllib.request.Request(_TOKEN_URL, data=body, headers={"Content-Type": "application/json"})
    r = json.loads(urllib.request.urlopen(req, timeout=15).read())
    o["accessToken"] = r["access_token"]
    o["refreshToken"] = r.get("refresh_token", o["refreshToken"])
    o["expiresAt"] = int((time.time() + r["expires_in"]) * 1000)
    tmp = CLAUDE_CRED.with_suffix(".tmp")
    tmp.write_text(json.dumps(cred), encoding="utf-8")
    tmp.replace(CLAUDE_CRED)  # 原子替换，立即落盘
    return o["accessToken"]


def claude():
    """用 Claude Code 的 OAuth 令牌查询订阅用量（5 小时 + 每周），缓存 60 秒。"""
    if time.time() - _claude_cache["t"] < 60:
        return _claude_cache["v"]
    _claude_cache["t"] = time.time()
    try:
        token = _refresh_token()
        req = urllib.request.Request("https://api.anthropic.com/api/oauth/usage", headers={
            "Authorization": f"Bearer {token}", "anthropic-beta": "oauth-2025-04-20"})
        d = json.loads(urllib.request.urlopen(req, timeout=10).read())
    except Exception as e:
        Path(__file__).with_name("quota_err.log").write_text(time.ctime() + " " + repr(e) + "\n", encoding="utf-8")
        return _claude_cache["v"]  # 未登录/网络失败：沿用上次结果
    p, w = d.get("five_hour") or {}, d.get("seven_day") or {}
    ts = lambda s: datetime.fromisoformat(s).timestamp() if s else 0
    used = round(p.get("utilization") or 0)
    reset = f"5h {used}%，{_left(ts(p.get('resets_at')))}"
    if w:
        reset += f"；周 {round(w.get('utilization') or 0)}%，{_left(ts(w.get('resets_at')))}"
    _claude_cache["v"] = {"key": "claude", "name": "Claude", "used": used, "reset": reset,
                          "h5": {"used": used, "left": _left(ts(p.get("resets_at")))},
                          "wk": {"used": round(w.get("utilization") or 0), "left": _left(ts(w.get("resets_at")))} if w else None}
    try:
        _LAST.write_text(json.dumps(_claude_cache["v"], ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return _claude_cache["v"]


# 每个 agent 对应的进程名（不区分大小写，精确匹配）
PROCS = {"claude": {"claude"}, "codex": {"codex"}, "clash": {"clash-verge", "verge-mihomo", "verge-mihomo-alpha", "mihomo", "clash", "clash-win64", "clash-meta"}}
# 网页版 agent：按浏览器窗口标题识别（只能识别各窗口当前显示的标签页）
TITLES = {}  # 例：{"xxx": "Xxx"}，窗口标题以此开头即视为在用


def _window_titles():
    u = ctypes.windll.user32
    titles = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _):
        if u.IsWindowVisible(h):
            buf = ctypes.create_unicode_buffer(512)
            u.GetWindowTextW(h, buf, 512)
            titles.append(buf.value)
        return True

    u.EnumWindows(cb, 0)
    return titles


def running():
    """返回当前正在使用的 agent key 集合。"""
    out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True,
                         creationflags=subprocess.CREATE_NO_WINDOW).stdout
    names = {line.split('","')[0].strip('"').lower().removesuffix(".exe") for line in out.splitlines() if line}
    on = {k for k, ps in PROCS.items() if names & ps}
    titles = _window_titles()
    on |= {k for k, t in TITLES.items() if any(x.startswith(t + " ") for x in titles)}
    return on


def _left(ts):
    s = int(ts - time.time())
    if s <= 0:
        return "已重置"
    if s >= 86400:
        return f"{s // 86400}天{s % 86400 // 3600}h后重置"
    return f"{s // 3600}h{s % 3600 // 60}m后重置"


def codex():
    """读取最近一次 Codex 会话日志里的 rate_limits（5 小时窗口 + 每周窗口）。"""
    files = sorted(CODEX_SESSIONS.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    for f in files[:5]:
        for line in reversed(f.read_text(encoding="utf-8", errors="ignore").splitlines()):
            if '"rate_limits"' not in line:
                continue
            rl = json.loads(line).get("payload", {}).get("rate_limits") or {}
            p, w = rl.get("primary"), rl.get("secondary")
            if not p:
                continue
            # 窗口已过期则用量归零
            used = 0 if p["resets_at"] < time.time() else round(p["used_percent"])
            reset = f"5h {used}%，{_left(p['resets_at'])}"
            wk = None
            if w:
                wused = 0 if w["resets_at"] < time.time() else round(w["used_percent"])
                reset += f"；周 {wused}%，{_left(w['resets_at'])}"
                wk = {"used": wused, "left": _left(w["resets_at"])}
            return {"key": "codex", "name": "Codex", "used": used, "reset": reset,
                    "h5": {"used": used, "left": _left(p["resets_at"])}, "wk": wk}
    return None
