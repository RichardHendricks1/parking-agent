from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mini_nanobot.planning.profiles import PlanningThresholdProfile


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _fmt_number(value: float) -> str:
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return text or "0"


def build_dashboard_html(
    *,
    log_path: Path,
    log_name_display: str | None = None,
    log_path_display: str | None = None,
    summary: str,
    risk_level: str,
    score: float,
    key_metrics: dict[str, Any],
    anomalies: list[dict[str, Any]],
    dashboard_data: dict[str, Any],
    profile: PlanningThresholdProfile,
) -> str:
    data_json = json.dumps(dashboard_data, ensure_ascii=False)
    summary_safe = _escape(summary)
    log_path_safe = _escape(log_path_display or str(log_path))
    log_name_safe = _escape(log_name_display or log_path.name)
    risk_class = {"high": "risk-high", "medium": "risk-medium", "low": "risk-low"}.get(risk_level, "risk-medium")
    timer_range = f"[{_fmt_number(profile.timer_interval_low_ms)}, {_fmt_number(profile.timer_interval_high_ms)}]"
    yaw_limit = _fmt_number(profile.yaw_jump_max_deg)
    html_template = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Planning Log Dashboard - __LOG_NAME__</title>
  <style>
    @import url("https://fonts.googleapis.com/css2?family=Sora:wght@400;600;700;800&family=IBM+Plex+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@500;700&display=swap");
    :root {
      --ink: #0b1b2e;
      --text: #122844;
      --muted: #4f6380;
      --sky: #d7e9ff;
      --sea: #0f7dcf;
      --teal: #0c9c86;
      --mint: #2fa38a;
      --sand: #f7c57f;
      --rose: #f5b7aa;
      --card: rgba(255, 255, 255, 0.86);
      --line: #d3dfef;
      --high: #d43f3a;
      --mid: #d48806;
      --low: #16845f;
      --shadow: 0 18px 40px rgba(17, 45, 89, 0.14);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--text);
      font-family: "IBM Plex Sans", "PingFang SC", "Microsoft YaHei", sans-serif;
      background:
        radial-gradient(circle at 15% 10%, rgba(215, 233, 255, 0.72), rgba(215, 233, 255, 0) 35%),
        radial-gradient(circle at 92% 5%, rgba(215, 255, 245, 0.72), rgba(215, 255, 245, 0) 32%),
        radial-gradient(circle at 80% 80%, rgba(255, 232, 205, 0.62), rgba(255, 232, 205, 0) 32%),
        linear-gradient(165deg, #f2f7ff 0%, #f8fbff 48%, #f4fbfa 100%);
      min-height: 100vh;
      position: relative;
      overflow-x: hidden;
    }
    .blob {
      position: fixed;
      border-radius: 999px;
      filter: blur(30px);
      opacity: 0.42;
      pointer-events: none;
      z-index: 0;
      animation: floaty 12s ease-in-out infinite;
    }
    .blob.a { width: 270px; height: 270px; background: #9ec9ff; top: -80px; right: -40px; }
    .blob.b { width: 220px; height: 220px; background: #9de7dd; left: -70px; top: 30vh; animation-delay: 1.5s; }
    .blob.c { width: 180px; height: 180px; background: #ffd8a8; right: 16%; bottom: -40px; animation-delay: 3s; }
    .wrap {
      max-width: 1440px;
      margin: 0 auto;
      padding: 26px 22px 34px;
      position: relative;
      z-index: 1;
    }
    .card-shell {
      background: var(--card);
      border: 1px solid rgba(255, 255, 255, 0.78);
      box-shadow: var(--shadow);
      border-radius: 22px;
      backdrop-filter: blur(5px);
      animation: rise 0.55s ease both;
      animation-delay: calc(var(--d, 0) * 70ms);
    }
    .hero {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 16px;
      padding: 24px 24px 22px;
      position: relative;
      overflow: hidden;
    }
    .hero::after {
      content: "";
      position: absolute;
      inset: -1px;
      background:
        linear-gradient(120deg, rgba(15, 125, 207, 0.18), rgba(255, 255, 255, 0.1) 55%, rgba(12, 156, 134, 0.13));
      z-index: -1;
    }
    .eyebrow {
      margin: 0;
      font-size: 11px;
      letter-spacing: 0.28em;
      text-transform: uppercase;
      color: #1d5e9c;
      font-weight: 700;
    }
    h1 {
      margin: 7px 0 0;
      font-family: "Sora", "PingFang SC", sans-serif;
      font-size: clamp(26px, 4vw, 36px);
      letter-spacing: 0.01em;
      color: var(--ink);
    }
    .meta {
      margin-top: 10px;
      font-size: 12px;
      color: #5d6f87;
      word-break: break-all;
    }
    .mono { font-family: "JetBrains Mono", monospace; }
    .summary {
      margin: 14px 0 0;
      max-width: 900px;
      padding: 11px 12px;
      border: 1px solid #d6e7fb;
      border-radius: 12px;
      background: rgba(255, 255, 255, 0.65);
      line-height: 1.56;
      font-size: 14px;
      color: #143257;
    }
    .hero-side {
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      gap: 10px;
      justify-content: flex-start;
    }
    .risk-chip {
      padding: 10px 16px;
      border-radius: 999px;
      color: #fff;
      font-weight: 700;
      font-size: 13px;
      letter-spacing: 0.04em;
      box-shadow: 0 10px 22px rgba(11, 24, 45, 0.16);
    }
    .score-box {
      min-width: 128px;
      text-align: center;
      border-radius: 14px;
      border: 1px solid #d9e7f8;
      background: rgba(255, 255, 255, 0.84);
      padding: 10px 12px;
    }
    .score-box .v {
      font-family: "Sora", sans-serif;
      font-size: 27px;
      line-height: 1.1;
      color: #11335a;
      font-weight: 700;
    }
    .score-box .k {
      margin-top: 4px;
      color: #60738d;
      font-size: 11px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }
    .risk-high { background: linear-gradient(135deg, #c7362f, #e35149); }
    .risk-medium { background: linear-gradient(135deg, #cf7a05, #ec9b17); }
    .risk-low { background: linear-gradient(135deg, #0e8a64, #14aa7c); }
    .warning-strip {
      margin-top: 14px;
      padding: 10px 14px;
      border-radius: 14px;
      border: 1px solid rgba(212, 63, 58, 0.16);
      background: rgba(255, 244, 239, 0.82);
      color: #8c3c2d;
      font-size: 13px;
      line-height: 1.5;
    }
    .warning-strip ul { margin: 0; padding-left: 18px; }
    .kpi-grid {
      margin-top: 15px;
      display: grid;
      gap: 14px;
      grid-template-columns: repeat(12, minmax(0, 1fr));
    }
    .kpi {
      grid-column: span 2;
      padding: 14px 14px 12px;
      min-height: 112px;
      position: relative;
      overflow: hidden;
    }
    .kpi.primary {
      background: linear-gradient(145deg, #0f7dcf, #1a8adf 56%, #37a0f0);
      color: #fff;
    }
    .kpi.primary .label, .kpi.primary .sub { color: rgba(255, 255, 255, 0.84); }
    .kpi .label {
      font-size: 11px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: #62748d;
      font-weight: 600;
    }
    .kpi .val {
      margin-top: 8px;
      font-family: "Sora", sans-serif;
      font-weight: 700;
      font-size: 30px;
      line-height: 1;
      color: #112f53;
    }
    .kpi .sub {
      margin-top: 9px;
      font-size: 12px;
      color: #5f738e;
    }
    .kpi.primary::before {
      content: "";
      position: absolute;
      width: 120px;
      height: 120px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.17);
      top: -56px;
      right: -42px;
    }
    .chart-grid {
      margin-top: 14px;
      display: grid;
      gap: 14px;
      grid-template-columns: repeat(12, minmax(0, 1fr));
    }
    .card {
      grid-column: span 6;
      padding: 14px 15px 15px;
      min-height: 346px;
    }
    .card h3, .section-card h3 {
      margin: 0;
      font-family: "Sora", sans-serif;
      font-size: 17px;
      color: #102a48;
      letter-spacing: 0.01em;
    }
    .hint {
      margin: 5px 0 11px;
      color: #60748f;
      font-size: 12px;
    }
    canvas {
      width: 100%;
      height: 252px;
      border-radius: 14px;
      border: 1px solid #dde8f7;
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.84), rgba(247, 251, 255, 0.9)),
        repeating-linear-gradient(45deg, rgba(230, 240, 252, 0.45) 0px, rgba(230, 240, 252, 0.45) 1px, rgba(255, 255, 255, 0) 1px, rgba(255, 255, 255, 0) 16px);
    }
    .trajectory-card, .section-card {
      margin-top: 14px;
      padding: 16px 16px 15px;
    }
    #trajectoryCanvas {
      height: 460px;
      background: linear-gradient(180deg, #fdfefe 0%, #f2f9ff 100%);
    }
    #processReplaySvg {
      height: clamp(600px, 72vh, 840px);
      background: linear-gradient(180deg, #fdfefe 0%, #f2f9ff 100%);
    }
    #gridMapSvg {
      height: clamp(620px, 74vh, 880px);
      background: linear-gradient(180deg, #fdfefe 0%, #f2f9ff 100%);
    }
    .viz-surface {
      height: 430px;
      width: 100%;
      display: block;
      border-radius: 14px;
      border: 1px solid #dde8f7;
      object-fit: contain;
    }
    #processReplayBody {
      display: grid;
      grid-template-columns: minmax(300px, 360px) minmax(0, 1fr);
      gap: 14px;
      align-items: start;
    }
    .toolbar, .section-toolbar {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 10px;
    }
    .toolbar .left, .section-toolbar .left {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      color: #2a4465;
      font-size: 13px;
      font-weight: 500;
      flex-wrap: wrap;
    }
    #trajectoryMeta, .pill {
      margin: 0;
      padding: 4px 9px;
      border-radius: 999px;
      background: #edf5ff;
      border: 1px solid #d7e8fb;
      color: #355375;
      font-size: 12px;
    }
    select, button, input[type="range"] {
      border: 1px solid #ccdff6;
      border-radius: 11px;
      padding: 7px 11px;
      background: #fff;
      color: #15375c;
      font-family: "JetBrains Mono", monospace;
      font-size: 12px;
      font-weight: 600;
    }
    button {
      cursor: pointer;
      font-family: "IBM Plex Sans", sans-serif;
      font-weight: 700;
      padding: 8px 14px;
      background: linear-gradient(180deg, #ffffff, #eef6ff);
    }
    input[type="range"] {
      padding: 0;
      height: 10px;
      background: transparent;
      border: none;
      min-width: 180px;
    }
    .legend, .toggle-list {
      display: flex;
      align-items: center;
      gap: 12px;
      color: #5c7391;
      font-size: 12px;
      flex-wrap: wrap;
    }
    .legend .dot {
      width: 9px;
      height: 9px;
      border-radius: 999px;
      display: inline-block;
      margin-right: 5px;
    }
    .toggle-list label {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 5px 9px;
      border-radius: 999px;
      background: rgba(237, 245, 255, 0.8);
      border: 1px solid #d7e8fb;
    }
    .toggle-list input { margin: 0; }
    .status-grid {
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      margin: 12px 0 14px;
    }
    #processStatusGrid {
      margin: 0;
      grid-column: 1;
      grid-row: 1;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      align-self: start;
    }
    #processReplaySvg {
      grid-column: 2;
      grid-row: 1;
      align-self: stretch;
    }
    #processReplayBoundary {
      grid-column: 1 / -1;
    }
    .status-card {
      border-radius: 16px;
      padding: 12px 12px 11px;
      border: 1px solid #deebf8;
      background: linear-gradient(180deg, rgba(255,255,255,0.9), rgba(244,249,255,0.92));
      min-height: 88px;
    }
    .status-card .k {
      color: #6a7d97;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      font-weight: 700;
    }
    .status-card .v {
      margin-top: 7px;
      color: #11355b;
      font-size: 15px;
      font-weight: 700;
      line-height: 1.35;
      word-break: break-word;
    }
    .status-card .s {
      margin-top: 5px;
      color: #67809f;
      font-size: 12px;
      line-height: 1.45;
    }
    .boundary-banner {
      margin-top: 10px;
      padding: 11px 12px;
      border-radius: 14px;
      background: linear-gradient(90deg, rgba(15,125,207,0.1), rgba(12,156,134,0.1));
      border: 1px solid rgba(15,125,207,0.14);
      color: #21496f;
      font-size: 12px;
      line-height: 1.5;
    }
    .full {
      margin-top: 14px;
      padding: 14px 15px 10px;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
      overflow: hidden;
      border-radius: 12px;
    }
    th, td {
      border-bottom: 1px solid #ebf1fa;
      text-align: left;
      padding: 10px 9px;
      vertical-align: top;
    }
    th {
      background: #f2f7ff;
      color: #4f6887;
      font-size: 11px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      font-weight: 700;
    }
    tr:hover td { background: #f8fbff; }
    .sev-high { color: var(--high); font-weight: 700; }
    .sev-medium { color: var(--mid); font-weight: 700; }
    .sev-low { color: var(--low); font-weight: 700; }
    .meta-grid {
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      margin-top: 12px;
    }
    .meta-box {
      border: 1px solid #deebf8;
      border-radius: 14px;
      padding: 12px;
      background: rgba(255,255,255,0.82);
    }
    .meta-box .k {
      color: #6a7d97;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      font-weight: 700;
    }
    .meta-box .v {
      margin-top: 7px;
      color: #11355b;
      font-size: 14px;
      font-weight: 700;
      line-height: 1.45;
      word-break: break-word;
    }
    .empty-note {
      padding: 18px 16px;
      border-radius: 16px;
      border: 1px dashed #cddcf0;
      background: rgba(246, 250, 255, 0.85);
      color: #5d718e;
      font-size: 13px;
      line-height: 1.6;
    }
    @keyframes rise {
      from { opacity: 0; transform: translateY(10px); }
      to { opacity: 1; transform: translateY(0); }
    }
    @keyframes floaty {
      0%, 100% { transform: translateY(0px); }
      50% { transform: translateY(14px); }
    }
    @media (max-width: 1120px) {
      .kpi { grid-column: span 4; }
      .kpi.primary { grid-column: span 12; }
      .status-grid, .meta-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      #processReplayBody { grid-template-columns: 1fr; }
      #processStatusGrid { grid-column: 1; grid-row: auto; margin: 12px 0 0; }
      #processReplaySvg { grid-column: 1; grid-row: auto; }
      #processReplayBoundary { grid-column: 1; }
    }
    @media (max-width: 900px) {
      .hero {
        grid-template-columns: 1fr;
        gap: 14px;
      }
      .hero-side { align-items: flex-start; }
      .kpi { grid-column: span 6; }
      .card { grid-column: span 12; }
      #trajectoryCanvas { height: 360px; }
      #processReplaySvg { height: 500px; }
      #gridMapSvg { height: 520px; }
    }
    @media (max-width: 620px) {
      .wrap { padding: 16px 12px 24px; }
      .kpi-grid, .chart-grid { gap: 10px; }
      .kpi { grid-column: span 12; min-height: 100px; }
      canvas { height: 220px; }
      #trajectoryCanvas { height: 300px; }
      #processReplaySvg { height: 380px; }
      #gridMapSvg { height: 400px; }
      .summary { font-size: 13px; }
      .legend, .toggle-list { gap: 9px; }
      .status-grid, .meta-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="blob a"></div>
  <div class="blob b"></div>
  <div class="blob c"></div>
  <div class="wrap">
    <section class="hero card-shell" style="--d:0">
      <div>
        <p class="eyebrow">J6B Planning Intelligence</p>
        <h1>Planning Log Dashboard</h1>
        <div class="meta mono">__LOG_PATH__</div>
        <p class="summary">__SUMMARY__</p>
      </div>
      <div class="hero-side">
        <div class="risk-chip __RISK_CLASS__">Risk: __RISK_LEVEL__</div>
        <div class="score-box">
          <div class="v">__SCORE__</div>
          <div class="k">Composite Score</div>
        </div>
      </div>
    </section>
    <div id="vizWarnings"></div>
    <section class="kpi-grid">
      <div class="kpi card-shell primary" style="--d:1"><div class="label">Overall Risk Score</div><div class="val">__SCORE__</div><div class="sub">Focus: __FOCUS__ / Profile: __PROFILE__</div></div>
      <div class="kpi card-shell" style="--d:2"><div class="label">Cycle Count</div><div class="val">__CYCLE_COUNT__</div><div class="sub">with points: __CYCLE_WITH_POINTS__</div></div>
      <div class="kpi card-shell" style="--d:3"><div class="label">Parsed Lines</div><div class="val">__PARSED_LINES__</div><div class="sub">total: __LINE_COUNT__</div></div>
      <div class="kpi card-shell" style="--d:4"><div class="label">Timer Jitter</div><div class="val">__TIMER_JITTER__</div><div class="sub">out of __TIMER_RANGE__ ms</div></div>
      <div class="kpi card-shell" style="--d:5"><div class="label">Replan Ratio</div><div class="val">__REPLAN_RATIO__</div><div class="sub">longest streak: __REPLAN_STREAK__</div></div>
      <div class="kpi card-shell" style="--d:6"><div class="label">Top Severity</div><div class="val">__HIGH_ANOMALY_COUNT__</div><div class="sub">high anomalies</div></div>
    </section>
    <section class="chart-grid">
      <div class="card card-shell" style="--d:7">
        <h3>Timer Interval (ms)</h3>
        <div class="hint">Planner loop interval trend with guard rails at __TIMER_RANGE__ ms.</div>
        <canvas id="timerChart"></canvas>
      </div>
      <div class="card card-shell" style="--d:8">
        <h3>Fork Star Used Time (ms)</h3>
        <div class="hint">Runtime load profile across planning cycles.</div>
        <canvas id="forkChart"></canvas>
      </div>
      <div class="card card-shell" style="--d:9">
        <h3>Yaw Jump Max per Cycle (deg)</h3>
        <div class="hint">Steering continuity risk view with __YAW_LIMIT__ deg threshold.</div>
        <canvas id="yawChart"></canvas>
      </div>
      <div class="card card-shell" style="--d:10">
        <h3>Path Length / Curvature Blend</h3>
        <div class="hint">Composite trend for route scale and curvature intensity.</div>
        <canvas id="pathChart"></canvas>
      </div>
    </section>
    <section class="trajectory-card card-shell" style="--d:11">
      <h3>Output Trajectory Map</h3>
      <div class="toolbar">
        <div class="left">
          <label for="trajectorySelect">Cycle:</label>
          <select id="trajectorySelect"></select>
          <span id="trajectoryMeta"></span>
        </div>
        <div class="legend">
          <span><span class="dot" style="background:#1185ff;"></span>selected</span>
          <span><span class="dot" style="background:#e35149;"></span>high</span>
          <span><span class="dot" style="background:#ec9b17;"></span>medium</span>
          <span><span class="dot" style="background:#92a7c0;"></span>normal</span>
        </div>
      </div>
      <canvas id="trajectoryCanvas"></canvas>
    </section>
    <section class="section-card card-shell" style="--d:12">
      <h3>Planning Process Replay</h3>
      <div class="hint">Frame-level replay ported from <span class="mono">plotlog_0305.py</span>, rendered as self-contained HTML.</div>
      <div class="section-toolbar">
        <div class="left">
          <button id="processPlayBtn" type="button">Play</button>
          <label for="processFrameRange">Frame</label>
          <input id="processFrameRange" type="range" min="0" max="0" value="0" />
          <span id="processFrameLabel" class="pill">frame 0 / 0</span>
          <label for="processSpeedSelect">Speed</label>
          <select id="processSpeedSelect">
            <option value="0.5">0.5x</option>
            <option value="1" selected>1x</option>
            <option value="2">2x</option>
            <option value="4">4x</option>
          </select>
        </div>
        <div class="toggle-list">
          <label><input id="processShowTrajectory" type="checkbox" checked />trajectory</label>
          <label><input id="processShowSlot" type="checkbox" checked />slot</label>
          <label><input id="processShowVehicle" type="checkbox" checked />vehicle</label>
          <label><input id="processShowTargets" type="checkbox" checked />targets</label>
        </div>
      </div>
      <div id="processReplayEmpty" class="empty-note" style="display:none"></div>
      <div id="processReplayBody">
        <div class="status-grid" id="processStatusGrid"></div>
        <img id="processReplaySvg" class="viz-surface" alt="Process replay SVG" />
        <div class="boundary-banner" id="processReplayBoundary"></div>
      </div>
    </section>
    <section class="section-card card-shell" style="--d:13">
      <h3>Planner Inputs GridMap</h3>
      <div class="hint">Occupancy grid and planner inputs ported from <span class="mono">gridmap_editor_with_base.py</span>.</div>
      <div class="section-toolbar">
        <div class="left">
          <label for="gridFrameSelect">Frame</label>
          <select id="gridFrameSelect"></select>
          <span id="gridFrameLabel" class="pill">frame 0 / 0</span>
          <label for="gridAlphaRange">Grid alpha</label>
          <input id="gridAlphaRange" type="range" min="20" max="100" value="84" />
        </div>
        <div class="toggle-list">
          <label><input id="gridShowTrajectory" type="checkbox" checked />trajectory</label>
          <label><input id="gridShowSlot" type="checkbox" checked />slot</label>
          <label><input id="gridShowBase" type="checkbox" checked />base polygon</label>
          <label><input id="gridShowPoses" type="checkbox" checked />ego / target</label>
        </div>
      </div>
      <div id="gridMapEmpty" class="empty-note" style="display:none"></div>
      <div id="gridMapBody">
        <img id="gridMapSvg" class="viz-surface" alt="Grid map SVG" />
        <div class="meta-grid" id="gridMapMeta"></div>
      </div>
    </section>
    <section class="full card-shell" style="--d:14">
      <h3>Top Anomalies</h3>
      <table id="anomalyTable">
        <thead><tr><th>Rule</th><th>Severity</th><th>Count</th><th>Detail</th></tr></thead>
        <tbody></tbody>
      </table>
    </section>
  </div>
<script>
const data = __DATA_JSON__;
function yScale(min, max, h, pad) {
  return (v) => {
    if (max === min) return h / 2;
    return h - pad - ((v - min) / (max - min)) * (h - pad * 2);
  };
}
function safeText(value, fallback = "-") {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}
function fmtNum(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  const text = Number(value).toFixed(digits);
  return text.replace(/\\.0+$/, "").replace(/(\\.\\d*?)0+$/, "$1");
}
function htmlEscape(value) {
  return safeText(value, "").replace(/[&<>"]/g, (ch) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[ch] || ch));
}
function setupHiDPI(canvas) {
  const ctx = canvas.getContext("2d");
  const ratio = Math.max(window.devicePixelRatio || 1, 1);
  const vw = canvas.clientWidth;
  const vh = canvas.clientHeight;
  canvas.width = Math.max(1, Math.floor(vw * ratio));
  canvas.height = Math.max(1, Math.floor(vh * ratio));
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, vw, vh);
  return { ctx, vw, vh };
}
function drawNoData(ctx, text) {
  ctx.fillStyle = "#6f8097";
  ctx.font = "500 13px 'IBM Plex Sans'";
  ctx.fillText(text, 14, 24);
}
function drawLine(canvasId, values, opts) {
  const c = document.getElementById(canvasId);
  const { ctx, vw, vh } = setupHiDPI(c);
  if (!values || !values.length) {
    drawNoData(ctx, "No data");
    return;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const pad = 28;
  const xStep = values.length > 1 ? (vw - pad * 2) / (values.length - 1) : 0;
  const yMap = yScale(min, max, vh, pad);
  const xAt = (i) => pad + i * xStep;
  ctx.strokeStyle = "#dee7f4";
  ctx.lineWidth = 1;
  for (let i = 0; i < 5; i++) {
    const y = pad + (i * (vh - pad * 2) / 4);
    ctx.beginPath();
    ctx.moveTo(pad, y);
    ctx.lineTo(vw - pad, y);
    ctx.stroke();
  }
  const area = ctx.createLinearGradient(0, pad, 0, vh - pad);
  area.addColorStop(0, `${opts.color}44`);
  area.addColorStop(1, `${opts.color}06`);
  ctx.beginPath();
  values.forEach((v, i) => {
    const x = xAt(i);
    const y = yMap(v);
    if (i === 0) {
      ctx.moveTo(x, y);
    } else {
      const px = xAt(i - 1);
      const py = yMap(values[i - 1]);
      const mx = (px + x) / 2;
      ctx.quadraticCurveTo(px, py, mx, (py + y) / 2);
    }
  });
  const lx = xAt(values.length - 1);
  const ly = yMap(values[values.length - 1]);
  ctx.lineTo(lx, ly);
  ctx.lineTo(vw - pad, vh - pad);
  ctx.lineTo(pad, vh - pad);
  ctx.closePath();
  ctx.fillStyle = area;
  ctx.fill();
  ctx.beginPath();
  values.forEach((v, i) => {
    const x = xAt(i);
    const y = yMap(v);
    if (i === 0) {
      ctx.moveTo(x, y);
    } else {
      const px = xAt(i - 1);
      const py = yMap(values[i - 1]);
      const mx = (px + x) / 2;
      ctx.quadraticCurveTo(px, py, mx, (py + y) / 2);
    }
  });
  ctx.strokeStyle = opts.color;
  ctx.lineWidth = 2.2;
  ctx.stroke();
  if (opts.thresholds) {
    ctx.font = "11px 'JetBrains Mono'";
    opts.thresholds.forEach((t) => {
      const y = yMap(t.value);
      ctx.strokeStyle = t.color;
      ctx.setLineDash([5, 4]);
      ctx.beginPath();
      ctx.moveTo(pad, y);
      ctx.lineTo(vw - pad, y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = t.color;
      ctx.fillText(String(t.value), vw - pad - 34, y - 5);
    });
  }
}
function drawBars(canvasId, values, color) {
  const c = document.getElementById(canvasId);
  const { ctx, vw, vh } = setupHiDPI(c);
  if (!values || !values.length) {
    drawNoData(ctx, "No data");
    return;
  }
  const pad = 28;
  const max = Math.max(...values, 1);
  const barW = Math.max(2, (vw - pad * 2) / values.length - 2);
  values.forEach((v, i) => {
    const x = pad + i * (barW + 2);
    const hVal = (v / max) * (vh - pad * 2);
    const y = vh - pad - hVal;
    const g = ctx.createLinearGradient(0, y, 0, vh - pad);
    g.addColorStop(0, `${color}d8`);
    g.addColorStop(1, `${color}58`);
    const r = Math.min(5, barW / 2);
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.moveTo(x, vh - pad);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.lineTo(x + barW - r, y);
    ctx.quadraticCurveTo(x + barW, y, x + barW, y + r);
    ctx.lineTo(x + barW, vh - pad);
    ctx.closePath();
    ctx.fill();
  });
}
function trajectoryColor(tag, selected) {
  if (selected) return "#1185ff";
  if (tag === "high") return "#e35149";
  if (tag === "medium") return "#ec9b17";
  return "#92a7c0";
}
function computeBounds(points, padMeters = 0.3) {
  if (!points.length) {
    return { minX: -1, maxX: 1, minY: -1, maxY: 1 };
  }
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  let minX = Math.min(...xs), maxX = Math.max(...xs);
  let minY = Math.min(...ys), maxY = Math.max(...ys);
  if (minX === maxX) { minX -= 1; maxX += 1; }
  if (minY === maxY) { minY -= 1; maxY += 1; }
  return { minX: minX - padMeters, maxX: maxX + padMeters, minY: minY - padMeters, maxY: maxY + padMeters };
}
function buildScaler(vw, vh, bounds, pad = 34) {
  const spanX = Math.max(bounds.maxX - bounds.minX, 1e-6);
  const spanY = Math.max(bounds.maxY - bounds.minY, 1e-6);
  const innerW = Math.max(1, vw - pad * 2);
  const innerH = Math.max(1, vh - pad * 2);
  const metersToPx = Math.min(innerW / spanX, innerH / spanY);
  const drawW = spanX * metersToPx;
  const drawH = spanY * metersToPx;
  const offsetX = pad + (innerW - drawW) / 2;
  const offsetY = pad + (innerH - drawH) / 2;
  return {
    toX: (x) => offsetX + (x - bounds.minX) * metersToPx,
    toY: (y) => vh - (offsetY + (y - bounds.minY) * metersToPx),
    metersToPx,
    left: offsetX,
    right: offsetX + drawW,
    bottom: vh - offsetY,
    top: vh - offsetY - drawH,
  };
}
function drawGridLines(ctx, scaler, steps = 6) {
  ctx.strokeStyle = "#dbe8f8";
  ctx.lineWidth = 1;
  for (let i = 0; i < steps; i++) {
    const x = scaler.left + (i * (scaler.right - scaler.left) / Math.max(steps - 1, 1));
    ctx.beginPath();
    ctx.moveTo(x, scaler.top);
    ctx.lineTo(x, scaler.bottom);
    ctx.stroke();
  }
  for (let i = 0; i < steps; i++) {
    const y = scaler.top + (i * (scaler.bottom - scaler.top) / Math.max(steps - 1, 1));
    ctx.beginPath();
    ctx.moveTo(scaler.left, y);
    ctx.lineTo(scaler.right, y);
    ctx.stroke();
  }
}
function drawPolyline(ctx, scaler, points, color, width, alpha = 1, dashed = false) {
  if (!points || points.length < 2) return;
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  if (dashed) ctx.setLineDash([6, 5]);
  ctx.beginPath();
  points.forEach((p, idx) => {
    const x = scaler.toX(p[0]);
    const y = scaler.toY(p[1]);
    if (idx === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.restore();
}
function drawPolygon(ctx, scaler, points, stroke, fill, width = 2, alpha = 1) {
  if (!points || points.length < 2) return;
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.lineWidth = width;
  ctx.strokeStyle = stroke;
  if (fill) ctx.fillStyle = fill;
  ctx.beginPath();
  points.forEach((p, idx) => {
    const x = scaler.toX(p[0]);
    const y = scaler.toY(p[1]);
    if (idx === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.closePath();
  if (fill) ctx.fill();
  ctx.stroke();
  ctx.restore();
}
function drawPose(ctx, scaler, pose, color, label) {
  if (!pose) return;
  const x = scaler.toX(pose.x_mm / 1000);
  const y = scaler.toY(pose.y_mm / 1000);
  const theta = Number(pose.yaw_deg || 0) * Math.PI / 180;
  const arrowLen = 20;
  const endX = x + Math.cos(theta) * arrowLen;
  const endY = y - Math.sin(theta) * arrowLen;
  ctx.save();
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.lineWidth = 2.2;
  ctx.beginPath();
  ctx.moveTo(x, y);
  ctx.lineTo(endX, endY);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(endX, endY);
  ctx.lineTo(endX - 6 * Math.cos(theta - Math.PI / 6), endY + 6 * Math.sin(theta - Math.PI / 6));
  ctx.lineTo(endX - 6 * Math.cos(theta + Math.PI / 6), endY + 6 * Math.sin(theta + Math.PI / 6));
  ctx.closePath();
  ctx.fill();
  ctx.beginPath();
  ctx.arc(x, y, 3.2, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
  if (label) {
    ctx.fillStyle = color;
    ctx.font = "600 11px 'IBM Plex Sans'";
    ctx.fillText(label, x + 8, y - 8);
  }
}
function drawPointSet(ctx, scaler, points, color, radius = 4, labels = true) {
  if (!points) return;
  ctx.save();
  ctx.fillStyle = color;
  ctx.font = "600 10px 'IBM Plex Sans'";
  points.forEach((point) => {
    const x = scaler.toX(point.x_mm / 1000);
    const y = scaler.toY(point.y_mm / 1000);
    ctx.beginPath();
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    ctx.fill();
    if (labels && point.label) ctx.fillText(point.label, x + 6, y - 6);
  });
  ctx.restore();
}
function drawPointSetPx(ctx, scaler, points, color, radius = 4, labels = true) {
  if (!points) return;
  ctx.save();
  ctx.fillStyle = color;
  ctx.font = "600 10px 'IBM Plex Sans'";
  points.forEach((point) => {
    const x = scaler.toX(point.x_px);
    const y = scaler.toY(point.y_px);
    ctx.beginPath();
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    ctx.fill();
    if (labels && point.label) ctx.fillText(point.label, x + 6, y - 6);
  });
  ctx.restore();
}
function vehicleModelLocal(lengthMm, widthMm, rearMm) {
  const front = lengthMm - rearMm;
  const halfWidth = widthMm / 2;
  const wheelLength = Math.min(lengthMm * 0.18, 780);
  const wheelWidth = Math.min(widthMm * 0.12, 235);
  const wheelInset = halfWidth + wheelWidth * 0.1;
  const makeWheel = (centerX, side) => {
    const centerY = side * wheelInset;
    const hw = wheelLength / 2;
    const hh = wheelWidth / 2;
    return [
      [centerX - hw, centerY - hh],
      [centerX + hw, centerY - hh],
      [centerX + hw, centerY + hh],
      [centerX - hw, centerY + hh],
    ];
  };
  return {
    outline: [
      [-rear, halfWidth],
      [front, halfWidth],
      [front, -halfWidth],
      [-rear, -halfWidth],
    ],
    wheels: [
      makeWheel(-rear * 0.18, 1),
      makeWheel(-rear * 0.18, -1),
      makeWheel(front * 0.42, 1),
      makeWheel(front * 0.42, -1),
    ],
  };
}
function transformVehicleShape(points, pose, coordKeyX, coordKeyY, unitScale = 1) {
  const theta = Number(pose.yaw_deg || 0) * Math.PI / 180;
  const cosT = Math.cos(theta);
  const sinT = Math.sin(theta);
  return points.map(([lx, ly]) => {
    const x = pose[coordKeyX] + lx * cosT - ly * sinT;
    const y = pose[coordKeyY] + lx * sinT + ly * cosT;
    return unitScale === 1 ? [x, y] : [x / unitScale, y / unitScale];
  });
}
function vehicleGeometryFromPose(pose, spec = { lengthMm: 5260, widthMm: 1980, rearToCenterMm: 970 }) {
  if (!pose) return null;
  const model = vehicleModelLocal(spec.lengthMm, spec.widthMm, spec.rearToCenterMm);
  return {
    outline: transformVehicleShape(model.outline, pose, "x_mm", "y_mm", 1000),
    wheels: model.wheels.map((wheel) => transformVehicleShape(wheel, pose, "x_mm", "y_mm", 1000)),
  };
}
function drawVehicleOutline(ctx, scaler, pose, stroke, fill, label) {
  if (!pose) return;
  const geom = vehicleGeometryFromPose(pose);
  if (!geom || geom.outline.length < 3) return;
  ctx.save();
  ctx.lineJoin = "round";
  ctx.shadowColor = `${stroke}33`;
  ctx.shadowBlur = 4;
  drawPolygon(ctx, scaler, geom.outline, stroke, fill, 2.2, 1);
  ctx.restore();
  geom.wheels.forEach((wheel) => drawPolygon(ctx, scaler, wheel, "#0b1220", "rgba(15,23,42,0.88)", 1.1, 1));
  drawPose(ctx, scaler, pose, stroke, label);
}
function drawTrajectoryMap(selectedCycleIndex) {
  const c = document.getElementById("trajectoryCanvas");
  const { ctx, vw, vh } = setupHiDPI(c);
  const trajectories = data.trajectoryPreview || [];
  if (!trajectories.length) {
    drawNoData(ctx, "No trajectory preview data");
    return;
  }
  const allPts = [];
  trajectories.forEach((t) => (t.points_xy_m || []).forEach((p) => allPts.push(p)));
  if (!allPts.length) {
    drawNoData(ctx, "No trajectory points");
    return;
  }
  const scaler = buildScaler(vw, vh, computeBounds(allPts, 0.35), 34);
  drawGridLines(ctx, scaler, 6);
  trajectories.forEach((t) => {
    const pts = t.points_xy_m || [];
    if (pts.length < 2) return;
    const selected = t.cycle_index === selectedCycleIndex;
    const color = trajectoryColor(t.risk_tag, selected);
    ctx.lineWidth = selected ? 3 : 1.3;
    ctx.strokeStyle = color;
    ctx.globalAlpha = selected ? 1 : 0.32;
    if (selected) {
      ctx.shadowColor = `${color}88`;
      ctx.shadowBlur = 9;
    } else {
      ctx.shadowBlur = 0;
    }
    ctx.beginPath();
    pts.forEach((p, i) => {
      const x = scaler.toX(p[0]);
      const y = scaler.toY(p[1]);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
    ctx.shadowBlur = 0;
    if (selected) {
      const first = pts[0], last = pts[pts.length - 1];
      ctx.globalAlpha = 1;
      ctx.fillStyle = "#15a26e";
      ctx.beginPath();
      ctx.arc(scaler.toX(first[0]), scaler.toY(first[1]), 4.1, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#d43f3a";
      ctx.beginPath();
      ctx.arc(scaler.toX(last[0]), scaler.toY(last[1]), 4.1, 0, Math.PI * 2);
      ctx.fill();
    }
  });
  ctx.globalAlpha = 1;
}
function initTrajectorySelector() {
  const trajectories = data.trajectoryPreview || [];
  const sel = document.getElementById("trajectorySelect");
  const meta = document.getElementById("trajectoryMeta");
  if (!trajectories.length) {
    sel.innerHTML = "<option>No trajectory</option>";
    drawTrajectoryMap(-1);
    return;
  }
  sel.innerHTML = trajectories
    .map((t, i) => `<option value="${t.cycle_index}" ${i === 0 ? "selected" : ""}>Cycle ${t.cycle_index} (${t.risk_tag})</option>`)
    .join("");
  const refresh = () => {
    const target = Number(sel.value);
    const item = trajectories.find((t) => t.cycle_index === target) || trajectories[0];
    meta.textContent = `points=${item.point_count}, len=${item.path_length_m}m, yawJump=${item.yaw_jump_max_deg}, curv=${item.curv_abs_max}`;
    drawTrajectoryMap(item.cycle_index);
  };
  sel.addEventListener("change", refresh);
  refresh();
}
function renderCharts() {
  drawLine("timerChart", data.timerIntervals, {
    color: "#1976d2",
    thresholds: [
      { value: data.thresholds.timer_interval_low_ms, color: "#ec9b17" },
      { value: data.thresholds.timer_interval_high_ms, color: "#e35149" },
    ],
  });
  drawBars("forkChart", data.forkTimes, "#0ea5a4");
  drawLine("yawChart", data.yawJump, {
    color: "#de7f10",
    thresholds: [{ value: data.thresholds.yaw_jump_max_deg, color: "#d43f3a" }],
  });
  drawLine("pathChart", data.pathLength.map((v, i) => v + (data.curvAbs[i] || 0) * 20), {
    color: "#14866a",
  });
}
function renderWarnings() {
  const host = document.getElementById("vizWarnings");
  const warnings = data.visualizationWarnings || [];
  if (!warnings.length) {
    host.innerHTML = "";
    return;
  }
  host.innerHTML = `<div class="warning-strip card-shell" style="--d:0"><strong>Visualization warnings</strong><ul>${warnings.map((w) => `<li>${htmlEscape(w)}</li>`).join("")}</ul></div>`;
}
function svgFrames(kind) {
  const source = data.svgVisualizations || {};
  if (kind === "process") return source.processReplayFrames || [];
  if (kind === "grid") return source.gridMapFrames || [];
  return [];
}
function showVizSurface(image, src) {
  if (!src) {
    image.style.display = "none";
    image.removeAttribute("src");
    return;
  }
  image.style.display = "block";
  image.src = src;
}
const processState = { index: 0, timer: null };
function getProcessFrames() {
  return (data.processReplayData && data.processReplayData.frames) || [];
}
function processLayerState() {
  return {
    trajectory: document.getElementById("processShowTrajectory").checked,
    slot: document.getElementById("processShowSlot").checked,
    vehicle: document.getElementById("processShowVehicle").checked,
    targets: document.getElementById("processShowTargets").checked,
  };
}
function buildProcessBounds() {
  const fixed = data.processReplayData && data.processReplayData.fixed_bounds_mm;
  if (fixed) {
    return {
      minX: fixed.min_x_mm / 1000,
      maxX: fixed.max_x_mm / 1000,
      minY: fixed.min_y_mm / 1000,
      maxY: fixed.max_y_mm / 1000,
    };
  }
  const points = [];
  getProcessFrames().forEach((frame) => {
    (frame.trajectory_xy_mm || []).forEach((p) => points.push([p.x_mm / 1000, p.y_mm / 1000]));
    [frame.vehicle_location, frame.plan_stage_target_pose, frame.plan_final_target_pose].forEach((pose) => {
      if (pose) points.push([pose.x_mm / 1000, pose.y_mm / 1000]);
    });
    [frame.parking_space, frame.slot_corners, frame.target_slot_corners, frame.fused_p0_p5, frame.realtime_parkingspace].forEach((group) => {
      (group || []).forEach((p) => points.push([p.x_mm / 1000, p.y_mm / 1000]));
    });
  });
  return computeBounds(points, 0.4);
}
function processStatusValue(item) {
  if (!item) return "-";
  if (item.label) return `${item.value} · ${item.label}`;
  return safeText(item.value);
}
function renderProcessStatus(frame) {
  const grid = document.getElementById("processStatusGrid");
  const cards = [
    { key: "Plan Frame", value: safeText(frame.plan_frame_id), sub: safeText(frame.log_name) },
    { key: "Function Status", value: processStatusValue(frame.parking_function_status), sub: `stage ${processStatusValue(frame.parking_function_stage)}` },
    { key: "Mode / Gear", value: processStatusValue(frame.parking_function_mode), sub: `gear ${processStatusValue(frame.path_segment_target_gear)}` },
    { key: "Control / Motion", value: processStatusValue(frame.control_work_mode), sub: `motion ${processStatusValue(frame.vehicle_moving_status)}` },
    { key: "Target Poses", value: frame.plan_final_target_pose ? `${fmtNum(frame.plan_final_target_pose.x_mm / 1000, 2)}m, ${fmtNum(frame.plan_final_target_pose.y_mm / 1000, 2)}m` : "-", sub: frame.plan_stage_target_pose ? `stage ${fmtNum(frame.plan_stage_target_pose.x_mm / 1000, 2)}m, ${fmtNum(frame.plan_stage_target_pose.y_mm / 1000, 2)}m` : "-" },
    { key: "Vehicle", value: frame.vehicle_location ? `${fmtNum(frame.vehicle_location.x_mm / 1000, 2)}m, ${fmtNum(frame.vehicle_location.y_mm / 1000, 2)}m` : "-", sub: frame.vehicle_location ? `yaw ${fmtNum(frame.vehicle_location.yaw_deg, 1)}°` : "-" },
    { key: "Replan / Stop", value: processStatusValue(frame.replan_type), sub: `stop ${processStatusValue(frame.vehicle_stop_reason)}` },
    { key: "Fusion / Stopper", value: frame.perception_fusion_timestamp ? safeText(frame.perception_fusion_timestamp.value) : "-", sub: frame.stopper_distance_mm !== null && frame.stopper_distance_mm !== undefined ? `stopper ${fmtNum(frame.stopper_distance_mm, 0)} mm` : `fork ${safeText(frame.fork_star_start)}` },
  ];
  grid.innerHTML = cards.map((card) => `
    <div class="status-card">
      <div class="k">${htmlEscape(card.key)}</div>
      <div class="v">${htmlEscape(card.value)}</div>
      <div class="s">${htmlEscape(card.sub)}</div>
    </div>
  `).join("");
}
function drawProcessReplay() {
  const frames = getProcessFrames();
  const image = document.getElementById("processReplaySvg");
  const empty = document.getElementById("processReplayEmpty");
  const body = document.getElementById("processReplayBody");
  const boundary = document.getElementById("processReplayBoundary");
  const label = document.getElementById("processFrameLabel");
  if (!frames.length) {
    body.style.display = "none";
    empty.style.display = "block";
    empty.textContent = "No process replay frames extracted from the log. The section stays available so the report format remains stable.";
    return;
  }
  body.style.display = "";
  empty.style.display = "none";
  const frame = frames[Math.max(0, Math.min(processState.index, frames.length - 1))];
  label.textContent = `frame ${processState.index + 1} / ${frames.length}`;
  const svg = svgFrames("process")[processState.index] || "";
  if (!svg) {
    body.style.display = "none";
    empty.style.display = "block";
    empty.textContent = "matplotlib-svg process replay output is unavailable. Check visualization warnings above.";
    return;
  }
  renderProcessStatus(frame);
  showVizSurface(image, svg);
  const boundaries = (data.processReplayData && data.processReplayData.file_boundaries) || [];
  const activeBoundary = boundaries.find((item) => processState.index >= item.start_frame_index && processState.index <= item.end_frame_index) || boundaries[0];
  boundary.textContent = activeBoundary
    ? `source ${activeBoundary.filename} · frames ${activeBoundary.start_frame_index + 1}-${activeBoundary.end_frame_index + 1} · lines ${safeText(frame.source_line_count)}`
    : `source ${safeText(frame.log_name)} · lines ${safeText(frame.source_line_count)}`;
}
function stopProcessPlayback() {
  if (processState.timer) {
    clearInterval(processState.timer);
    processState.timer = null;
  }
  document.getElementById("processPlayBtn").textContent = "Play";
}
function startProcessPlayback() {
  const frames = getProcessFrames();
  if (!frames.length) return;
  stopProcessPlayback();
  const speed = Number(document.getElementById("processSpeedSelect").value || 1);
  processState.timer = window.setInterval(() => {
    processState.index = (processState.index + 1) % frames.length;
    document.getElementById("processFrameRange").value = String(processState.index);
    drawProcessReplay();
  }, Math.max(120, Math.round(320 / Math.max(speed, 0.25))));
  document.getElementById("processPlayBtn").textContent = "Pause";
}
function initProcessReplay() {
  const frames = getProcessFrames();
  const range = document.getElementById("processFrameRange");
  range.max = String(Math.max(frames.length - 1, 0));
  range.value = "0";
  range.addEventListener("input", () => {
    processState.index = Number(range.value || 0);
    drawProcessReplay();
  });
  document.getElementById("processPlayBtn").addEventListener("click", () => {
    if (processState.timer) stopProcessPlayback();
    else startProcessPlayback();
  });
  document.getElementById("processSpeedSelect").addEventListener("change", () => {
    if (processState.timer) startProcessPlayback();
  });
  ["processShowTrajectory", "processShowSlot", "processShowVehicle", "processShowTargets"].forEach((id) => {
    document.getElementById(id).disabled = true;
  });
  drawProcessReplay();
}
const gridCache = new Map();
function decodeGrid(base64, size) {
  const key = `${size}:${base64.slice(0, 32)}`;
  if (gridCache.has(key)) return gridCache.get(key);
  const raw = atob(base64 || "");
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  gridCache.set(key, out);
  return out;
}
function getGridFrames() {
  return (data.gridMapData && data.gridMapData.frames) || [];
}
function gridLayerState() {
  return {
    trajectory: document.getElementById("gridShowTrajectory").checked,
    slot: document.getElementById("gridShowSlot").checked,
    base: document.getElementById("gridShowBase").checked,
    poses: document.getElementById("gridShowPoses").checked,
  };
}
function buildGridPixelBounds(frame) {
  const size = Number(frame.grid_size || 512);
  return {
    minX: -0.5,
    maxX: size - 0.5,
    minY: -0.5,
    maxY: size - 0.5,
  };
}
function drawGridRaster(ctx, scaler, frame, alphaValue) {
  if (!frame.grid_b64) return;
  const size = Number(frame.grid_size || 0);
  if (!size) return;
  const arr = decodeGrid(frame.grid_b64, size);
  const off = document.createElement("canvas");
  off.width = size;
  off.height = size;
  const offCtx = off.getContext("2d");
  const img = offCtx.createImageData(size, size);
  for (let i = 0; i < arr.length; i++) {
    const value = arr[i];
    const px = i * 4;
    const shade = Math.max(0, Math.min(255, value));
    img.data[px] = shade;
    img.data[px + 1] = shade;
    img.data[px + 2] = shade;
    img.data[px + 3] = 255;
  }
  offCtx.putImageData(img, 0, 0);
  ctx.save();
  ctx.globalAlpha = Math.max(0.2, Math.min(alphaValue, 1));
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(off, scaler.left, scaler.top, scaler.right - scaler.left, scaler.bottom - scaler.top);
  ctx.restore();
}
function drawGridPixelOverlay(ctx, scaler, frame) {
  const size = Number(frame.grid_size || 512);
  const resolution = Number(frame.resolution_mm_per_cell || 100);
  ctx.save();
  ctx.strokeStyle = "rgba(40, 96, 176, 0.30)";
  ctx.lineWidth = 0.9;
  for (let i = 0; i < size; i += 10) {
    const x = scaler.toX(i);
    ctx.beginPath();
    ctx.moveTo(x, scaler.top);
    ctx.lineTo(x, scaler.bottom);
    ctx.stroke();
    const y = scaler.toY(i);
    ctx.beginPath();
    ctx.moveTo(scaler.left, y);
    ctx.lineTo(scaler.right, y);
    ctx.stroke();
  }
  ctx.strokeStyle = "#9bb7d5";
  ctx.strokeRect(scaler.left, scaler.top, scaler.right - scaler.left, scaler.bottom - scaler.top);
  ctx.fillStyle = "#4e6988";
  ctx.font = "10px 'JetBrains Mono'";
  for (let i = 0; i < size; i += 50) {
    const label = `${Math.round(i * resolution / 1000)}m`;
    ctx.fillText(label, scaler.toX(i) - 10, scaler.bottom + 16);
    ctx.fillText(label, scaler.left - 28, scaler.toY(i) + 3);
  }
  ctx.restore();
}
function drawPosePx(ctx, scaler, pose, color, label) {
  if (!pose) return;
  const x = scaler.toX(pose.x_px);
  const y = scaler.toY(pose.y_px);
  const yaw = (Number(pose.yaw_deg || 0) - 90) * Math.PI / 180;
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(yaw);
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.moveTo(0, -10);
  ctx.lineTo(6, 8);
  ctx.lineTo(-6, 8);
  ctx.closePath();
  ctx.fill();
  ctx.restore();
  if (label) {
    ctx.fillStyle = color;
    ctx.font = "600 11px 'IBM Plex Sans'";
    ctx.fillText(label, x + 8, y - 8);
  }
}
function drawPolylinePx(ctx, scaler, points, color, width, alpha = 1) {
  if (!points || points.length < 2) return;
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.beginPath();
  points.forEach((p, idx) => {
    const x = scaler.toX(p.x_px);
    const y = scaler.toY(p.y_px);
    if (idx === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.restore();
}
function drawPolygonPx(ctx, scaler, points, stroke, fill, width = 2, alpha = 1) {
  if (!points || points.length < 2) return;
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.lineWidth = width;
  ctx.strokeStyle = stroke;
  if (fill) ctx.fillStyle = fill;
  ctx.beginPath();
  points.forEach((p, idx) => {
    const x = scaler.toX(p.x_px);
    const y = scaler.toY(p.y_px);
    if (idx === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.closePath();
  if (fill) ctx.fill();
  ctx.stroke();
  ctx.restore();
}
function vehicleOutlineFromPosePx(pose, resolutionMm, spec = { lengthMm: 5250, widthMm: 2000, rearAxleToRearMm: 1134 }) {
  if (!pose) return [];
  const geom = vehicleGeometryFromPosePx(pose, resolutionMm, spec);
  return geom ? geom.outline : [];
}
function transformVehicleShapePx(points, pose) {
  const theta = Number(pose.yaw_deg || 0) * Math.PI / 180;
  const cosT = Math.cos(theta);
  const sinT = Math.sin(theta);
  return points.map(([lx, ly]) => ({
    x_px: pose.x_px + lx * cosT - ly * sinT,
    y_px: pose.y_px + lx * sinT + ly * cosT,
  }));
}
function vehicleGeometryFromPosePx(pose, resolutionMm, spec = { lengthMm: 5250, widthMm: 2000, rearAxleToRearMm: 1134 }) {
  if (!pose) return null;
  const model = vehicleModelLocal(spec.lengthMm / resolutionMm, spec.widthMm / resolutionMm, spec.rearAxleToRearMm / resolutionMm);
  return {
    outline: transformVehicleShapePx(model.outline, pose),
    wheels: model.wheels.map((wheel) => transformVehicleShapePx(wheel, pose)),
  };
}
function drawVehicleOutlinePx(ctx, scaler, pose, resolutionMm, opts) {
  if (!pose) return;
  const geom = vehicleGeometryFromPosePx(pose, resolutionMm, opts.spec);
  if (!geom || geom.outline.length < 3) return;
  ctx.save();
  ctx.lineJoin = "round";
  ctx.shadowColor = `${opts.edge}33`;
  ctx.shadowBlur = 4;
  drawPolygonPx(ctx, scaler, geom.outline, opts.edge, opts.fill, 2.5, opts.alpha ?? 1);
  ctx.restore();
  geom.wheels.forEach((wheel) => drawPolygonPx(ctx, scaler, wheel, "#0b1220", "rgba(15,23,42,0.9)", 1.1, 1));
  const rearX = scaler.toX(pose.x_px);
  const rearY = scaler.toY(pose.y_px);
  ctx.save();
  ctx.fillStyle = opts.edge;
  ctx.beginPath();
  ctx.arc(rearX, rearY, 5.8, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = opts.labelBg || opts.edge;
  const text = opts.label || "";
  if (text) {
    ctx.font = "700 11px 'IBM Plex Sans'";
    const width = Math.max(34, ctx.measureText(text).width + 10);
    ctx.fillRect(rearX + 6, rearY - 18, width, 18);
    ctx.fillStyle = opts.labelColor || "#fff";
    ctx.fillText(text, rearX + 11, rearY - 5);
  }
  const theta = Number(pose.yaw_deg || 0) * Math.PI / 180;
  const endX = rearX + Math.cos(theta) * 20;
  const endY = rearY - Math.sin(theta) * 20;
  ctx.strokeStyle = opts.edge;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(rearX, rearY);
  ctx.lineTo(endX, endY);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(endX, endY);
  ctx.lineTo(endX - 5 * Math.cos(theta - Math.PI / 6), endY + 5 * Math.sin(theta - Math.PI / 6));
  ctx.lineTo(endX - 5 * Math.cos(theta + Math.PI / 6), endY + 5 * Math.sin(theta + Math.PI / 6));
  ctx.closePath();
  ctx.fillStyle = opts.edge;
  ctx.fill();
  ctx.restore();
}
function drawSlotOverlayPx(ctx, scaler, points) {
  if (!points || points.length < 4) return;
  drawPolygonPx(ctx, scaler, points, "#d43f3a", "rgba(255, 221, 87, 0.34)", 2.2, 1);
  const colors = ["#d43f3a", "#1c9d65", "#1f77cf", "#d48806"];
  ctx.save();
  ctx.font = "700 11px 'IBM Plex Sans'";
  points.slice(0, 4).forEach((point, idx) => {
    const x = scaler.toX(point.x_px);
    const y = scaler.toY(point.y_px);
    ctx.fillStyle = colors[idx % colors.length];
    ctx.beginPath();
    ctx.arc(x, y, 4.2, 0, Math.PI * 2);
    ctx.fill();
    const label = htmlEscape((point.label || String.fromCharCode(65 + idx)).replace("_abs", ""));
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(x + 4, y - 17, 18, 14);
    ctx.fillStyle = colors[idx % colors.length];
    ctx.fillText(label, x + 8, y - 6);
  });
  ctx.restore();
}
function drawTrajectoryDetailedPx(ctx, scaler, points, resolutionMm) {
  if (!points || points.length < 2) return;
  drawPolylinePx(ctx, scaler, points, "#0b63ce", 2.0, 0.72);
  const boxInterval = Math.max(1, Math.floor(points.length / 80));
  for (let i = 0; i < points.length; i += boxInterval) {
    const box = vehicleOutlineFromPosePx(points[i], resolutionMm, { lengthMm: 5200, widthMm: 2000, rearAxleToRearMm: 1000 });
    drawPolygonPx(ctx, scaler, box, "rgba(0, 215, 255, 0.45)", "rgba(0, 215, 255, 0.15)", 1.0, 1);
  }
  const arrowInterval = Math.max(1, Math.floor(points.length / 10));
  ctx.save();
  ctx.strokeStyle = "#0b63ce";
  ctx.fillStyle = "#0b63ce";
  ctx.lineWidth = 0.8;
  for (let i = 0; i < points.length; i += arrowInterval) {
    const point = points[i];
    const x = scaler.toX(point.x_px);
    const y = scaler.toY(point.y_px);
    const theta = Number(point.yaw_deg || 0) * Math.PI / 180;
    const dx = Math.cos(theta) * 5;
    const dy = -Math.sin(theta) * 5;
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(x + dx, y + dy);
    ctx.stroke();
  }
  const start = points[0];
  const end = points[points.length - 1];
  [[start, "#15a26e", "Start"], [end, "#d43f3a", "End"]].forEach(([point, color, label]) => {
    const x = scaler.toX(point.x_px);
    const y = scaler.toY(point.y_px);
    ctx.fillStyle = String(color);
    ctx.beginPath();
    ctx.arc(x, y, 5.2, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(x + 5, y - 17, 28, 14);
    ctx.fillStyle = String(color);
    ctx.font = "700 10px 'IBM Plex Sans'";
    ctx.fillText(String(label), x + 9, y - 7);
  });
  ctx.restore();
}
function renderGridMeta(frame) {
  const host = document.getElementById("gridMapMeta");
  const cards = [
    { key: "Frame", value: `${safeText(frame.frame_index)} / ${getGridFrames().length}` },
    { key: "Grid", value: `${safeText(frame.grid_size)} x ${safeText(frame.grid_size)} @ ${fmtNum(frame.resolution_mm_per_cell, 0)} mm` },
    { key: "Timestamp", value: safeText(frame.timestamp_ns) },
    { key: "Ego Pose", value: frame.ego_pose ? `${fmtNum(frame.ego_pose.x_mm / 1000, 2)}m, ${fmtNum(frame.ego_pose.y_mm / 1000, 2)}m / ${fmtNum(frame.ego_pose.yaw_deg, 1)}°` : "-" },
    { key: "Target Pose", value: frame.target_pose ? `${fmtNum(frame.target_pose.x_mm / 1000, 2)}m, ${fmtNum(frame.target_pose.y_mm / 1000, 2)}m / ${fmtNum(frame.target_pose.yaw_deg, 1)}°` : "-" },
    { key: "Trajectory Points", value: safeText((frame.trajectory || []).length) },
  ];
  host.innerHTML = cards.map((card) => `
    <div class="meta-box">
      <div class="k">${htmlEscape(card.key)}</div>
      <div class="v">${htmlEscape(card.value)}</div>
    </div>
  `).join("");
}
function drawGridMap() {
  const frames = getGridFrames();
  const image = document.getElementById("gridMapSvg");
  const empty = document.getElementById("gridMapEmpty");
  const body = document.getElementById("gridMapBody");
  const label = document.getElementById("gridFrameLabel");
  if (!frames.length) {
    body.style.display = "none";
    empty.style.display = "block";
    empty.textContent = "planner_inputs.csv was not available or could not be parsed. Diagnosis and trajectory outputs remain valid.";
    return;
  }
  body.style.display = "block";
  empty.style.display = "none";
  const select = document.getElementById("gridFrameSelect");
  const index = Math.max(0, Math.min(Number(select.value || 0), frames.length - 1));
  const frame = frames[index];
  label.textContent = `frame ${index + 1} / ${frames.length}`;
  const svg = svgFrames("grid")[index] || "";
  if (!svg) {
    body.style.display = "none";
    empty.style.display = "block";
    empty.textContent = "matplotlib-svg gridmap output is unavailable. Check visualization warnings above.";
    return;
  }
  renderGridMeta(frame);
  showVizSurface(image, svg);
}
function initGridMap() {
  const frames = getGridFrames();
  const select = document.getElementById("gridFrameSelect");
  if (!frames.length) {
    select.innerHTML = '<option value="0">No frame</option>';
  } else {
    select.innerHTML = frames.map((frame, idx) => {
      const suffix = frame.timestamp_ns ? " · " + frame.timestamp_ns : "";
      return `<option value="${idx}">Frame ${idx + 1}${suffix}</option>`;
    }).join("");
  }
  select.addEventListener("change", drawGridMap);
  ["gridShowTrajectory", "gridShowSlot", "gridShowBase", "gridShowPoses"].forEach((id) => {
    document.getElementById(id).disabled = true;
  });
  document.getElementById("gridAlphaRange").disabled = true;
  drawGridMap();
}
function populateAnomalies() {
  const tbody = document.querySelector("#anomalyTable tbody");
  tbody.innerHTML = "";
  (data.anomalies || []).forEach((a) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${htmlEscape(a.rule || "")}</td><td class="sev-${a.severity || "low"}">${htmlEscape(a.severity || "")}</td><td>${htmlEscape(a.count ?? "")}</td><td>${htmlEscape(a.detail || "")}</td>`;
    tbody.appendChild(tr);
  });
}
function redrawAll() {
  renderCharts();
  const sel = document.getElementById("trajectorySelect");
  drawTrajectoryMap(Number(sel && sel.value ? sel.value : -1));
  drawProcessReplay();
  drawGridMap();
}
renderWarnings();
renderCharts();
initTrajectorySelector();
initProcessReplay();
initGridMap();
populateAnomalies();
window.addEventListener("resize", redrawAll);
window.addEventListener("beforeunload", stopProcessPlayback);
</script>
</body>
</html>
"""
    replacements = {
        "__LOG_NAME__": log_name_safe,
        "__LOG_PATH__": log_path_safe,
        "__SUMMARY__": summary_safe,
        "__RISK_CLASS__": risk_class,
        "__RISK_LEVEL__": risk_level,
        "__SCORE__": str(score),
        "__FOCUS__": str(key_metrics.get("risk_breakdown", {}).get("focus", "comprehensive")),
        "__PROFILE__": profile.name,
        "__CYCLE_COUNT__": str(key_metrics.get("cycle_count", 0)),
        "__CYCLE_WITH_POINTS__": str(key_metrics.get("cycle_with_points_count", 0)),
        "__PARSED_LINES__": str(key_metrics.get("parsed_line_count", 0)),
        "__LINE_COUNT__": str(key_metrics.get("line_count", 0)),
        "__TIMER_JITTER__": str(key_metrics.get("timer_jitter_count", 0)),
        "__TIMER_RANGE__": timer_range,
        "__REPLAN_RATIO__": str(key_metrics.get("replan_ratio", 0.0)),
        "__REPLAN_STREAK__": str(key_metrics.get("longest_replan_streak", 0)),
        "__HIGH_ANOMALY_COUNT__": str(sum(1 for anomaly in anomalies if anomaly.get("severity") == "high")),
        "__YAW_LIMIT__": yaw_limit,
        "__DATA_JSON__": data_json,
    }
    out = html_template
    for key, value in replacements.items():
        out = out.replace(key, value)
    return out
