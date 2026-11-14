# Taskbar Island

常驻 Windows 任务栏的灵动岛。

- Spotify / QQ音乐：实时显示歌名、歌手、专辑封面（QQ 音乐搜索优先，iTunes 兜底），上一首 / 播放暂停 / 下一首；两个都开着时显示正在播的那个（都在播显示后开始的）；都没开时点播放键会启动 Spotify 并自动播放；音量条只调 Spotify 的应用音量，不动系统音量和 QQ音乐
- 点击歌曲区展开玻璃面板：Claude / Codex 的 5 小时与每周额度（只显示正在运行的）、Clash 流量（每月 28 日重置，套餐 1 TB）、V2Ray 流量与实时上下行速度（同上套餐，见下文）、玻璃雾化滑块
- 逐像素透明的液态玻璃外观，跟随系统浅色/深色模式；可沿任务栏拖动，位置自动保存；随任务栏一起隐藏/显示

技术栈：Python + FastAPI + SQLite + HTML/CSS，pywebview 无边框窗口。

## 运行

```bash
pip install -r requirements.txt
```

双击 `start.vbs` 启动（无控制台窗口）。Claude 额度需要先用 Claude Code 登录（`claude` → `/login`）。

## V2Ray 流量

- 需要 v2rayN 开启 TUN 模式：此时 sing-box 接管全部流量，并开着无密码的 Clash 兼容接口 `127.0.0.1:10814`；读不到这个接口时卡片自动隐藏
- 只读，不改 v2rayN / xray / sing-box 的任何配置（v2rayN 自带的流量统计开关可以保持关闭）
- 每秒读一次连接列表，按连接累计走节点（非 direct）的流量，直连不计；连接在两次读取之间关闭时，最后不到 1 秒的流量会漏计
- 从灵动岛启动后开始累计，启动前已有连接的流量不计；本周期、今日用量存在 `island.db`
- 接口地址在 `app/v2ray.py` 的 `API`；套餐总量与重置日和 Clash 共用 `app/clash.py` 的 `TOTAL`、`RESET_DAY`

## 开机自启

```bash
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v TaskbarIsland /d "wscript.exe \"<项目路径>\start.vbs\"" /f
```
