from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


DEFAULT_STATUS = {
    "online": False,
    "screen": "face",
    "emotion": "happy",
    "message": "OnPlant",
    "sub_message": "Ready",
    "lux": 0,
    "temperature": 0,
    "humidity": 0,
    "soil_moisture": 0,
    "robot_state": "IDLE",
    "camera_visible": False,
    "updated_at": 0,
}

status = DEFAULT_STATUS.copy()
status_lock = threading.Lock()


HTML = r"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OnPlant Display</title>
  <style>
:root {
  --ink: #1f3b1f;
  --leaf: #93aa74;
  --leaf-dark: #6e8757;
  --cream: #fffdf1;
  --cream-2: #f8f8e8;
  --blush: rgba(190, 215, 147, .46);
  --card: rgba(255, 255, 255, .78);
}

* { box-sizing: border-box; }

html,
body {
  width: 100%;
  height: 100%;
  margin: 0;
  overflow: hidden;
  cursor: none;
  background: #030303;
  color: var(--ink);
  font-family: Arial, "Noto Sans KR", "Malgun Gothic", sans-serif;
}

.tablet {
  position: fixed;
  inset: 0;
  width: 100vw;
  width: 100dvw;
  height: 100vh;
  height: 100dvh;
  padding: clamp(24px, 5vw, 58px) clamp(34px, 6vw, 72px);
  display: grid;
  place-items: center;
  background:
    radial-gradient(circle at 50% 4.8%, #272727 0 5px, #0b0b0b 6px 11px, transparent 12px),
    linear-gradient(180deg, #242424 0, #060606 12%, #050505 86%, #1c1c1c 100%);
  border-radius: clamp(34px, 7vw, 76px);
  box-shadow:
    inset 0 0 0 5px #2a2a2a,
    inset 0 0 0 11px #0a0a0a,
    inset 0 22px 50px rgba(255,255,255,.08),
    inset 0 -22px 42px rgba(0,0,0,.72);
}

.screen {
  position: relative;
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  display: none;
  border-radius: clamp(18px, 3vw, 34px);
  background:
    radial-gradient(circle at 50% 48%, rgba(255,255,255,.78) 0 22%, transparent 48%),
    radial-gradient(circle at 18% 84%, rgba(207, 222, 166, .22), transparent 34%),
    linear-gradient(180deg, var(--cream) 0%, var(--cream-2) 100%);
  box-shadow:
    inset 0 0 46px rgba(201, 210, 166, .2),
    0 0 0 1px rgba(255,255,255,.18);
}

.screen.active {
  display: grid;
  place-items: center;
}

.screen::before,
.screen::after {
  content: "";
  position: absolute;
  pointer-events: none;
  opacity: .44;
  z-index: 0;
}

.screen::before {
  width: min(270px, 34vw);
  height: min(250px, 46vh);
  left: -18px;
  top: -18px;
  background:
    radial-gradient(ellipse at 24% 20%, rgba(147,170,116,.36) 0 10%, transparent 11%),
    radial-gradient(ellipse at 40% 30%, rgba(147,170,116,.3) 0 13%, transparent 14%),
    radial-gradient(ellipse at 58% 14%, rgba(147,170,116,.28) 0 9%, transparent 10%),
    linear-gradient(110deg, transparent 0 22%, rgba(110,135,87,.38) 23% 24%, transparent 25%),
    linear-gradient(42deg, transparent 0 36%, rgba(110,135,87,.26) 37% 38%, transparent 39%);
  border-radius: 0 0 70% 0;
  transform: rotate(-7deg);
}

.screen::after {
  width: min(360px, 44vw);
  height: min(230px, 38vh);
  right: -10px;
  bottom: -8px;
  background:
    radial-gradient(ellipse at 78% 58%, rgba(147,170,116,.38) 0 11%, transparent 12%),
    radial-gradient(ellipse at 66% 70%, rgba(147,170,116,.34) 0 13%, transparent 14%),
    radial-gradient(ellipse at 54% 80%, rgba(147,170,116,.28) 0 11%, transparent 12%),
    radial-gradient(circle at 72% 92%, rgba(157,185,135,.32) 0 18%, transparent 19%),
    linear-gradient(145deg, transparent 0 48%, rgba(110,135,87,.34) 49% 50%, transparent 51%);
  border-radius: 70% 0 0 0;
}

.sprig {
  position: absolute;
  pointer-events: none;
  z-index: 1;
  opacity: .44;
}

.sprig::before,
.sprig::after {
  content: "";
  position: absolute;
  border-radius: 70% 0 70% 0;
  background: rgba(141, 164, 108, .36);
}

.sprig-a {
  left: 5%;
  bottom: 7%;
  width: 150px;
  height: 180px;
}

.sprig-a::before {
  width: 54px;
  height: 96px;
  left: 8px;
  bottom: 0;
  transform: rotate(-28deg);
}

.sprig-a::after {
  width: 38px;
  height: 72px;
  left: 76px;
  bottom: 18px;
  transform: rotate(34deg);
}

.sprig-b {
  right: 5%;
  top: 4%;
  width: 150px;
  height: 115px;
}

.sprig-b::before {
  width: 58px;
  height: 86px;
  right: 0;
  top: 0;
  transform: rotate(34deg);
}

.sprig-b::after {
  width: 34px;
  height: 58px;
  right: 66px;
  top: 10px;
  transform: rotate(-36deg);
}

.face-core {
  position: relative;
  z-index: 3;
  width: min(520px, 70vw);
  height: min(230px, 42vh);
  display: grid;
  place-items: center;
  animation: idle-alive 4.2s ease-in-out infinite;
}

.eyes,
.sleep-eyes {
  position: absolute;
  top: 14%;
  display: flex;
  gap: clamp(96px, 22vw, 190px);
  align-items: center;
}

.eyes i {
  position: relative;
  width: clamp(46px, 8vw, 64px);
  --eye-h: clamp(64px, 12vw, 92px);
  height: var(--eye-h);
  border-radius: 50%;
  background:
    radial-gradient(circle at 43% 30%, transparent 0 12%, var(--ink) 13%),
    linear-gradient(160deg, #24481f, #142b14);
  transition: height 120ms ease, border-radius 120ms ease, transform 120ms ease;
  transition-delay: 0ms;
  box-shadow: inset -8px -10px 12px rgba(0,0,0,.18);
}

.gentle-eyes i::before,
.happy-eyes i::before {
  content: "";
  position: absolute;
  left: 24%;
  top: 16%;
  width: 38%;
  height: 30%;
  border-radius: 50%;
  background: #fff;
}

.gentle-eyes i::after,
.happy-eyes i::after {
  content: "";
  position: absolute;
  right: 30%;
  bottom: 34%;
  width: 13%;
  height: 11%;
  border-radius: 50%;
  background: rgba(255,255,255,.92);
}

.screen.active .eyes.blink-now i,
.screen.active .happy-eyes.blink-now i {
  height: 8px !important;
  border-radius: 999px !important;
  transform: translateY(35px) !important;
}

.screen.active .eyes.blink-now i::before,
.screen.active .eyes.blink-now i::after {
  opacity: 0 !important;
}

.bored i {
  --eye-h: clamp(18px, 4vw, 30px);
  height: var(--eye-h);
  border-radius: 999px;
}

.sharp i {
  --eye-h: clamp(34px, 7vw, 50px);
  height: var(--eye-h);
  border-radius: 50% 50% 38% 38%;
  transform: skew(-10deg) rotate(-2deg);
}

.happy-eyes i {
  width: clamp(52px, 9vw, 72px);
  --eye-h: clamp(72px, 13vw, 100px);
}

.sleep-eyes i {
  width: clamp(62px, 11vw, 88px);
  height: 34px;
  border-bottom: 8px solid var(--ink);
  border-radius: 0 0 80px 80px;
}

.brows {
  position: absolute;
  top: 1%;
  display: flex;
  gap: clamp(92px, 22vw, 182px);
}

.brows i {
  width: 62px;
  height: 8px;
  border-radius: 8px;
  background: var(--ink);
}

.brows i:first-child { transform: rotate(17deg); }
.brows i:last-child { transform: rotate(-17deg); }

.cheeks {
  position: absolute;
  top: 62%;
  width: min(430px, 66vw);
  height: 58px;
}

.cheeks::before,
.cheeks::after {
  content: "";
  position: absolute;
  width: clamp(70px, 13vw, 112px);
  height: clamp(36px, 7vw, 54px);
  border-radius: 50%;
  background: var(--blush);
  filter: blur(.2px);
}

.cheeks::before { left: 0; }
.cheeks::after { right: 0; }

.mouth {
  position: absolute;
  top: 67%;
}

.smile,
.sleep-mouth {
  width: clamp(68px, 12vw, 96px);
  height: 42px;
  border-bottom: 8px solid var(--ink);
  border-radius: 0 0 90px 90px;
  animation: smile-soft 3.4s ease-in-out infinite;
}

.pout {
  width: 52px;
  height: 12px;
  border-radius: 999px;
  background: var(--ink);
}

.angry-mouth {
  width: 58px;
  height: 9px;
  border-radius: 999px;
  background: var(--ink);
  transform: rotate(-4deg);
}

.big-smile {
  width: 106px;
  height: 58px;
  border-radius: 0 0 120px 120px;
  background: var(--ink);
}

.sound {
  position: absolute;
  top: 37%;
  display: flex;
  gap: 10px;
  align-items: center;
  z-index: 4;
}

.sound.left { left: 16%; }
.sound.right { right: 16%; }

.sound i {
  width: 10px;
  height: 42px;
  border-radius: 20px;
  background: #7fa36d;
  animation: sound 820ms ease-in-out infinite;
}

.sound i:nth-child(2) { animation-delay: 90ms; }
.sound i:nth-child(3) { animation-delay: 180ms; }
.sound i:nth-child(4) { animation-delay: 270ms; }

.scan {
  position: absolute;
  width: min(310px, 52vw);
  aspect-ratio: 1;
  border-radius: 50%;
  z-index: 2;
}

.scan-a {
  border: 2px solid rgba(114, 151, 94, .3);
  box-shadow: 0 0 0 34px rgba(114,151,94,.07), 0 0 0 70px rgba(114,151,94,.04);
  animation: spin 3.4s linear infinite;
}

.scan-b {
  width: min(210px, 42vw);
  border-top: 4px solid rgba(114,151,94,.52);
  border-right: 4px solid transparent;
  animation: spin 1.6s linear infinite reverse;
}

.bubble {
  position: absolute;
  left: 50%;
  bottom: clamp(22px, 6vh, 46px);
  transform: translateX(-50%);
  min-width: min(390px, 82vw);
  border-radius: 26px;
  background: rgba(255, 255, 255, .84);
  border: 1px solid rgba(117, 156, 105, .28);
  box-shadow: 0 18px 44px rgba(54, 74, 47, .13);
  padding: 16px 26px;
  text-align: center;
  z-index: 5;
}

.bubble strong {
  display: block;
  font-size: clamp(20px, 4vw, 28px);
  line-height: 1.1;
}

.bubble span {
  display: block;
  margin-top: 6px;
  color: #60715d;
  font-size: clamp(14px, 2.6vw, 18px);
}

.bubble em {
  display: flex;
  justify-content: center;
  gap: 8px;
  margin-top: 10px;
  font-style: normal;
}

.bubble em i {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--leaf-dark);
  animation: dot 1s ease-in-out infinite;
}

.bubble em i:nth-child(2) { animation-delay: 150ms; }
.bubble em i:nth-child(3) { animation-delay: 300ms; }

.report {
  padding: clamp(18px, 4vw, 34px);
}

.report.active {
  display: block;
}

.report-shell {
  width: min(720px, 100%);
  margin: 0 auto;
  animation: report-in .5s ease both;
}

.report h1 {
  margin: 0 0 clamp(14px, 3vh, 20px);
  text-align: center;
  font-size: clamp(26px, 5vw, 36px);
  line-height: 1.05;
}

.report-card {
  display: grid;
  gap: 10px;
  width: min(680px, 94%);
  margin: 0 auto clamp(14px, 3vh, 22px);
  padding: clamp(18px, 4vw, 26px);
  border-radius: 28px;
  border: 1px solid rgba(117, 156, 105, .35);
  background: var(--card);
  box-shadow: 0 18px 42px rgba(54, 74, 47, .13);
  text-align: center;
}

.report-card strong { font-size: clamp(24px, 5vw, 34px); }
.report-card span,
.report-card b { font-size: clamp(15px, 3vw, 20px); }

.metric-grid {
  width: min(720px, 94%);
  margin: 0 auto;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: clamp(10px, 2vw, 14px);
}

.metric-grid div {
  min-height: 82px;
  border-radius: 22px;
  border: 1px solid rgba(117, 156, 105, .3);
  background: rgba(255, 255, 255, .72);
  padding: clamp(12px, 3vw, 18px);
  font-weight: 800;
}

.metric-grid span {
  display: block;
  color: #5f6f5d;
  font-size: clamp(14px, 3vw, 18px);
}

.metric-grid strong {
  display: block;
  margin-top: 6px;
  color: #477640;
  font-size: clamp(22px, 5vw, 30px);
}

@keyframes idle-alive {
  0%, 100% { transform: translateY(0) scale(1); }
  48% { transform: translateY(-4px) scale(1.01); }
}

@keyframes smile-soft {
  0%, 100% { transform: translateY(0) scaleX(1); }
  50% { transform: translateY(2px) scaleX(1.06); }
}

@keyframes sound {
  0%, 100% { transform: scaleY(.45); opacity: .52; }
  50% { transform: scaleY(1.35); opacity: 1; }
}

@keyframes spin { to { transform: rotate(360deg); } }

@keyframes dot {
  0%, 100% { opacity: .35; transform: translateY(0); }
  50% { opacity: 1; transform: translateY(-5px); }
}

@keyframes report-in {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}

    * { cursor: none !important; }
    .tablet { border-radius: 0; padding: clamp(12px, 3vw, 32px); }
    .status-pill {
      position: fixed;
      right: 18px;
      top: 14px;
      z-index: 20;
      padding: 7px 12px;
      border-radius: 999px;
      background: rgba(255,255,255,.72);
      border: 1px solid rgba(117,156,105,.26);
      font: 700 14px Arial, sans-serif;
      color: #52684c;
    }
    .status-pill.offline { color: #80584a; }
  </style>
</head>
<body>
  <div class="status-pill offline" id="netState">OFFLINE</div>
  <main class="tablet" aria-label="OnPlant front display">
    <section class="screen face idle active" data-screen="idle">
      <div class="sprig sprig-a"></div><div class="sprig sprig-b"></div>
      <div class="face-core gentle-core"><div class="eyes glossy gentle-eyes"><i></i><i></i></div><div class="cheeks"></div><div class="mouth smile"></div></div>
    </section>
    <section class="screen face sulk" data-screen="sulk">
      <div class="sprig sprig-a"></div><div class="sprig sprig-b"></div>
      <div class="face-core sulk-core"><div class="eyes bored"><i></i><i></i></div><div class="cheeks"></div><div class="mouth pout"></div></div>
    </section>
    <section class="screen face angry" data-screen="angry">
      <div class="sprig sprig-a"></div><div class="sprig sprig-b"></div>
      <div class="face-core angry-core"><div class="brows"><i></i><i></i></div><div class="eyes sharp"><i></i><i></i></div><div class="cheeks"></div><div class="mouth angry-mouth"></div></div>
    </section>
    <section class="screen face sleep" data-screen="sleep">
      <div class="sprig sprig-a"></div><div class="sprig sprig-b"></div>
      <div class="face-core sleep-core"><div class="sleep-eyes"><i></i><i></i></div><div class="cheeks"></div><div class="mouth sleep-mouth"></div><div class="sleep-mark">z</div></div>
    </section>
    <section class="screen face happy" data-screen="happy">
      <div class="sprig sprig-a"></div><div class="sprig sprig-b"></div>
      <div class="face-core happy-core"><div class="eyes glossy happy-eyes"><i></i><i></i></div><div class="cheeks"></div><div class="mouth big-smile"></div></div>
    </section>
    <section class="screen face listening" data-screen="listening">
      <div class="sound left"><i></i><i></i><i></i><i></i></div><div class="sound right"><i></i><i></i><i></i><i></i></div>
      <div class="face-core gentle-core"><div class="eyes glossy gentle-eyes"><i></i><i></i></div><div class="cheeks"></div><div class="mouth smile"></div></div>
      <div class="bubble"><strong>Listening</strong><span>Waiting for voice command</span></div>
    </section>
    <section class="screen face analyzing" data-screen="analyzing">
      <div class="scan scan-a"></div><div class="scan scan-b"></div>
      <div class="face-core gentle-core"><div class="eyes glossy gentle-eyes"><i></i><i></i></div><div class="cheeks"></div><div class="mouth smile"></div></div>
        <div class="bubble"><strong>식물 상태 분석 중</strong><span>센서 데이터를 확인하고 있어요</span><em><i></i><i></i><i></i></em></div>
    </section>
    <section class="screen report" data-screen="report">
      <div class="report-shell">
        <h1>식물 상태 리포트</h1>
        <div class="report-card"><strong id="reportTitle">현재 상태</strong><span id="reportMessage">최신 센서 데이터를 확인하고 있습니다.</span><b id="reportRecommend">현재 환경을 유지하고 주기적으로 확인하세요.</b></div>
        <div class="metric-grid"><div><span>온도</span><strong id="dTemp">--°C</strong></div><div><span>습도</span><strong id="dHum">--%</strong></div><div><span>조도</span><strong id="dLux">-- lux</strong></div><div><span>토양수분</span><strong id="dSoil">--%</strong></div></div>
      </div>
    </section>
  </main>
  <script>
    const screens = new Set(["idle", "sulk", "angry", "sleep", "happy", "listening", "analyzing", "report"]);
    let currentScreen = "idle";
    function show(screen) { const next = screens.has(screen) ? screen : "idle"; currentScreen = next; document.querySelectorAll(".screen").forEach((node) => node.classList.toggle("active", node.dataset.screen === next)); }
    function setMetric(id, value, suffix, digits = 0) { const node = document.getElementById(id); if (!node) return; const n = Number(value); node.textContent = Number.isFinite(n) ? `${n.toFixed(digits)}${suffix}` : `--${suffix}`; }
    function mapScreen(data) { if (!data.online) return "idle"; if (data.screen === "report") return "report"; if (data.emotion === "warn" || data.emotion === "alert") return "sulk"; if (data.emotion === "angry") return "angry"; if (data.emotion === "sleep") return "sleep"; if (data.emotion === "listening") return "listening"; if (data.emotion === "analyzing") return "analyzing"; if (data.emotion === "happy") return "happy"; return "idle"; }
    async function refresh() { try { const res = await fetch("/api/status?ts=" + Date.now(), { cache: "no-store" }); const data = await res.json(); show(mapScreen(data)); const net = document.getElementById("netState"); net.textContent = data.online ? "ONLINE" : "OFFLINE"; net.className = "status-pill" + (data.online ? "" : " offline"); setMetric("dTemp", data.temperature, "°C", 1); setMetric("dHum", data.humidity, "%"); setMetric("dLux", data.lux, " lux"); setMetric("dSoil", data.soil_moisture, "%"); document.getElementById("reportTitle").textContent = data.sub_message || "현재 상태"; document.getElementById("reportMessage").textContent = data.message || "OnPlant"; document.getElementById("reportRecommend").textContent = data.recommendation || "현재 환경을 유지하고 주기적으로 확인하세요."; } catch { show("idle"); } }
    function blinkActiveFace() { if (currentScreen === "sleep" || currentScreen === "report") return; const eyes = document.querySelector(".screen.active .eyes"); if (!eyes) return; eyes.classList.remove("blink-now"); void eyes.offsetWidth; eyes.classList.add("blink-now"); window.setTimeout(() => eyes.classList.remove("blink-now"), 220); }
    refresh(); setInterval(refresh, 1000); setInterval(blinkActiveFace, 1800); window.setTimeout(blinkActiveFace, 600);
  </script>
</body>
</html>"""


def now() -> float:
    return time.time()


def fetch_json(url: str, timeout: float = 2.0) -> dict:
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def update_status(payload: dict) -> None:
    with status_lock:
        status.update(payload)
        status["updated_at"] = now()


def fallback_status() -> None:
    update_status(
        {
            **DEFAULT_STATUS,
            "online": False,
            "screen": "face",
            "emotion": "offline",
            "message": "OnPlant",
            "sub_message": "Server offline",
            "updated_at": now(),
        }
    )


def clamp_number(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def status_from_summary(summary: dict, display: dict) -> dict:
    latest = summary.get("latest") or {}
    robot = summary.get("robot") or {}
    status_info = summary.get("status") or {}

    screen = display.get("screen") or "idle"
    if screen in {"report", "dashboard", "status"}:
        screen = "report"
    else:
        screen = "face"

    tone = str(status_info.get("tone") or "").lower()
    level = str(status_info.get("level") or "").lower()
    emotion = "happy"
    if tone in {"warn", "danger", "alert"} or "warn" in level or "danger" in level:
        emotion = "warn"

    robot_state = "IDLE"
    message = display.get("message") or ""
    if not message:
        message = robot.get("plant_name") or "OnPlant"

    return {
        "online": True,
        "screen": screen,
        "emotion": emotion,
        "message": str(message)[:80],
        "sub_message": str(status_info.get("level") or robot_state)[:80],
        "lux": clamp_number(latest.get("lux"), 0),
        "temperature": clamp_number(latest.get("temperature"), 0),
        "humidity": clamp_number(latest.get("humidity"), 0),
        "soil_moisture": clamp_number(latest.get("soil_moisture"), 0),
        "recommendation": str(status_info.get("recommendation") or "")[:160],
        "robot_state": robot_state,
        "camera_visible": bool(display.get("camera_visible", False)),
    }


def poll_server(base_url: str, robot_id: str, interval: float) -> None:
    base_url = base_url.rstrip("/")
    robot_path = quote(robot_id, safe="")
    failed_count = 0
    was_online = False
    last_error_print = 0.0

    while True:
        try:
            summary = fetch_json(f"{base_url}/api/robots/{robot_path}/summary")
            try:
                display = fetch_json(f"{base_url}/api/robots/{robot_path}/display")
            except Exception as exc:
                display = {}
                now_ts = now()
                if now_ts - last_error_print > 10:
                    print(f"display endpoint unavailable, using summary only: {exc}", file=sys.stderr)
                    last_error_print = now_ts

            update_status(status_from_summary(summary, display))
            failed_count = 0
            if not was_online:
                print(f"display server online: {base_url} robot_id={robot_id}")
            was_online = True
        except Exception as exc:
            failed_count += 1
            now_ts = now()
            if now_ts - last_error_print > 10:
                print(f"display server offline/retry {failed_count}: {exc}", file=sys.stderr)
                last_error_print = now_ts
            if failed_count >= 2:
                fallback_status()
                was_online = False
        time.sleep(interval)


class DisplayHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        return

    def send_json(self, payload: dict, code: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.startswith("/api/status"):
            with status_lock:
                payload = status.copy()
            self.send_json(payload)
            return

        body = HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def find_browser() -> str:
    for candidate in ("chromium", "chromium-browser", "google-chrome", "firefox"):
        path = shutil.which(candidate)
        if path:
            return path
    raise RuntimeError("no browser found. Install chromium-browser on Raspberry Pi.")


def build_browser_command(browser: str, url: str, width: int, height: int) -> list[str]:
    name = os.path.basename(browser).lower()
    if "firefox" in name:
        return [browser, "--kiosk", url]
    return [
        browser,
        "--kiosk",
        "--window-position=0,0",
        f"--window-size={width},{height}",
        "--start-maximized",
        "--start-fullscreen",
        "--force-device-scale-factor=1",
        "--hide-scrollbars",
        "--app=" + url,
        "--noerrdialogs",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-infobars",
        "--disable-translate",
        "--disable-features=Translate,TranslateUI,PasswordManagerOnboarding",
        "--disable-session-crashed-bubble",
        "--password-store=basic",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--user-data-dir=/tmp/onplant-display-chromium",
        "--check-for-update-interval=31536000",
        "--autoplay-policy=no-user-gesture-required",
    ]


def start_local_server(host: str, port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), DisplayHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def main() -> int:
    parser = argparse.ArgumentParser(description="Run OnPlant 5-inch display with offline fallback.")
    parser.add_argument("--server", default=os.getenv("ONPLANT_SERVER", "http://192.168.10.110:5050"))
    parser.add_argument("--robot-id", default=os.getenv("ONPLANT_ROBOT_ID", "raspbot-a"))
    parser.add_argument("--host", default=os.getenv("ONPLANT_DISPLAY_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("ONPLANT_DISPLAY_PORT", "8765")))
    parser.add_argument("--poll", type=float, default=float(os.getenv("ONPLANT_DISPLAY_POLL", "2.0")))
    parser.add_argument("--width", type=int, default=int(os.getenv("ONPLANT_DISPLAY_WIDTH", "1024")))
    parser.add_argument("--height", type=int, default=int(os.getenv("ONPLANT_DISPLAY_HEIGHT", "600")))
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    fallback_status()
    start_local_server(args.host, args.port)

    poll_thread = threading.Thread(
        target=poll_server,
        args=(args.server, args.robot_id, args.poll),
        daemon=True,
    )
    poll_thread.start()

    local_url = f"http://{args.host}:{args.port}/"
    print(f"local display: {local_url}")
    print(f"remote server: {args.server.rstrip('/')} robot_id={args.robot_id}")

    if args.no_browser:
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return 0

    browser = find_browser()
    command = build_browser_command(browser, local_url, args.width, args.height)
    subprocess.Popen(command)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"front display failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
