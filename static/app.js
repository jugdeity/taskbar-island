const $ = id => document.getElementById(id);
const api = () => window.pywebview && window.pywebview.api;
const GB = 1024 ** 3;
const fmt = b => b >= 1024 ** 4 ? (b / 1024 ** 4).toFixed(2) + " TB" : b >= GB * 100 ? Math.round(b / GB) + " GB" : (b / GB).toFixed(1) + " GB";
const IC = {
  claude: `<img src="claude.svg" class="ic-claude">`,
  codex: `<svg viewBox="0 0 24 24" fill="none" stroke="#e5e7eb" stroke-width="2.6" stroke-linecap="round"><path d="M4 7l5 5-5 5M12 18h8"/></svg>`,
};
const COLOR = { claude: "#d97757", codex: "#e5e7eb" };

// 歌名：超出宽度时首尾相接循环滚动；只在换歌时重建，避免动画重置
let shownTitle = null;
function setTitle(text) {
  if (text === shownTitle) return;
  shownTitle = text;
  const el = $("title");
  el.classList.remove("roll");
  el.innerHTML = "<span></span>";
  el.firstChild.textContent = text;
  const w = el.firstChild.offsetWidth;
  if (w > el.clientWidth) {
    el.firstChild.textContent = text + "　　" + text + "　　";
    el.style.setProperty("--dur", (w / 25) + "s");
    el.classList.add("roll");
  }
}

let lockUntil = 0;
let shownCover = null;
function setCover(url) {
  if (url === shownCover) return;
  shownCover = url;
  const c = $("cover");
  c.style.backgroundImage = url ? `url("${url}")` : "";
  c.classList.toggle("has", !!url);
}

async function refreshMedia() {
  const m = await fetch("/api/media").then(r => r.json()).catch(() => null);
  if (!m) { setTitle("未在播放"); $("artist").textContent = "打开 QQ音乐"; setCover(null); $("pp").classList.add("paused"); return; }
  setTitle(m.title || "未知歌曲");
  $("artist").textContent = m.artist || "";
  $("artist").style.display = m.artist ? "" : "none";
  setCover(m.cover);
  if (Date.now() > lockUntil) $("pp").classList.toggle("paused", !m.playing);
}

document.querySelectorAll("[data-act]").forEach(b =>
  b.onclick = () => {
    if (b.dataset.act === "toggle") { $("pp").classList.toggle("paused"); lockUntil = Date.now() + 1500; }  // 先乐观切换，避免等轮询
    fetch("/api/media/" + b.dataset.act, { method: "POST" }).then(refreshMedia);
  });

// 面板：额度（只显示正在运行的软件）+ Clash 流量
const bar = (label, p, c, right) =>
  `<div class="bar" style="--p:${p};--c:${c}"><span>${label}</span><i><u></u></i><span>${right}</span></div>`;
function agentCard(q) {
  const c = COLOR[q.key], wk = q.wk, h5 = q.h5;
  const rows = (h5 ? bar("5小时", h5.used, c, `${h5.used}% · ${h5.left}`) : "") + (wk ? bar("本周", wk.used, c, `${wk.used}% · ${wk.left}`) : "");
  return `<div class="card"><div class="top"><div class="ring" style="--p:${wk ? wk.used : (h5 ? h5.used : 0)};--c:${c}"><span class="${q.key === "claude" ? "ic-white" : ""}">${IC[q.key]}</span></div>
    <div class="m"><b>${q.name}</b></div></div>${rows ? `<div class="bars">${rows}</div>` : `<small style="color:var(--sub)">暂无额度数据</small>`}</div>`;
}
function clashCard(s) {
  const tot = s.up + s.down;
  return `<div class="card"><div class="top"><div class="ring" style="--p:${s.percent};--c:#4cc9f0"><span class="ic-clash"><img src="clash.png"></span></div>
    <div class="m"><b>Clash 流量</b></div><small>已用 ${s.percent}% · ${s.reset}</small></div>
    <div class="nums"><div><small>今日</small><b>${fmt(s.today)}</b></div><div><small>本周期已用</small><b>${fmt(s.used)}</b></div><div><small>套餐 ${fmt(s.total)}</small><b>剩 ${fmt(s.left)}</b></div></div>
    <div class="bars">${bar("↑ 上传", (tot ? Math.round(s.up / tot * 100) : 0), "#4cc9f0", fmt(s.up))}${bar("↓ 下载", (tot ? Math.round(s.down / tot * 100) : 0), "#7b8cff", fmt(s.down))}</div></div>`;
}
async function refreshPanel() {
  const [q, c] = await Promise.all([
    fetch("/api/quota").then(r => r.json()).catch(() => []),
    fetch("/api/clash").then(r => r.json()).catch(() => null)]);
  $("cards").innerHTML = (q.length ? q.map(agentCard).join("") : "") +
    (c ? clashCard(c) : "") +
    (!q.length && !c ? `<div class="sec"><span>没有正在运行的软件</span></div>` : "");
}

// 雾化滑块
const setHaze = v => { document.documentElement.style.setProperty("--h", v / 100); $("hv").textContent = v + "%"; };
fetch("/api/haze").then(r => r.json()).then(d => { $("haze").value = d.haze; setHaze(d.haze); });
$("haze").oninput = e => setHaze(e.target.value);
$("haze").onchange = e => fetch("/api/haze?v=" + e.target.value, { method: "POST" });

// 跟随 Windows 浅色/深色模式
const refreshTheme = () => fetch("/api/theme").then(r => r.json())
  .then(t => document.documentElement.classList.toggle("dark", !t.light)).catch(() => {});
refreshTheme(); setInterval(refreshTheme, 2000);

// 展开：先撑开窗口，再播放「自下而上展开」动画；收起：动画播完再缩窗口
let closeTimer = 0;
function togglePanel() {
  const p = $("panel");
  clearTimeout(closeTimer);
  if (p.classList.contains("hidden")) {
    p.classList.remove("hidden");
    reportSize();
    setTimeout(() => p.classList.add("show"), 90);  // 等窗口撑开到位
  } else if (p.classList.contains("show")) {
    p.classList.remove("show");
    closeTimer = setTimeout(() => { p.classList.add("hidden"); reportSize(); }, 420);
  } else {  // 展开动画尚未开始就被再次点击
    p.classList.add("hidden"); reportSize();
  }
}

// 点击歌曲区展开/收起面板；按住拖动则沿任务栏移动
let down = null;
document.querySelectorAll(".drag").forEach(el => {
  el.onmousedown = e => {
    if (e.button !== 0) return;
    e.preventDefault();
    down = e.screenX;
    if (api()) api().drag_start();
  };
});
document.addEventListener("mouseup", e => {
  if (down !== null && Math.abs(e.screenX - down) < 4) {
    togglePanel();
  }
  down = null;
});

// 窗口高度跟随内容（面板向上展开，药丸始终贴在任务栏位置）
let lastH = 0;
function reportSize() {
  const h = Math.ceil($("root").getBoundingClientRect().height);
  if (h !== lastH && api()) { lastH = h; api().set_extra(h - 40); }
}
setInterval(reportSize, 150);

refreshMedia(); refreshPanel();
setInterval(refreshMedia, 1000);
setInterval(refreshPanel, 5000);
