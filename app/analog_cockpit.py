from __future__ import annotations


ANALOG_COCKPIT_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>The Abode</title>
<style>
:root {
  --bg: #11120f;
  --bg-soft: #171913;
  --panel: rgba(24, 27, 21, 0.88);
  --panel-strong: rgba(18, 21, 16, 0.94);
  --line: rgba(185, 196, 162, 0.16);
  --line-strong: rgba(185, 196, 162, 0.28);
  --text: #ebe6d5;
  --muted: #a5a08d;
  --soft: #706d5d;
  --accent: #7bb79f;
  --accent-2: #8ed0b3;
  --accent-warm: #c1a66c;
  --danger: #cc6c6c;
  --ok: #7bc49f;
  --shadow: 0 24px 80px rgba(0, 0, 0, 0.35);
  --radius-xl: 28px;
  --radius-lg: 22px;
  --radius-md: 16px;
  --radius-sm: 12px;
}

* { box-sizing: border-box; }
html, body { margin: 0; min-height: 100%; background: var(--bg); color: var(--text); }
body {
  font-family: Inter, "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  background:
    radial-gradient(circle at top left, rgba(102, 145, 125, 0.18), transparent 28%),
    radial-gradient(circle at top right, rgba(77, 117, 133, 0.12), transparent 26%),
    linear-gradient(180deg, #121310 0%, #0f100d 100%);
}
body::before {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  opacity: 0.16;
  background:
    repeating-linear-gradient(
      0deg,
      rgba(255,255,255,0.02) 0,
      rgba(255,255,255,0.02) 1px,
      transparent 1px,
      transparent 6px
    ),
    repeating-linear-gradient(
      90deg,
      rgba(255,255,255,0.015) 0,
      rgba(255,255,255,0.015) 1px,
      transparent 1px,
      transparent 7px
    );
}

.shell {
  display: grid;
  grid-template-columns: 248px minmax(0, 1fr);
  min-height: 100vh;
  gap: 18px;
  padding: 18px;
}

.rail, .panel, .hero {
  border: 1px solid var(--line);
  background: var(--panel);
  box-shadow: var(--shadow);
  backdrop-filter: blur(16px);
}

.rail {
  border-radius: 30px;
  padding: 20px 18px 18px;
  display: flex;
  flex-direction: column;
  gap: 18px;
  position: sticky;
  top: 18px;
  height: calc(100vh - 36px);
}

.brand {
  padding: 6px 8px 12px;
  border-bottom: 1px solid var(--line);
}
.brand-kicker,
.meta-line,
.eyebrow,
.small-label,
.pill,
.nav-btn,
.action-btn,
.chip {
  font-family: "SFMono-Regular", "IBM Plex Mono", "Menlo", "Monaco", monospace;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.brand-kicker {
  color: var(--accent);
  font-size: 11px;
  margin-bottom: 8px;
}
.brand-title {
  font-size: 30px;
  line-height: 1;
  margin: 0;
}
.brand-copy {
  margin-top: 10px;
  color: var(--muted);
  font-size: 14px;
  line-height: 1.5;
}

.status-stack, .nav-stack, .rail-footer {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.status-chip {
  padding: 12px 14px;
  border-radius: 16px;
  border: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.02);
}
.status-chip strong {
  display: block;
  font-size: 12px;
  color: var(--text);
}
.status-chip span {
  display: block;
  margin-top: 6px;
  font-size: 12px;
  color: var(--muted);
}
.status-chip.condensed strong {
  font-size: 13px;
}
.status-chip.condensed span {
  margin-top: 4px;
  line-height: 1.45;
}

.nav-btn {
  border: 1px solid transparent;
  background: transparent;
  color: var(--muted);
  padding: 14px 16px;
  border-radius: 18px;
  text-align: left;
  cursor: pointer;
  transition: 0.2s ease;
  font-size: 12px;
}
.nav-btn.active,
.nav-btn:hover {
  border-color: var(--line-strong);
  color: var(--text);
  background: linear-gradient(135deg, rgba(124, 182, 159, 0.12), rgba(255,255,255,0.02));
}
.nav-label {
  padding: 6px 16px 0;
  color: var(--soft);
  font-size: 10px;
}
.nav-btn.secondary {
  color: #8f9388;
  padding-top: 12px;
  padding-bottom: 12px;
}

.rail-footer {
  margin-top: auto;
  padding: 12px 8px 2px;
  border-top: 1px solid var(--line);
  color: var(--soft);
  font-size: 12px;
}

.workspace {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 6px 6px 0;
}
.topbar-title {
  font-size: 32px;
  margin: 0;
}
.topbar-copy {
  color: var(--muted);
  margin-top: 6px;
  font-size: 15px;
}
.topbar-meta {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.pill {
  border: 1px solid var(--line-strong);
  border-radius: 999px;
  padding: 10px 13px;
  font-size: 11px;
  color: var(--muted);
  background: rgba(255,255,255,0.03);
}

.view {
  display: none;
  grid-template-columns: minmax(0, 1fr);
  gap: 18px;
}
.view.active { display: grid; }

.hero {
  border-radius: var(--radius-xl);
  padding: 26px;
  background:
    radial-gradient(circle at top right, rgba(120, 186, 160, 0.26), transparent 30%),
    linear-gradient(145deg, rgba(16, 33, 28, 0.96), rgba(19, 25, 22, 0.92));
}
.hero-grid {
  display: grid;
  grid-template-columns: 1.15fr 0.85fr;
  gap: 18px;
  align-items: end;
}
.hero .eyebrow {
  color: var(--accent-2);
  font-size: 11px;
  margin-bottom: 12px;
}
.hero h2 {
  margin: 0;
  font-size: 42px;
  line-height: 0.95;
}
.hero-copy {
  margin-top: 14px;
  max-width: 620px;
  color: var(--muted);
  font-size: 16px;
  line-height: 1.6;
}
.hero-number {
  font-size: 62px;
  line-height: 0.95;
  text-align: right;
}
.hero-subnumber {
  margin-top: 10px;
  text-align: right;
  color: var(--muted);
  font-size: 14px;
}
.hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 22px;
}

.card-grid {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  gap: 18px;
}
.panel {
  border-radius: var(--radius-lg);
  padding: 20px;
  min-width: 0;
}
.span-12 { grid-column: span 12; }
.span-8 { grid-column: span 8; }
.span-7 { grid-column: span 7; }
.span-6 { grid-column: span 6; }
.span-5 { grid-column: span 5; }
.span-4 { grid-column: span 4; }

.panel-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 18px;
}
.panel-title {
  margin: 0;
  font-size: 24px;
}
.panel-meta {
  color: var(--soft);
  font-size: 12px;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}
.metric {
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 14px;
  background: rgba(255,255,255,0.02);
}
.metric .small-label {
  font-size: 11px;
  color: var(--soft);
}
.metric .metric-value {
  margin-top: 8px;
  font-size: 28px;
  line-height: 1;
}
.metric .metric-note {
  margin-top: 6px;
  color: var(--muted);
  font-size: 12px;
}

.signal-row,
.lane-row,
.feed-list,
.stack-list,
.chat-history,
.summary-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.lane-card,
.feed-item,
.summary-item,
.chat-msg,
.signal-card {
  border: 1px solid var(--line);
  border-radius: 18px;
  padding: 15px 16px;
  background: rgba(255,255,255,0.025);
}
.signal-card.buy,
.feed-item.ok {
  background: linear-gradient(135deg, rgba(91, 144, 123, 0.18), rgba(255,255,255,0.02));
}
.signal-card.sell,
.feed-item.warn {
  background: linear-gradient(135deg, rgba(132, 59, 59, 0.24), rgba(255,255,255,0.02));
}
.signal-card.hold {
  background: linear-gradient(135deg, rgba(81, 92, 82, 0.18), rgba(255,255,255,0.02));
}

.summary-item strong,
.lane-card strong,
.signal-head,
.feed-item strong {
  display: block;
  font-size: 14px;
}
.summary-item span,
.lane-card span,
.feed-item span {
  display: block;
  margin-top: 6px;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.5;
}

.signal-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
}
.signal-kicker {
  color: var(--accent-2);
  font-size: 11px;
}
.signal-body {
  margin-top: 10px;
  color: var(--muted);
  line-height: 1.6;
}

.proposal-actions,
.controls-actions,
.chat-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.doc-reader {
  min-height: 520px;
  border: 1px solid var(--line);
  border-radius: 20px;
  padding: 22px;
  background: rgba(255,255,255,0.02);
  line-height: 1.7;
  color: var(--muted);
}
.doc-reader h1,
.doc-reader h2,
.doc-reader h3 {
  color: var(--text);
  margin: 0 0 12px;
}
.doc-reader h1 { font-size: 28px; }
.doc-reader h2 { font-size: 22px; margin-top: 20px; }
.doc-reader h3 { font-size: 18px; margin-top: 16px; }
.doc-reader p,
.doc-reader ul {
  margin: 0 0 12px;
}
.doc-reader ul {
  padding-left: 18px;
}
.doc-reader li {
  margin-bottom: 6px;
}
.doc-reader code {
  color: var(--text);
  background: rgba(255,255,255,0.05);
  border-radius: 8px;
  padding: 2px 6px;
}

.action-btn,
.chip {
  border: 1px solid var(--line-strong);
  background: rgba(255,255,255,0.03);
  color: var(--text);
  border-radius: 999px;
  padding: 11px 15px;
  cursor: pointer;
  font-size: 11px;
  transition: 0.2s ease;
}
.action-btn:hover,
.chip:hover { border-color: var(--accent); color: var(--accent-2); }
.chip.active {
  border-color: rgba(123, 183, 159, 0.5);
  color: #d6f0e5;
  background: linear-gradient(135deg, rgba(123, 183, 159, 0.18), rgba(255,255,255,0.03));
}
.action-btn.primary {
  background: linear-gradient(135deg, rgba(123, 183, 159, 0.2), rgba(255,255,255,0.03));
}
.action-btn.warn {
  border-color: rgba(204, 108, 108, 0.3);
}
.action-btn:disabled,
.chip:disabled {
  opacity: 0.46;
  cursor: not-allowed;
  color: var(--soft);
  border-color: var(--line);
}
.action-btn.live {
  border-color: rgba(76, 203, 138, 0.42);
  color: #c6f4da;
  background: linear-gradient(135deg, rgba(60, 187, 123, 0.2), rgba(255,255,255,0.03));
}
.feed-item.pending {
  background: linear-gradient(135deg, rgba(176, 139, 75, 0.24), rgba(255,255,255,0.02));
}
.check-item {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 12px;
  align-items: start;
}
.check-badge {
  min-width: 66px;
  text-align: center;
  border-radius: 999px;
  padding: 6px 10px;
  border: 1px solid var(--line-strong);
  font-size: 10px;
  color: var(--muted);
  background: rgba(255,255,255,0.03);
}
.check-item.pass .check-badge {
  border-color: rgba(76, 203, 138, 0.35);
  color: #c6f4da;
  background: rgba(60, 187, 123, 0.16);
}
.check-item.fail .check-badge {
  border-color: rgba(204, 108, 108, 0.35);
  color: #ffd0d0;
  background: rgba(162, 70, 70, 0.16);
}
.ledger-meta {
  display: block;
  margin-top: 8px;
  color: var(--soft);
  font-size: 11px;
}

.chat-history {
  min-height: 280px;
  max-height: 460px;
  overflow: auto;
}
.chat-msg.operator {
  align-self: flex-end;
  background: rgba(255,255,255,0.05);
}
.chat-msg.agent {
  align-self: flex-start;
}
.chat-msg small {
  display: block;
  margin-bottom: 8px;
  color: var(--soft);
  font-size: 11px;
  font-family: "SFMono-Regular", "IBM Plex Mono", "Menlo", monospace;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}
.chat-msg p {
  margin: 0;
  line-height: 1.6;
  color: var(--text);
  white-space: pre-wrap;
}

textarea.chat-input {
  width: 100%;
  min-height: 104px;
  resize: vertical;
  border-radius: 18px;
  border: 1px solid var(--line);
  background: rgba(8, 10, 8, 0.46);
  color: var(--text);
  padding: 14px 16px;
  font: inherit;
  line-height: 1.6;
}
textarea.chat-input:focus {
  outline: none;
  border-color: var(--accent);
}

.empty-copy,
.muted-copy {
  color: var(--muted);
  line-height: 1.6;
}

.mobile-nav {
  display: none;
}

.terminal-panel {
  background:
    radial-gradient(circle at top right, rgba(59, 184, 122, 0.12), transparent 26%),
    linear-gradient(180deg, rgba(13, 16, 21, 0.96), rgba(10, 13, 18, 0.98));
  border-color: rgba(110, 126, 119, 0.22);
}

.market-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.ticker-card {
  position: relative;
  overflow: hidden;
  border: 1px solid rgba(102, 114, 128, 0.26);
  border-radius: 20px;
  padding: 16px 18px;
  background:
    radial-gradient(circle at top right, rgba(93, 209, 143, 0.16), transparent 30%),
    linear-gradient(180deg, rgba(15, 18, 24, 0.98), rgba(9, 11, 15, 0.98));
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.03);
}
.ticker-card.down {
  background:
    radial-gradient(circle at top right, rgba(221, 88, 88, 0.16), transparent 30%),
    linear-gradient(180deg, rgba(18, 15, 18, 0.98), rgba(11, 9, 11, 0.98));
}
.ticker-card.flat {
  background:
    radial-gradient(circle at top right, rgba(130, 148, 168, 0.12), transparent 30%),
    linear-gradient(180deg, rgba(15, 18, 24, 0.98), rgba(9, 11, 15, 0.98));
}
.ticker-label,
.ticker-note,
.tape-mini,
.action-badge,
.chart-chip {
  font-family: "SFMono-Regular", "IBM Plex Mono", "Menlo", "Monaco", monospace;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}
.ticker-label {
  color: #73808e;
  font-size: 10px;
}
.ticker-value {
  margin-top: 10px;
  font-size: 30px;
  line-height: 1;
}
.ticker-delta {
  margin-top: 8px;
  font-size: 12px;
  font-weight: 600;
}
.ticker-delta.up { color: #59d98e; }
.ticker-delta.down { color: #ff7f7f; }
.ticker-delta.flat { color: #a7b1bc; }
.ticker-note {
  margin-top: 8px;
  font-size: 10px;
  color: #667280;
}

.belfort-desk {
  align-items: stretch;
}

.market-board {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(300px, 0.85fr);
  gap: 18px;
}

.account-board,
.control-card {
  border: 1px solid rgba(105, 118, 133, 0.18);
  border-radius: 22px;
  padding: 18px;
  background: rgba(255,255,255,0.02);
}

.account-top {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
}
.hero-copy.compact {
  margin-top: 10px;
  max-width: none;
  font-size: 14px;
}
.account-value {
  min-width: 180px;
  text-align: right;
}
.account-number {
  font-size: 48px;
  line-height: 0.95;
}
.account-subnumber {
  margin-top: 8px;
  color: var(--muted);
  font-size: 13px;
}

.chart-frame {
  margin-top: 18px;
  border: 1px solid rgba(92, 108, 123, 0.22);
  border-radius: 20px;
  padding: 16px;
  background:
    linear-gradient(180deg, rgba(8, 11, 15, 0.98), rgba(12, 15, 19, 0.98));
}
.chart-meta {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}
.chart-chip {
  color: #7f8d9b;
  font-size: 10px;
}
.chart-toolbar {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}
.chart-toolbar .chip {
  cursor: pointer;
}
.candle-strip {
  margin-top: 18px;
  height: 220px;
  border-radius: 16px;
  overflow: hidden;
  background:
    linear-gradient(180deg, rgba(255,255,255,0.015), rgba(255,255,255,0.01)),
    linear-gradient(180deg, rgba(6, 10, 14, 0.98), rgba(10, 14, 18, 0.98));
  border: 1px solid rgba(100, 118, 136, 0.16);
}
.candle-strip svg {
  width: 100%;
  height: 100%;
  display: block;
}
.chart-empty {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #91a2b2;
  font-size: 13px;
  padding: 0 18px;
  text-align: center;
}
.chart-grid line {
  stroke: rgba(255,255,255,0.06);
  stroke-width: 1;
}
.chart-price-line {
  stroke: rgba(149, 201, 255, 0.42);
  stroke-width: 1.5;
  stroke-dasharray: 4 6;
}
.chart-price-tag {
  fill: #bcd7ef;
  font-size: 11px;
}
.chart-wick {
  stroke-width: 2;
  stroke-linecap: round;
}
.chart-wick.up,
.chart-body.up {
  stroke: rgba(83, 220, 153, 0.95);
  fill: rgba(60, 190, 129, 0.95);
}
.chart-wick.down,
.chart-body.down {
  stroke: rgba(255, 111, 111, 0.95);
  fill: rgba(214, 79, 79, 0.95);
}
.chart-wick.flat,
.chart-body.flat {
  stroke: rgba(165, 177, 188, 0.88);
  fill: rgba(132, 144, 155, 0.88);
}
.chart-volume.up { fill: rgba(56, 185, 128, 0.36); }
.chart-volume.down { fill: rgba(210, 88, 88, 0.28); }
.chart-volume.flat { fill: rgba(129, 141, 152, 0.22); }
.chart-axis-tag {
  fill: rgba(174, 188, 201, 0.72);
  font-size: 11px;
}

.metric-grid-terminal {
  margin-top: 16px;
}
.metric-grid-terminal .metric {
  background: rgba(255,255,255,0.03);
}
.metric-grid-terminal .metric-value {
  font-size: 24px;
}

.terminal-side {
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.button-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}
.button-grid .action-btn {
  width: 100%;
  justify-content: center;
}

.action-status-card {
  position: relative;
  overflow: hidden;
  border-radius: 18px;
  border: 1px solid rgba(92, 108, 123, 0.22);
  padding: 16px;
  background: rgba(255,255,255,0.025);
}
.action-status-card.ok {
  background: linear-gradient(135deg, rgba(48, 136, 94, 0.22), rgba(255,255,255,0.03));
}
.action-status-card.warn {
  background: linear-gradient(135deg, rgba(131, 46, 46, 0.28), rgba(255,255,255,0.03));
}
.action-status-card.pending {
  background: linear-gradient(135deg, rgba(176, 139, 75, 0.24), rgba(255,255,255,0.03));
}
.action-status-card strong {
  display: block;
  margin-top: 8px;
  font-size: 15px;
}
.action-status-card span {
  display: block;
  margin-top: 6px;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.5;
}
.action-badge {
  color: #8090a1;
  font-size: 10px;
}

.signal-card {
  background: linear-gradient(180deg, rgba(10, 13, 18, 0.96), rgba(16, 19, 24, 0.98));
}
.signal-card.buy {
  background: linear-gradient(135deg, rgba(49, 143, 101, 0.22), rgba(255,255,255,0.02));
}
.signal-card.sell {
  background: linear-gradient(135deg, rgba(139, 58, 58, 0.28), rgba(255,255,255,0.02));
}
.signal-card.hold {
  background: linear-gradient(135deg, rgba(81, 92, 102, 0.2), rgba(255,255,255,0.02));
}
.signal-quote {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: baseline;
  margin-top: 12px;
}
.signal-price {
  font-size: 28px;
  line-height: 1;
}
.signal-side {
  text-align: right;
  color: var(--muted);
  font-size: 12px;
}

.lane-card,
.summary-item,
.feed-item {
  background: rgba(255,255,255,0.02);
}
.lane-card strong,
.summary-item strong,
.feed-item strong {
  color: #edf3fb;
}

.feed-item.micro strong {
  font-size: 13px;
}
.feed-item.micro span {
  font-size: 12px;
}

.belfort-workspace {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.workspace-tabs {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.workspace-tab {
  border: 1px solid rgba(118, 128, 142, 0.22);
  background: rgba(255,255,255,0.02);
  color: #9ba4af;
  border-radius: 999px;
  padding: 10px 14px;
  cursor: pointer;
  font-size: 11px;
  font-family: "SFMono-Regular", "IBM Plex Mono", "Menlo", "Monaco", monospace;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  transition: 0.18s ease;
}
.workspace-tab:hover,
.workspace-tab.active {
  color: #eef4fb;
  border-color: rgba(90, 208, 141, 0.4);
  background: linear-gradient(135deg, rgba(62, 176, 120, 0.18), rgba(255,255,255,0.03));
}

.workspace-pane { display: none; }
.workspace-pane.active { display: block; }

.terminal-summary {
  display: flex;
  justify-content: space-between;
  gap: 18px;
  align-items: center;
}
.terminal-summary-copy {
  color: var(--muted);
  font-size: 13px;
  line-height: 1.6;
}
.terminal-summary-copy strong {
  color: #eef4fb;
  display: block;
  margin-bottom: 4px;
  font-size: 14px;
}
.terminal-summary-kicker {
  color: var(--soft);
  font-size: 11px;
  font-family: "SFMono-Regular", "IBM Plex Mono", "Menlo", "Monaco", monospace;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.terminal-surface {
  background:
    radial-gradient(circle at top right, rgba(48, 179, 118, 0.08), transparent 28%),
    linear-gradient(180deg, rgba(11, 14, 18, 0.98), rgba(10, 12, 17, 0.98));
  border-color: rgba(96, 106, 118, 0.2);
}

.trade-grid {
  display: grid;
  grid-template-columns: minmax(260px, 300px) minmax(0, 1fr) minmax(300px, 340px);
  gap: 18px;
  align-items: start;
}
.trade-column.tight {
  gap: 14px;
}
.trade-column,
.trade-center {
  display: flex;
  flex-direction: column;
  gap: 18px;
  min-width: 0;
}
.terminal-surface.compact {
  padding-bottom: 16px;
}

.watchlist-list,
.blotter-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.watchlist-list.scroll,
.blotter-list.scroll {
  max-height: 620px;
  overflow: auto;
  padding-right: 4px;
}

.watchlist-row,
.blotter-item {
  border: 1px solid rgba(111, 124, 138, 0.18);
  border-radius: 16px;
  padding: 12px 13px;
  background: rgba(255,255,255,0.02);
}
.watchlist-row.focus {
  border-color: rgba(86, 206, 141, 0.32);
  background: linear-gradient(135deg, rgba(42, 142, 98, 0.18), rgba(255,255,255,0.02));
}
.watchlist-row.warn,
.blotter-item.warn {
  background: linear-gradient(135deg, rgba(120, 56, 56, 0.18), rgba(255,255,255,0.02));
}
.blotter-item.ok {
  background: linear-gradient(135deg, rgba(42, 142, 98, 0.18), rgba(255,255,255,0.02));
}

.watchlist-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}
.watchlist-symbol {
  font-size: 15px;
  font-weight: 700;
  color: #eef4fb;
}
.watchlist-score,
.blotter-item small,
.watch-badge,
.tight-chip {
  font-family: "SFMono-Regular", "IBM Plex Mono", "Menlo", "Monaco", monospace;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}
.watchlist-score,
.blotter-item small {
  color: var(--soft);
  font-size: 10px;
}
.watchlist-note {
  margin-top: 7px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.55;
}
.watchlist-note.secondary {
  color: #8c97a3;
}
.watchlist-note strong {
  color: #d9e4ef;
  font-weight: 600;
}
.watchlist-footer,
.tight-chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}
.watch-badge,
.tight-chip {
  border: 1px solid rgba(111, 124, 138, 0.18);
  border-radius: 999px;
  padding: 5px 9px;
  color: #9ba4af;
  font-size: 10px;
}
.watch-badge.eligible {
  border-color: rgba(86, 206, 141, 0.28);
  color: #9ce4bc;
  background: rgba(42, 142, 98, 0.16);
}
.watch-badge.watch_only {
  border-color: rgba(111, 124, 138, 0.24);
  color: #c7cdd6;
}
.watch-badge.blocked {
  border-color: rgba(199, 102, 102, 0.28);
  color: #e6a7a7;
  background: rgba(120, 56, 56, 0.16);
}

.focus-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
}
.focus-symbol {
  font-size: 44px;
  line-height: 0.94;
  font-weight: 650;
  letter-spacing: -0.04em;
}
.focus-meta {
  color: var(--muted);
  font-size: 14px;
  line-height: 1.7;
  max-width: 560px;
}
.trade-block {
  border-top: 1px solid rgba(111, 124, 138, 0.15);
  padding-top: 14px;
}
.trade-block:first-child {
  border-top: 0;
  padding-top: 0;
}
.trade-block-title {
  margin: 0 0 12px;
  color: #eef4fb;
  font-size: 15px;
  font-weight: 650;
}
.panel-kicker {
  margin: 0 0 10px;
  color: #8f9aa6;
  font-size: 12px;
  line-height: 1.55;
}

.trade-signal-panel {
  display: grid;
  gap: 16px;
}

.leader-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.leader-card {
  border: 1px solid rgba(111, 124, 138, 0.18);
  border-radius: 14px;
  padding: 12px;
  background: rgba(255,255,255,0.02);
}

.leader-card.focus {
  border-color: rgba(86, 206, 141, 0.32);
  background: linear-gradient(135deg, rgba(42, 142, 98, 0.18), rgba(255,255,255,0.02));
}

.leader-card-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
}

.leader-card-title {
  color: #eef4fb;
  font-size: 14px;
  font-weight: 650;
}

.leader-card-score {
  color: #9ce4bc;
  font-size: 10px;
  font-family: "SFMono-Regular", "IBM Plex Mono", "Menlo", "Monaco", monospace;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.leader-card-copy {
  margin-top: 8px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.5;
}

.trade-shell {
  display: grid;
  gap: 18px;
}

.trade-console-stack {
  display: grid;
  gap: 14px;
}

.trade-console-card {
  border-top: 1px solid rgba(111, 124, 138, 0.15);
  padding-top: 14px;
}

.trade-console-card:first-of-type {
  border-top: 0;
  padding-top: 0;
}

.compact-summary {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.proof-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}
.proof-item {
  border: 1px solid rgba(111, 124, 138, 0.18);
  border-radius: 14px;
  padding: 12px;
  background: rgba(255,255,255,0.02);
}
.proof-head {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: center;
}
.proof-title {
  color: #eef4fb;
  font-size: 13px;
  font-weight: 650;
}
.proof-status {
  border-radius: 999px;
  padding: 4px 8px;
  font-size: 10px;
  border: 1px solid rgba(111, 124, 138, 0.18);
  color: #b7c0cb;
  font-family: "SFMono-Regular", "IBM Plex Mono", "Menlo", "Monaco", monospace;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}
.proof-status.ready {
  border-color: rgba(86, 206, 141, 0.28);
  color: #9ce4bc;
}
.proof-status.blocked {
  border-color: rgba(199, 102, 102, 0.28);
  color: #e6a7a7;
}
.proof-status.warming {
  border-color: rgba(193, 166, 108, 0.28);
  color: #e5ca8c;
}
.proof-note {
  margin-top: 9px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.55;
}
.compact-row {
  display: grid;
  grid-template-columns: 108px 1fr;
  gap: 12px;
  align-items: start;
}
.compact-row-label {
  color: #7f8d9b;
  font-size: 11px;
  font-family: "SFMono-Regular", "IBM Plex Mono", "Menlo", "Monaco", monospace;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}
.compact-row-value {
  color: var(--text);
  font-size: 13px;
  line-height: 1.55;
}

.scanner-shell,
.research-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.12fr) minmax(300px, 0.88fr);
  gap: 18px;
  align-items: start;
}
.scanner-primary,
.scanner-side {
  display: grid;
  gap: 18px;
}
.stack-grid {
  display: grid;
  gap: 18px;
}
.stack-grid.two {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}
.scanner-summary-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.scanner-summary-card,
.radar-card {
  border: 1px solid rgba(111, 124, 138, 0.18);
  border-radius: 16px;
  padding: 14px;
  background: rgba(255,255,255,0.02);
}
.scanner-summary-card strong,
.radar-card strong {
  display: block;
  color: #eef4fb;
  font-size: 14px;
}
.scanner-summary-card span,
.radar-card span {
  display: block;
  margin-top: 8px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.55;
}
.scanner-filter-panel {
  display: grid;
  gap: 12px;
  margin-bottom: 14px;
}
.filter-group {
  display: grid;
  gap: 8px;
}
.filter-group-label {
  color: #8f9aa6;
  font-size: 11px;
  font-family: "SFMono-Regular", "IBM Plex Mono", "Menlo", "Monaco", monospace;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}
.filter-group .proposal-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.leaderboard-list {
  display: grid;
  gap: 12px;
}
.leaderboard-card {
  border: 1px solid rgba(111, 124, 138, 0.18);
  border-radius: 16px;
  padding: 14px;
  background: rgba(255,255,255,0.02);
}
.leaderboard-card strong {
  color: #eef4fb;
  display: block;
  font-size: 14px;
}
.leaderboard-card span {
  display: block;
  margin-top: 8px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.55;
}
.leader-symbols {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.leader-symbol {
  border: 1px solid rgba(111, 124, 138, 0.18);
  border-radius: 999px;
  padding: 5px 8px;
  font-size: 10px;
  color: #c7d1dd;
  font-family: "SFMono-Regular", "IBM Plex Mono", "Menlo", "Monaco", monospace;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}
.radar-grid {
  display: grid;
  gap: 10px;
}
.radar-card {
  cursor: pointer;
  transition: 0.18s ease;
}
.radar-card.active,
.radar-card:hover {
  border-color: rgba(90, 208, 141, 0.34);
  background: linear-gradient(135deg, rgba(42, 142, 98, 0.14), rgba(255,255,255,0.02));
}
.radar-count {
  color: #9ce4bc;
  font-size: 10px;
  font-family: "SFMono-Regular", "IBM Plex Mono", "Menlo", "Monaco", monospace;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}
.radar-symbols {
  margin-top: 8px;
  color: #c7d1dd;
  font-size: 12px;
  line-height: 1.5;
}
.radar-empty {
  color: #8f9aa6;
  font-size: 12px;
}

.doc-grid {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 18px;
}
.guide-shell .doc-reader {
  min-height: 680px;
}

@media (max-width: 1120px) {
  .shell {
    grid-template-columns: 1fr;
    padding-bottom: 96px;
  }
  .rail {
    display: none;
  }
  .hero-grid,
  .metric-grid {
    grid-template-columns: 1fr;
  }
  .hero-number,
  .hero-subnumber {
    text-align: left;
  }
  .market-strip,
  .market-board,
  .trade-grid,
  .scanner-shell,
  .research-grid,
  .doc-grid,
  .stack-grid.two,
  .scanner-summary-grid,
  .leader-strip,
  .button-grid {
    grid-template-columns: 1fr;
  }
  .account-top {
    flex-direction: column;
  }
  .account-value {
    min-width: 0;
    text-align: left;
  }
  .candle-strip {
    height: 180px;
  }
  .watchlist-list.scroll,
  .blotter-list.scroll {
    max-height: none;
  }
  .span-8, .span-7, .span-6, .span-5, .span-4 { grid-column: span 12; }
  .mobile-nav {
    position: fixed;
    left: 14px;
    right: 14px;
    bottom: 14px;
    display: grid;
    grid-template-columns: repeat(6, 1fr);
    gap: 8px;
    padding: 10px;
    border: 1px solid var(--line);
    border-radius: 24px;
    background: rgba(20, 22, 18, 0.94);
    backdrop-filter: blur(16px);
    box-shadow: var(--shadow);
    z-index: 50;
  }
  .mobile-nav .nav-btn {
    text-align: center;
    padding: 12px 10px;
    border-radius: 16px;
    font-size: 10px;
  }
}
</style>
</head>
<body>
<div class="shell">
  <aside class="rail">
    <div class="brand">
      <div class="brand-kicker">Deliberate Surface</div>
      <h1 class="brand-title">The Abode</h1>
      <div class="brand-copy">A calm operator cockpit for Peter, Belfort, and Frank Lloyd. Easier to navigate, quieter to read, and built for steady decision-making.</div>
    </div>
    <div class="status-stack">
      <div class="status-chip condensed"><strong id="rail-mode">Belfort: --</strong><span id="rail-readiness">Readiness loading...</span></div>
      <div class="status-chip condensed"><strong id="rail-loop">Paper lane: --</strong><span id="rail-sim">Session loading...</span></div>
    </div>
    <nav class="nav-stack">
      <button class="nav-btn active" data-view="overview">Overview</button>
      <button class="nav-btn" data-view="belfort">Mr Belfort</button>
      <div class="nav-label">House</div>
      <button class="nav-btn secondary" data-view="peter">Peter</button>
      <button class="nav-btn secondary" data-view="frank">Frank Lloyd</button>
      <div class="nav-label">Operations</div>
      <button class="nav-btn" data-view="controls">Controls</button>
      <button class="nav-btn" data-view="guide">Guide</button>
    </nav>
    <div class="rail-footer">
      <div id="rail-clock">--</div>
      <div id="rail-refresh">Waiting for state...</div>
    </div>
  </aside>

  <main class="workspace">
    <header class="topbar">
      <div>
        <h1 class="topbar-title" id="topbar-title">Overview</h1>
        <div class="topbar-copy" id="topbar-copy">A slower, clearer operating surface for the house.</div>
      </div>
      <div class="topbar-meta">
        <div class="pill" id="pill-backend">Backend --</div>
        <div class="pill" id="pill-lm">LM --</div>
        <div class="pill" id="pill-refresh">Refresh --</div>
      </div>
    </header>

    <section class="view active" id="view-overview">
      <section class="hero">
        <div class="hero-grid">
          <div>
            <div class="eyebrow">Whole House</div>
            <h2 id="overview-hero-title">Operating with deliberate calm.</h2>
            <div class="hero-copy" id="overview-hero-copy">Loading system state...</div>
            <div class="hero-actions">
              <button class="chip" onclick="showView('belfort')">Open Belfort</button>
              <button class="chip" onclick="showView('peter')">Ask Peter</button>
              <button class="chip" onclick="showView('frank')">Talk to Frank</button>
            </div>
          </div>
          <div>
            <div class="hero-number" id="overview-hero-number">--</div>
            <div class="hero-subnumber" id="overview-hero-subnumber">Portfolio value and active posture</div>
          </div>
        </div>
      </section>
      <section class="card-grid">
        <article class="panel span-12">
          <div class="panel-head"><h3 class="panel-title">House State</h3><div class="panel-meta">Fast read</div></div>
          <div class="metric-grid" id="overview-metrics"></div>
        </article>
        <article class="panel span-7">
          <div class="panel-head"><h3 class="panel-title">Attention</h3><div class="panel-meta">What matters now</div></div>
          <div class="summary-list" id="overview-attention"></div>
        </article>
        <article class="panel span-5">
          <div class="panel-head"><h3 class="panel-title">Recent Flow</h3><div class="panel-meta">Belfort + Frank</div></div>
          <div class="feed-list" id="overview-activity"></div>
        </article>
      </section>
    </section>

    <section class="view" id="view-belfort">
      <section class="market-strip" id="belfort-market-strip"></section>
      <section class="belfort-workspace">
        <section class="panel terminal-panel terminal-summary">
          <div class="terminal-summary-copy">
            <strong id="belfort-hero-title">Mr Belfort</strong>
            <div id="belfort-hero-copy">Loading Belfort desk...</div>
          </div>
          <div class="terminal-summary-kicker">Trading desk / operator-first workspace</div>
        </section>
        <div class="workspace-tabs" id="belfort-workspace-tabs">
          <button class="workspace-tab active" onclick="setBelfortWorkspace('trade')">Trade</button>
          <button class="workspace-tab" onclick="setBelfortWorkspace('scanner')">Scanner</button>
          <button class="workspace-tab" onclick="setBelfortWorkspace('research')">Research</button>
          <button class="workspace-tab" onclick="setBelfortWorkspace('guide')">Guide</button>
        </div>

        <section class="workspace-pane active" id="belfort-pane-trade">
          <div class="trade-grid">
            <div class="trade-column tight">
              <article class="panel terminal-surface compact">
                <div class="panel-head"><h3 class="panel-title">Trading Shortlist</h3><div class="panel-meta">Focus, open names, and paper candidates</div></div>
                <div class="panel-kicker">Trade keeps only the current desk shortlist. Open Scanner for the full board, filters, catalysts, and leader decks.</div>
                <div class="watchlist-list scroll" id="belfort-watchlist"></div>
                <div class="watchlist-footer">
                  <button class="chip" onclick="setBelfortWorkspace('scanner')">Open scanner</button>
                  <button class="chip" onclick="setBelfortWorkspace('research')">Open research</button>
                </div>
              </article>
              <article class="panel terminal-surface compact">
                <div class="panel-head"><h3 class="panel-title">Market Pulse</h3><div class="panel-meta">Leaders worth a closer look</div></div>
                <div class="summary-list" id="belfort-live-leaders"></div>
              </article>
            </div>

            <div class="trade-center">
              <article class="panel terminal-surface">
                <div class="focus-header">
                  <div>
                    <div class="eyebrow">Focus symbol</div>
                    <div class="focus-symbol" id="belfort-focus-symbol">--</div>
                  </div>
                  <div class="tight-chip-row" id="belfort-focus-badges"></div>
                </div>
                <div class="focus-meta" id="belfort-focus-meta">Loading scanner focus...</div>
                <div class="trade-block">
                  <div class="trade-block-title">Opening-Drive Leaders</div>
                  <div class="panel-kicker">Best paper-eligible names for the current session, ranked for clean tape and opening-drive potential.</div>
                  <div class="leader-strip" id="belfort-opening-drive-strip"></div>
                </div>
                <div class="chart-frame">
                  <div class="chart-meta">
                    <div class="small-label">Live chart</div>
                    <div class="chart-toolbar">
                      <div class="chart-chip" id="belfort-chart-meta">Loading Belfort chart...</div>
                      <div id="belfort-chart-toolbar"></div>
                    </div>
                  </div>
                  <div class="candle-strip" id="belfort-chart"></div>
                </div>
                <div class="metric-grid metric-grid-terminal" id="belfort-trade-metrics"></div>
              </article>
              <article class="panel terminal-surface">
                <div class="trade-signal-panel">
                  <div>
                    <div class="trade-block-title">Current Signal</div>
                    <div class="signal-row" id="belfort-signal"></div>
                  </div>
                  <div>
                    <div class="trade-block-title">Recent Trading Flow</div>
                    <div class="blotter-list" id="belfort-blotter-compact"></div>
                  </div>
                </div>
              </article>
            </div>

            <div class="trade-column">
              <article class="panel terminal-surface">
                <div class="panel-head"><h3 class="panel-title">Trade Console</h3><div class="panel-meta">Account, controls, readiness</div></div>
                <div class="trade-console-stack">
                  <div id="belfort-action-status"></div>
                  <div class="button-grid" id="belfort-console-actions"></div>
                  <div class="trade-console-card">
                    <div class="trade-block-title">Account</div>
                    <div class="compact-summary" id="belfort-account-summary"></div>
                  </div>
                  <div class="trade-console-card">
                    <div class="trade-block-title">Order State</div>
                    <div class="compact-summary" id="belfort-order-summary"></div>
                  </div>
                  <div class="trade-console-card">
                    <div class="trade-block-title">Order Monitor</div>
                    <div class="compact-summary" id="belfort-order-monitor"></div>
                  </div>
                  <div class="trade-console-card">
                    <div class="trade-block-title">Ready at Open</div>
                    <div class="compact-summary" id="belfort-readiness-compact"></div>
                  </div>
                  <div class="trade-console-card">
                    <div class="trade-block-title">Why Not Trading</div>
                    <div class="compact-summary" id="belfort-why-not-trading"></div>
                  </div>
                  <div class="trade-console-card">
                    <div class="trade-block-title">Open Proof</div>
                    <div class="proof-grid" id="belfort-open-proof"></div>
                  </div>
                </div>
              </article>
            </div>
          </div>
        </section>

        <section class="workspace-pane" id="belfort-pane-scanner">
          <div class="scanner-shell">
            <div class="scanner-primary">
              <article class="panel terminal-surface compact">
                <div class="panel-head"><h3 class="panel-title">Scanner Overview</h3><div class="panel-meta">Focus, paper focus, and board scope</div></div>
                <div class="scanner-summary-grid" id="belfort-scanner-overview"></div>
              </article>
              <article class="panel terminal-surface">
                <div class="panel-head"><h3 class="panel-title">Scanner Board</h3><div class="panel-meta">Ranked names with guided filters</div></div>
                <div class="scanner-filter-panel">
                  <div class="filter-group">
                    <div class="filter-group-label">Board view</div>
                    <div class="proposal-actions" id="belfort-scanner-filter-toolbar"></div>
                  </div>
                  <div class="filter-group">
                    <div class="filter-group-label">Setup type</div>
                    <div class="proposal-actions" id="belfort-scanner-setup-toolbar"></div>
                  </div>
                  <div class="filter-group">
                    <div class="filter-group-label">Market cap</div>
                    <div class="proposal-actions" id="belfort-scanner-cap-filter-toolbar"></div>
                  </div>
                  <div class="filter-group">
                    <div class="filter-group-label">Float</div>
                    <div class="proposal-actions" id="belfort-scanner-float-filter-toolbar"></div>
                  </div>
                </div>
                <div class="watchlist-list scroll" id="belfort-scanner"></div>
              </article>
            </div>
            <div class="scanner-side">
              <article class="panel terminal-surface">
                <div class="panel-head"><h3 class="panel-title">Leaderboards</h3><div class="panel-meta">Best names by flow and opening-drive pressure</div></div>
                <div class="leaderboard-list" id="belfort-flow-leaders"></div>
              </article>
              <article class="panel terminal-surface">
                <div class="panel-head"><h3 class="panel-title">Setup Radar</h3><div class="panel-meta">Click a setup lane to jump to the names behind it</div></div>
                <div class="radar-grid" id="belfort-radar"></div>
                <div class="trade-block">
                  <div class="trade-block-title">Radar Detail</div>
                  <div class="summary-list" id="belfort-radar-detail"></div>
                </div>
              </article>
              <article class="panel terminal-surface">
                <div class="panel-head"><h3 class="panel-title">Catalyst Desk</h3><div class="panel-meta">Fresh headlines and trade drivers</div></div>
                <div class="feed-list" id="belfort-catalysts"></div>
              </article>
              <article class="panel terminal-surface">
                <div class="panel-head"><h3 class="panel-title">Tape Context</h3><div class="panel-meta">Which names are clean, leading, or risky?</div></div>
                <div class="summary-list" id="belfort-tradeability"></div>
              </article>
            </div>
          </div>
        </section>

        <section class="workspace-pane" id="belfort-pane-research">
          <div class="research-grid">
            <div class="stack-grid">
              <article class="panel terminal-surface">
                <div class="panel-head"><h3 class="panel-title">Research</h3><div class="panel-meta">Learning verdict and environment read</div></div>
                <div class="summary-list" id="belfort-learning"></div>
              </article>
              <article class="panel terminal-surface">
                <div class="panel-head"><h3 class="panel-title">Setup Scorecards</h3><div class="panel-meta">Which patterns are earning trust?</div></div>
                <div class="summary-list" id="belfort-setups"></div>
              </article>
              <article class="panel terminal-surface">
                <div class="panel-head"><h3 class="panel-title">Blotter</h3><div class="panel-meta">Recent signal, paper, sim, and adjustment flow</div></div>
                <div class="proposal-actions" id="belfort-ledger-toolbar"></div>
                <div class="blotter-list scroll" id="belfort-feed"></div>
              </article>
            </div>
            <div class="stack-grid">
              <article class="panel terminal-surface">
                <div class="panel-head"><h3 class="panel-title">Readiness</h3><div class="panel-meta">Full open checklist</div></div>
                <div class="summary-list" id="belfort-readiness"></div>
              </article>
              <article class="panel terminal-surface">
                <div class="panel-head"><h3 class="panel-title">Adjustment Desk</h3><div class="panel-meta">Bounded and auditable</div></div>
                <div class="summary-list" id="belfort-proposal"></div>
                <div class="proposal-actions" id="belfort-proposal-actions"></div>
              </article>
              <article class="panel terminal-surface">
                <div class="panel-head"><h3 class="panel-title">Strategy</h3><div class="panel-meta">Policy selection and regime read</div></div>
                <div class="summary-list" id="belfort-policy"></div>
              </article>
              <article class="panel terminal-surface">
                <div class="panel-head"><h3 class="panel-title">Execution Lanes</h3><div class="panel-meta">Paper and sim stay separate</div></div>
                <div class="lane-row" id="belfort-lanes"></div>
              </article>
            </div>
          </div>
        </section>

        <section class="workspace-pane" id="belfort-pane-guide">
          <div class="doc-grid guide-shell">
            <article class="panel terminal-surface">
              <div class="panel-head"><h3 class="panel-title">How Belfort Works</h3><div class="panel-meta">Operator walkthrough</div></div>
              <div class="summary-list" id="belfort-guide-summary"></div>
              <div class="proposal-actions" id="belfort-guide-toolbar"></div>
            </article>
            <article class="panel terminal-surface">
              <div class="panel-head"><h3 class="panel-title" id="belfort-guide-doc-title">Guide</h3><div class="panel-meta" id="belfort-guide-doc-meta">Belfort docs</div></div>
              <div class="doc-reader" id="belfort-guide-doc">Loading Belfort guide...</div>
            </article>
          </div>
        </section>
      </section>
    </section>

    <section class="view" id="view-peter">
      <section class="card-grid">
        <article class="panel span-12">
          <div class="panel-head"><h3 class="panel-title">Peter</h3><div class="panel-meta">Front door and coordinator</div></div>
          <div class="summary-list" id="peter-summary"></div>
        </article>
        <article class="panel span-12">
          <div class="panel-head"><h3 class="panel-title">Ask Peter</h3><div class="panel-meta">Whole-house guidance</div></div>
          <div class="chat-history" id="peter-chat-history"></div>
          <div class="chat-row" style="margin-top:12px">
            <textarea id="peter-chat-input" class="chat-input" placeholder="Ask Peter what matters, what needs review, or what to do next."></textarea>
          </div>
          <div class="chat-row" style="margin-top:12px">
            <button class="action-btn primary" id="peter-send" onclick="peterSend()">Send</button>
            <button class="action-btn" onclick="fillPeter('What needs my attention right now?')">Needs attention</button>
            <button class="action-btn" onclick="fillPeter('What should I do next?')">What next</button>
            <button class="action-btn" onclick="fillPeter('Explain Belfort progress for my mentor')">Belfort progress</button>
          </div>
        </article>
      </section>
    </section>

    <section class="view" id="view-frank">
      <section class="card-grid">
        <article class="panel span-12">
          <div class="panel-head"><h3 class="panel-title">Frank Lloyd</h3><div class="panel-meta">Builder / operator</div></div>
          <div class="summary-list" id="frank-summary"></div>
        </article>
        <article class="panel span-12">
          <div class="panel-head"><h3 class="panel-title">Talk to Frank Lloyd</h3><div class="panel-meta">Builds, drafts, apply flow</div></div>
          <div class="chat-history" id="frank-chat-history"></div>
          <div class="chat-row" style="margin-top:12px">
            <textarea id="frank-chat-input" class="chat-input" placeholder="Tell Frank Lloyd what to build, approve, draft, or ship."></textarea>
          </div>
          <div class="chat-row" style="margin-top:12px">
            <button class="action-btn primary" id="frank-send" onclick="frankSend()">Send</button>
            <button class="action-btn" onclick="fillFrank('What are you working on right now?')">Status</button>
            <button class="action-btn" onclick="fillFrank('Approve the current Frank Lloyd plan')">Approve plan</button>
            <button class="action-btn" onclick="fillFrank('Generate the current draft')">Generate draft</button>
          </div>
        </article>
      </section>
    </section>

    <section class="view" id="view-controls">
      <section class="card-grid">
        <article class="panel span-12">
          <div class="panel-head"><h3 class="panel-title">Controls</h3><div class="panel-meta">Calm, bounded, operator-visible</div></div>
          <div class="controls-actions">
            <button class="action-btn primary" onclick="controlAction('start-paper')">Start Paper Loop</button>
            <button class="action-btn" onclick="controlAction('stop-paper')">Stop Paper Loop</button>
            <button class="action-btn" onclick="controlAction('start-sim')">Start Sim</button>
            <button class="action-btn" onclick="controlAction('stop-sim')">Stop Sim</button>
            <button class="action-btn" onclick="controlAction('advance-mode')">Advance Belfort Mode</button>
            <button class="action-btn warn" onclick="controlAction('reset-paper')">Reset Paper Portfolio</button>
          </div>
        </article>
        <article class="panel span-6">
          <div class="panel-head"><h3 class="panel-title">Control State</h3><div class="panel-meta">Current lanes</div></div>
          <div class="summary-list" id="controls-summary"></div>
        </article>
        <article class="panel span-6">
          <div class="panel-head"><h3 class="panel-title">Action Feed</h3><div class="panel-meta">This session</div></div>
          <div class="feed-list" id="controls-feed"></div>
        </article>
      </section>
    </section>

    <section class="view" id="view-guide">
      <section class="card-grid">
        <article class="panel span-4">
          <div class="panel-head"><h3 class="panel-title">How Belfort Works</h3><div class="panel-meta">Readable operator guide</div></div>
          <div class="summary-list" id="guide-summary"></div>
          <div class="proposal-actions" id="guide-toolbar"></div>
        </article>
        <article class="panel span-8">
          <div class="panel-head"><h3 class="panel-title" id="guide-doc-title">Guide</h3><div class="panel-meta" id="guide-doc-meta">Belfort docs</div></div>
          <div class="doc-reader" id="guide-doc">Loading Belfort guide...</div>
        </article>
      </section>
    </section>
  </main>
</div>

<nav class="mobile-nav">
  <button class="nav-btn active" data-view="overview">Overview</button>
  <button class="nav-btn" data-view="belfort">Belfort</button>
  <button class="nav-btn" data-view="peter">Peter</button>
  <button class="nav-btn" data-view="frank">Frank</button>
  <button class="nav-btn" data-view="controls">Controls</button>
  <button class="nav-btn" data-view="guide">Guide</button>
</nav>

<script>
const VIEW_META = {
  overview: ['Overview', 'A slower, clearer operating surface for the house.'],
  belfort: ['Mr Belfort', 'Trading desk, scanner, research, and guide in one operator-first workspace.'],
  peter: ['Peter', 'Front door, coordination, and next-step guidance.'],
  frank: ['Frank Lloyd', 'Direct builder/operator surface for changes and workflows.'],
  controls: ['Controls', 'Bounded operator actions across the house.'],
  guide: ['Guide', 'How Belfort works, what he trades, and what the desk is connected to.'],
};

let _state = null;
let _learning = null;
let _proposal = null;
let _strategy = null;
let _regime = null;
let _docs = {current: 'BELFORT_HOW_IT_WORKS.md', cache: {}};
let _peterChat = [{role: 'agent', text: 'Peter is ready. Ask what matters, what needs review, or what to do next.'}];
let _frankChat = [{role: 'agent', text: 'Frank Lloyd is ready. Tell him what to build or what build action to take.'}];
let _controlFeed = [{kind: 'ok', title: 'Surface ready', text: 'Waiting for the first refresh from the backend.'}];
let _belfortAction = {kind: 'ok', title: 'Desk ready', text: 'Use the trade console to start paper, start sim, or apply a bounded adjustment.'};
let _belfortPendingAction = null;
let _belfortLedgerFilter = 'all';
let _belfortWorkspace = 'trade';
let _belfortScannerFilter = 'leaders';
let _belfortScannerSetupFilter = 'all';
let _belfortScannerMarketCapFilter = 'all';
let _belfortScannerFloatFilter = 'all';
let _belfortChartTimeframe = '5Min';
let _belfortChart = null;
let _currentView = 'overview';

function esc(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function fmtMoney(value) {
  const n = Number(value || 0);
  const abs = Math.abs(n);
  if (abs >= 1000000) return (n < 0 ? '-$' : '$') + (abs / 1000000).toFixed(2) + 'm';
  if (abs >= 1000) return (n < 0 ? '-$' : '$') + (abs / 1000).toFixed(1) + 'k';
  return (n < 0 ? '-$' : '$') + abs.toFixed(2);
}

function fmtPct(value) {
  if (value == null || Number.isNaN(Number(value))) return '--';
  return Math.round(Number(value) * 100) + '%';
}

function fmtSignedMoney(value) {
  const n = Number(value || 0);
  return (n >= 0 ? '+' : '-') + fmtMoney(Math.abs(n));
}

function fmtAgo(iso) {
  if (!iso) return '--';
  const then = new Date(iso);
  const ms = Date.now() - then.getTime();
  if (!Number.isFinite(ms) || ms < 0) return '--';
  const sec = Math.floor(ms / 1000);
  if (sec < 60) return sec + 's ago';
  const min = Math.floor(sec / 60);
  if (min < 60) return min + 'm ago';
  const hr = Math.floor(min / 60);
  if (hr < 24) return hr + 'h ago';
  return Math.floor(hr / 24) + 'd ago';
}

function clip(text, maxLen) {
  const raw = String(text || '').trim();
  if (!raw) return '';
  return raw.length > maxLen ? raw.slice(0, maxLen - 1) + '…' : raw;
}

async function fetchJson(url, options) {
  const response = await fetch(url, options || {});
  const raw = await response.text();
  let payload = null;
  if (raw) {
    try {
      payload = JSON.parse(raw);
    } catch (_err) {
      payload = null;
    }
  }
  if (!response.ok) {
    const detail = payload && (payload.detail || payload.error || payload.message);
    throw new Error(detail || ('HTTP ' + response.status + (response.statusText ? (' ' + response.statusText) : '')));
  }
  return payload || {};
}

function feed(kind, title, text) {
  _controlFeed.unshift({kind, title, text});
  _controlFeed = _controlFeed.slice(0, 12);
  renderControls();
}

function setTopbar(view) {
  const meta = VIEW_META[view] || VIEW_META.overview;
  document.getElementById('topbar-title').textContent = meta[0];
  document.getElementById('topbar-copy').textContent = meta[1];
}

function showView(view) {
  _currentView = view;
  Object.keys(VIEW_META).forEach((name) => {
    const pane = document.getElementById('view-' + name);
    if (pane) pane.classList.toggle('active', name === view);
  });
  document.querySelectorAll('[data-view]').forEach((el) => {
    el.classList.toggle('active', el.dataset.view === view);
  });
  setTopbar(view);
  location.hash = view;
}

function bindNav() {
  document.querySelectorAll('[data-view]').forEach((btn) => {
    btn.addEventListener('click', () => showView(btn.dataset.view));
  });
  const initial = location.hash.replace('#', '');
  if (VIEW_META[initial]) showView(initial);
}

function metric(label, value, note) {
  return '<div class="metric"><div class="small-label">' + esc(label) + '</div><div class="metric-value">' +
    esc(value) + '</div><div class="metric-note">' + esc(note || '') + '</div></div>';
}

function toneClass(value) {
  const n = Number(value || 0);
  if (n > 0) return 'up';
  if (n < 0) return 'down';
  return 'flat';
}

function marketCard(label, value, delta, note, tone) {
  return '<div class="ticker-card ' + esc(tone || 'flat') + '">' +
    '<div class="ticker-label">' + esc(label) + '</div>' +
    '<div class="ticker-value">' + esc(value) + '</div>' +
    '<div class="ticker-delta ' + esc(tone || 'flat') + '">' + esc(delta || '--') + '</div>' +
    '<div class="ticker-note">' + esc(note || '') + '</div>' +
  '</div>';
}

function actionCard(kind, title, text) {
  return '<div class="action-status-card ' + esc(kind || 'ok') + '">' +
    '<div class="action-badge">' + esc(kind === 'pending' ? 'working' : 'desk status') + '</div>' +
    '<strong>' + esc(title || 'Desk ready') + '</strong>' +
    '<span>' + esc(text || '') + '</span>' +
  '</div>';
}

function controlButton(label, action, options) {
  const opts = options || {};
  const classes = ['action-btn'];
  if (opts.primary) classes.push('primary');
  if (opts.warn) classes.push('warn');
  if (opts.live) classes.push('live');
  return '<button class="' + classes.join(' ') + '" onclick="controlAction(\'' + action + '\')"' +
    (opts.disabled ? ' disabled' : '') + '>' + esc(label) + '</button>';
}

function proposalButton(label, action, options) {
  const opts = options || {};
  const classes = ['action-btn'];
  if (opts.primary) classes.push('primary');
  if (opts.warn) classes.push('warn');
  return '<button class="' + classes.join(' ') + '" onclick="proposalAction(\'' + action + '\')"' +
    (opts.disabled ? ' disabled' : '') + '>' + esc(label) + '</button>';
}

function humanTimeframeLabel(tf) {
  const raw = String(tf || '5Min');
  return raw
    .replace(/Min$/i, 'm')
    .replace(/Hour$/i, 'h')
    .replace(/Day$/i, 'd');
}

function renderCandleStrip(id, chart) {
  const el = document.getElementById(id);
  if (!el) return;
  const bars = Array.isArray((chart || {}).bars) ? chart.bars : [];
  if (!bars.length) {
    el.innerHTML = '<div class="chart-empty">Live candles are not available yet for the watched symbol.</div>';
    return;
  }

  const width = 920;
  const height = 220;
  const topPad = 12;
  const bottomPad = 14;
  const volumeHeight = 44;
  const plotBottom = height - volumeHeight - bottomPad;
  const highs = bars.map((bar) => Number(bar.high || 0));
  const lows = bars.map((bar) => Number(bar.low || 0));
  const closes = bars.map((bar) => Number(bar.close || 0));
  const volumes = bars.map((bar) => Number(bar.volume || 0));
  const hi = Math.max.apply(null, highs);
  const lo = Math.min.apply(null, lows);
  const priceSpan = Math.max(hi - lo, Math.max(hi * 0.003, 0.01));
  const volumeMax = Math.max.apply(null, volumes.concat([1]));
  const innerWidth = width - 24;
  const step = innerWidth / bars.length;
  const bodyWidth = Math.max(4, Math.min(14, step * 0.58));
  const priceY = (price) => topPad + ((hi - price) / priceSpan) * (plotBottom - topPad);
  const volumeY = (volume) => height - bottomPad - ((Number(volume || 0) / volumeMax) * (volumeHeight - 6));
  const lastClose = Number(closes[closes.length - 1] || 0);
  const lastY = priceY(lastClose);

  const grid = [];
  for (let idx = 0; idx < 4; idx += 1) {
    const y = topPad + ((plotBottom - topPad) / 3) * idx;
    grid.push('<line x1="0" y1="' + y.toFixed(2) + '" x2="' + width + '" y2="' + y.toFixed(2) + '"></line>');
  }

  const candles = bars.map((bar, idx) => {
    const open = Number(bar.open || 0);
    const close = Number(bar.close || 0);
    const high = Number(bar.high || 0);
    const low = Number(bar.low || 0);
    const x = 12 + step * idx + (step / 2);
    const yOpen = priceY(open);
    const yClose = priceY(close);
    const yHigh = priceY(high);
    const yLow = priceY(low);
    const tone = close > open ? 'up' : (close < open ? 'down' : 'flat');
    const bodyTop = Math.min(yOpen, yClose);
    const bodyHeight = Math.max(2, Math.abs(yClose - yOpen));
    return [
      '<line class="chart-wick ' + tone + '" x1="' + x.toFixed(2) + '" y1="' + yHigh.toFixed(2) + '" x2="' + x.toFixed(2) + '" y2="' + yLow.toFixed(2) + '"></line>',
      '<rect class="chart-body ' + tone + '" x="' + (x - bodyWidth / 2).toFixed(2) + '" y="' + bodyTop.toFixed(2) + '" width="' + bodyWidth.toFixed(2) + '" height="' + bodyHeight.toFixed(2) + '" rx="2"></rect>',
      '<rect class="chart-volume ' + tone + '" x="' + (x - bodyWidth / 2).toFixed(2) + '" y="' + volumeY(bar.volume).toFixed(2) + '" width="' + bodyWidth.toFixed(2) + '" height="' + Math.max(3, height - bottomPad - volumeY(bar.volume)).toFixed(2) + '" rx="1"></rect>',
    ].join('');
  }).join('');

  const latestLabel = lastClose ? ('$' + lastClose.toFixed(2)) : '--';
  el.innerHTML =
    '<svg viewBox="0 0 ' + width + ' ' + height + '" preserveAspectRatio="none" aria-label="Live candle chart">' +
      '<g class="chart-grid">' + grid.join('') + '</g>' +
      '<line class="chart-price-line" x1="0" y1="' + lastY.toFixed(2) + '" x2="' + width + '" y2="' + lastY.toFixed(2) + '"></line>' +
      '<text class="chart-price-tag" x="' + (width - 64) + '" y="' + Math.max(14, lastY - 6).toFixed(2) + '">' + esc(latestLabel) + '</text>' +
      candles +
      '<text class="chart-axis-tag" x="12" y="' + (height - 2) + '">' + esc(humanTimeframeLabel(chart.timeframe)) + ' candles</text>' +
    '</svg>';
}

async function loadBelfortChart(symbol) {
  const target = String(symbol || 'SPY').toUpperCase();
  _belfortChart = await fetchJson('/monitor/chart?symbol=' + encodeURIComponent(target) + '&timeframe=' + encodeURIComponent(_belfortChartTimeframe) + '&limit=32');
}

function setBelfortChartTimeframe(timeframe) {
  _belfortChartTimeframe = timeframe || '5Min';
  const symbol = (((_state || {}).belfort || {}).belfort_focus_symbol || 'SPY');
  loadBelfortChart(symbol)
    .then(() => renderBelfort())
    .catch((err) => {
      feed('warn', 'Chart refresh failed', err.message || 'Could not load live candles for Belfort.');
    });
}

function setBelfortAction(kind, title, text, pendingKey) {
  _belfortAction = {kind, title, text};
  _belfortPendingAction = pendingKey || null;
  if (_state) renderBelfort();
}

function setBelfortLedgerFilter(kind) {
  _belfortLedgerFilter = kind || 'all';
  if (_state) renderBelfort();
}

function setBelfortWorkspace(kind) {
  _belfortWorkspace = kind || 'trade';
  if (_state) renderBelfort();
}

function setBelfortScannerFilter(kind) {
  _belfortScannerFilter = kind || 'leaders';
  if (_state) renderBelfort();
}

function setBelfortScannerSetupFilter(kind) {
  _belfortScannerSetupFilter = kind || 'all';
  if (_state) renderBelfort();
}

function setBelfortScannerMarketCapFilter(kind) {
  _belfortScannerMarketCapFilter = kind || 'all';
  if (_state) renderBelfort();
}

function setBelfortScannerFloatFilter(kind) {
  _belfortScannerFloatFilter = kind || 'all';
  if (_state) renderBelfort();
}

function compactRow(label, value) {
  return '<div class="compact-row"><div class="compact-row-label">' + esc(label) + '</div><div class="compact-row-value">' + esc(value || '--') + '</div></div>';
}

function humanSessionLabel(raw) {
  const value = String(raw || '').replace(/_/g, ' ').trim().toLowerCase();
  if (!value) return 'session unknown';
  if (value === 'pre market') return 'pre-market';
  if (value === 'regular') return 'regular session';
  if (value === 'closed') return 'market closed';
  return value;
}

function humanVerdictLabel(readiness) {
  const verdict = String(((readiness || {}).verdict) || '').replace(/_/g, ' ').trim();
  return verdict || 'not ready';
}

function humanReadinessSummary(readiness, fallback) {
  return String(((readiness || {}).summary) || fallback || 'Readiness is still being evaluated.').trim();
}

function simplifyTradeabilityReason(text) {
  const lower = String(text || '').toLowerCase();
  if (!lower) return 'Tradeability is still being evaluated.';
  if (lower.includes('watch only')) return 'Watch only for now.';
  if (lower.includes('phase 1')) return String(text || '').trim();
  if (lower.includes('expanded liquid-volatility universe')) return 'Eligible for paper trading in Belfort’s expanded volatile-stock phase.';
  if (lower.includes('eligible for paper trading')) return 'Eligible for paper trading right now.';
  if (lower.includes('market cap is still too small')) return 'Watch only for now. Market cap is still too small for Belfort’s paper lane.';
  if (lower.includes('float is still too tight')) return 'Watch only for now. Float is still too tight for Belfort’s paper lane.';
  if (lower.includes('average volume is still too thin')) return 'Watch only for now. Average volume is still too thin for Belfort’s paper lane.';
  if (lower.includes('relative volume is still too soft')) return 'Watch only for now. Relative volume is still too soft for Belfort’s paper lane.';
  if (lower.includes('float turnover is still too low')) return 'Watch only for now. Float turnover is still too low for Belfort’s paper lane.';
  if (lower.includes('price action is too unstable')) return 'Blocked for now. Price action is too unstable for a fresh entry.';
  if (lower.includes('spread')) return 'Watch the spread. The current book is not clean enough yet.';
  return String(text || '').trim();
}

function candidateStructureNote(candidate) {
  const parts = [];
  if (candidate.market_cap_bucket) parts.push(String(candidate.market_cap_bucket));
  if (candidate.float_bucket) parts.push(String(candidate.float_bucket));
  if (candidate.volatility_profile) parts.push(String(candidate.volatility_profile));
  if (candidate.relative_volume != null) parts.push(String(Number(candidate.relative_volume).toFixed(1)) + 'x rel vol');
  if (candidate.gap_pct != null) parts.push((Number(candidate.gap_pct) >= 0 ? '+' : '') + String((Number(candidate.gap_pct) * 100).toFixed(1)) + '% gap');
  if (candidate.float_turnover_pct != null) parts.push(String((Number(candidate.float_turnover_pct) * 100).toFixed(2)) + '% float turnover');
  return parts.filter(Boolean).join(' · ');
}

function shortTradeabilityLabel(candidate) {
  const label = String(candidate.tradeability_label || (candidate.paper_eligible ? 'eligible' : 'watch_only')).toLowerCase();
  if (label === 'eligible') return 'Eligible for paper trading right now.';
  if (label === 'blocked') return 'Blocked for fresh paper entries right now.';
  return 'Watch only for now.';
}

function plainScannerReason(text, fallbackSymbol) {
  const raw = String(text || '').trim();
  if (!raw) return (fallbackSymbol || 'This symbol') + ' is still warming up in Belfort’s board.';
  const lower = raw.toLowerCase();
  if (lower.includes('building price history')) return (fallbackSymbol || 'This symbol') + ' is being watched while Belfort builds enough recent price history to trust a setup.';
  if (lower.includes('leads the board')) return raw;
  return raw.replace(/\s*\|\s*/g, '. ');
}

function plainSelectionReason(text, policy, symbol) {
  const raw = String(text || '').trim();
  if (!raw) return 'Belfort is still deciding which setup lens to trust most.';
  const lower = raw.toLowerCase();
  if (lower.includes('warming up')) {
    return 'Belfort is still warming up the ' + String(policy || 'current') + ' setup lens on ' + String(symbol || 'the current symbol') + '.';
  }
  if (lower.includes('building price history')) {
    return 'Belfort is still collecting enough recent price history before it trusts a setup.';
  }
  return raw.replace(/\s*\|\s*/g, '. ');
}

function plainSimReason(text, ticks, fills) {
  const raw = String(text || '').trim();
  if (!raw) return 'Practice sim is active. Belfort is reading the tape and waiting for a clean setup.';
  const lower = raw.toLowerCase();
  if (lower.includes('warming_up_regime') || lower.includes('er warning') || lower.includes('min_signal_gap')) {
    return 'Practice sim is reading the tape but has not seen a clean enough setup yet. ' + String(ticks || 0) + ' tick(s) processed and ' + String(fills || 0) + ' fill(s) logged.';
  }
  if (lower.includes('session is closed')) {
    return 'Practice sim is running while the live paper lane is closed, so Belfort is only observing price action right now.';
  }
  return raw.replace(/\s*\|\s*/g, '. ');
}

function plainPaperSummary(exec, sessionLabel) {
  if (!exec) return 'No paper order has been submitted yet.';
  const status = String(exec.execution_status || '').toLowerCase();
  const symbol = String(exec.symbol || '').toUpperCase();
  const side = String(exec.action || exec.side || 'trade').toUpperCase();
  if (status === 'submitted') return side + ' ' + symbol + ' submitted to the paper broker.';
  if (status === 'filled') return side + ' ' + symbol + ' filled in the paper broker.';
  if (status === 'gated' || status === 'blocked') {
    const gate = String(exec.gate_block_reason || '').trim();
    if (!gate) return 'Paper order was blocked before it reached the broker.';
    return gate;
  }
  return String(exec.exec_summary || 'Paper lane updated.').replace(/\s*\|\s*/g, '. ');
}

function plainSignalBody(sig, paperEligibleFocus) {
  if (!sig) return 'No fresh signal yet.';
  const action = String(sig.signal_action || 'hold').toUpperCase();
  const symbol = String(sig.symbol || paperEligibleFocus || 'the focus symbol').toUpperCase();
  const setup = String(sig.setup_tag || '').trim();
  const blocked = sig.risk_can_proceed === false;
  const blockReason = String(sig.risk_block_reason || '').trim();
  const setupLine = setup && setup !== 'monitor only'
    ? ('Setup: ' + setup + '. ')
    : 'Belfort is still in monitor-only mode on this symbol. ';
  if (blocked) {
    if (blockReason.toLowerCase().includes('paper-tradeable session is closed')) {
      return setupLine + 'Belfort found a possible ' + action.toLowerCase() + ' in ' + symbol + ', but no paper-tradeable session is open yet.';
    }
    return setupLine + 'Belfort found a possible ' + action.toLowerCase() + ' in ' + symbol + ', but risk blocked the trade: ' + blockReason;
  }
  return setupLine + 'Belfort sees a ' + action.toLowerCase() + ' in ' + symbol + ' and risk currently allows the setup.';
}

function plainRiskReason(sig) {
  if (!sig) return 'No fresh signal yet.';
  if (sig.risk_can_proceed === false) {
    const blockReason = String(sig.risk_block_reason || '').toLowerCase();
    if (blockReason.includes('paper-tradeable session is closed')) return 'Blocked until the next paper-tradeable session opens.';
    if (blockReason) return 'Blocked by risk: ' + sig.risk_block_reason;
    return 'Blocked by risk.';
  }
  return 'Risk is clear for this setup.';
}

function pacingStateLabel(state) {
  const raw = String(state || '').toLowerCase();
  if (!raw || raw === 'open') return 'Entry pacing is open.';
  if (raw === 'daily_capacity_used') return 'Daily order capacity is used up.';
  if (raw === 'hourly_capacity_used') return 'Hourly trade pacing is throttling new entries.';
  if (raw === 'global_cooldown') return 'Desk-wide entry cooldown is active.';
  if (raw === 'symbol_cooldown') return 'This symbol is in cooldown.';
  if (raw === 'turnover_budget_used') return 'Turnover budget is exhausted for today.';
  if (raw === 'symbol_concentration') return 'This name is already too large in the book.';
  if (raw === 'position_limit') return 'The desk already has enough active names.';
  if (raw === 'exposure_full') return 'The book is fully deployed.';
  if (raw === 'cost_dominant') return 'Trading costs outweigh the expected edge.';
  if (raw === 'net_edge_too_thin') return 'Expected profit after fees is still too thin.';
  return raw.replace(/_/g, ' ');
}

function humanizeBlotterItem(item) {
  const title = String(item.title || 'Desk update');
  const text = String(item.text || '').replace(/\s+/g, ' ').trim();
  if (item.source === 'signal') {
    const clean = text
      .replace(/^PAPER decision:\s*/i, '')
      .replace(/^SHADOW decision:\s*/i, '')
      .replace(/Policy:\s*[^.]+\.\s*/i, '')
      .replace(/Rationale:\s*/i, '')
      .replace(/Risk:\s*/i, 'Risk: ')
      .replace(/\bmean_reversion\b/gi, 'mean reversion')
      .replace(/\bma_crossover\b/gi, 'trend')
      .replace(/\branging\b/gi, 'ranging tape')
      .replace(/\btrending\b/gi, 'trending tape')
      .replace(/Max daily order count reached:\s*\d+\/\d+/gi, 'Belfort has already used the day’s order budget')
      .replace(/\s+/g, ' ');
    return {
      title,
      text: clean || 'Signal evaluated.',
    };
  }
  if (item.source === 'paper') {
    return {
      title,
      text: text || 'Paper lane updated.',
    };
  }
  if (item.source === 'sim') {
    return {
      title,
      text: text || 'Practice sim updated.',
    };
  }
  return {title, text: text || 'Desk update.'};
}

function humanizeOrderEvent(event) {
  const type = String(event.event_type || '').toLowerCase();
  const symbol = String(event.symbol || '--').toUpperCase();
  const qty = Number(event.qty || 0);
  const price = Number(event.limit_price || event.broker_fill_price || 0);
  const setup = String(event.setup_tag || '').replace(/_/g, ' ').trim();
  const priceText = price > 0 ? (' @ ' + fmtMoney(price)) : '';
  const qtyText = qty > 0 ? (qty + ' ') : '';
  const setupText = setup ? (' via ' + setup) : '';
  if (type === 'placed') return qtyText + symbol + priceText + setupText + ' submitted to the paper broker.';
  if (type === 'ack') return qtyText + symbol + setupText + ' accepted by the broker and still working.';
  if (type === 'partial_fill') return qtyText + symbol + setupText + ' partially filled and is still working.';
  if (type === 'fill') return qtyText + symbol + priceText + setupText + ' fully filled.';
  if (type === 'reject') return qtyText + symbol + setupText + ' was rejected by the broker.';
  if (type === 'cancel') return qtyText + symbol + setupText + ' was cancelled.';
  if (type === 'expired') return qtyText + symbol + setupText + ' expired before filling.';
  return qtyText + symbol + setupText + ' has a recent order update.';
}

function orderMonitorLine(row) {
  const side = String(row.side || '').toUpperCase();
  const qty = Number(row.qty || 0);
  const qtyText = qty > 0 ? (qty + ' ') : '';
  const symbol = String(row.symbol || '--').toUpperCase();
  const status = String(row.status_label || row.event_type || 'working');
  const age = String(row.age_label || 'unknown');
  const updated = String(row.updated_label || 'unknown');
  const stale = row.is_stale ? (' Stale for this session after ' + String(row.stale_threshold_label || 'the session limit') + '.') : '';
  return qtyText + symbol + ' ' + side + ' is ' + status + '. Working for ' + age + ', last broker update ' + updated + ' ago.' + stale;
}

function watchlistRow(candidate, focusSymbol, mode) {
  const line = candidateTapeLine(candidate, focusSymbol);
  const symbol = String(candidate.symbol || '--').toUpperCase();
  const structure = candidateStructureNote(candidate);
  const classes = ['watchlist-row'];
  if (symbol === focusSymbol) classes.push('focus');
  if ((line.tone || '') === 'warn') classes.push('warn');
  const badgeClass = esc(line.badgeClass || 'watch_only');
  const badgeLabel = esc(line.badgeLabel || 'Watch only');
  const compact = mode === 'trade';
  const setupBias = String(candidate.strategy_fit || 'monitor only').replace(/_/g, ' ');
  const catalyst = clip(candidate.catalyst_summary || 'No fresh company catalyst.', compact ? 74 : 104);
  const flowLine = [
    candidate.relative_volume != null ? (Number(candidate.relative_volume).toFixed(1) + 'x rel vol') : '',
    candidate.gap_pct != null ? ((Number(candidate.gap_pct) >= 0 ? '+' : '') + (Number(candidate.gap_pct) * 100).toFixed(1) + '% gap') : '',
    candidate.float_turnover_pct != null ? ((Number(candidate.float_turnover_pct) * 100).toFixed(2) + '% float turnover') : '',
  ].filter(Boolean).join(' · ');
  const compactPrimary = clip([
    shortTradeabilityLabel(candidate),
    setupBias !== 'monitor only' ? ('Setup bias: ' + setupBias + '.') : 'General watch.',
    flowLine,
  ].filter(Boolean).join(' '), 128);
  const compactSecondary = clip([
    candidate.relative_strength_label || '',
    catalyst,
  ].filter(Boolean).join(' '), 118);
  return (
    '<div class="' + classes.join(' ') + '">' +
      '<div class="watchlist-head"><div class="watchlist-symbol">' + esc(symbol) + '</div><div style="display:flex;gap:8px;align-items:center"><div class="watch-badge ' + badgeClass + '">' + badgeLabel + '</div><div class="watchlist-score">score ' + esc(String(candidate.score || 0)) + '</div></div></div>' +
      (compact
        ? (
          '<div class="watchlist-note">' + esc(compactPrimary) + '</div>' +
          '<div class="watchlist-note secondary">' + esc(compactSecondary) + '</div>'
        )
        : (
          (structure ? '<div class="watchlist-note"><strong>' + esc(structure) + '</strong></div>' : '') +
          '<div class="watchlist-note">' + esc(line.text) + '</div>'
        )
      ) +
    '</div>'
  );
}

function scannerSetupBucket(candidate) {
  const fit = String((candidate || {}).strategy_fit || 'monitor only').toLowerCase();
  if (fit.includes('momentum') || fit.includes('trend') || fit.includes('continuation')) return 'momentum';
  if (fit.includes('news')) return 'news';
  if (fit.includes('mean reversion') || fit.includes('fade')) return 'mean-reversion';
  return 'neutral';
}

function openingDriveCard(candidate, focusSymbol) {
  const symbol = String(candidate.symbol || '--').toUpperCase();
  const classes = ['leader-card'];
  if (symbol === focusSymbol) classes.push('focus');
  const score = Number(candidate.opportunity_score || candidate.score || 0);
  const relVol = candidate.relative_volume != null ? (Number(candidate.relative_volume).toFixed(1) + 'x rel vol') : '';
  const gap = candidate.gap_pct != null ? ((Number(candidate.gap_pct) >= 0 ? '+' : '') + (Number(candidate.gap_pct) * 100).toFixed(1) + '% gap') : '';
  const flow = candidate.float_turnover_pct != null ? ((Number(candidate.float_turnover_pct) * 100).toFixed(2) + '% float turnover') : '';
  const body = [
    shortTradeabilityLabel(candidate),
    candidate.strategy_fit && candidate.strategy_fit !== 'monitor only' ? ('Setup bias: ' + candidate.strategy_fit + '.') : 'General watch.',
    [relVol, gap, flow].filter(Boolean).join(' · '),
  ].filter(Boolean).join(' ');
  return (
    '<div class="' + classes.join(' ') + '">' +
      '<div class="leader-card-head"><div class="leader-card-title">' + esc(symbol) + '</div><div class="leader-card-score">score ' + esc(score.toFixed ? score.toFixed(2) : String(score)) + '</div></div>' +
      '<div class="leader-card-copy">' + esc(clip(body, 132)) + '</div>' +
    '</div>'
  );
}

function scannerMatchesFilter(candidate) {
  const bucket = String(candidate.price_bucket || '').toLowerCase();
  const symbol = String(candidate.symbol || '').toUpperCase();
  const marketCapBucket = String(candidate.market_cap_bucket || '').toLowerCase();
  const floatBucket = String(candidate.float_bucket || '').toLowerCase();
  const setupBucket = scannerSetupBucket(candidate);
  const baseMatch = (
    _belfortScannerFilter === 'leaders' ? true :
    _belfortScannerFilter === 'benchmarks' ? ['SPY', 'QQQ', 'IWM'].includes(symbol) :
    _belfortScannerFilter === 'lower-price' ? bucket.includes('lower-price') :
    _belfortScannerFilter === 'news-led' ? Number(candidate.news_count || 0) > 0 :
    true
  );
  const capMatch = (
    _belfortScannerMarketCapFilter === 'all' ? true :
    _belfortScannerMarketCapFilter === 'mega' ? marketCapBucket.includes('mega') :
    _belfortScannerMarketCapFilter === 'large' ? marketCapBucket.includes('large') :
    _belfortScannerMarketCapFilter === 'mid' ? marketCapBucket.includes('mid') :
    _belfortScannerMarketCapFilter === 'small' ? marketCapBucket.includes('small') :
    true
  );
  const floatMatch = (
    _belfortScannerFloatFilter === 'all' ? true :
    _belfortScannerFloatFilter === 'high' ? floatBucket.includes('high') :
    _belfortScannerFloatFilter === 'medium' ? floatBucket.includes('medium') :
    _belfortScannerFloatFilter === 'low' ? floatBucket.includes('low') :
    true
  );
  const setupMatch = (
    _belfortScannerSetupFilter === 'all' ? true :
    _belfortScannerSetupFilter === setupBucket
  );
  return baseMatch && capMatch && floatMatch && setupMatch;
}

function plainBelfortSummary(b, operatorState, latestSimRecord, simBlockedReason) {
  const session = humanSessionLabel(b.belfort_session_type || 'unknown');
  const paperSessionOpen = ['regular session', 'pre-market', 'after-hours'].includes(session);
  if (operatorState && operatorState.current_action) return operatorState.current_action;
  if (b.sim_active && latestSimRecord && latestSimRecord.action === 'hold') {
    return 'Belfort is reading live price action in the sim lane and skipping trades until the setup and quote quality line up. ' + plainSimReason(simBlockedReason, b.sim_ticks || 0, b.sim_fills || 0);
  }
  if (b.sim_active && latestSimRecord && latestSimRecord.action !== 'hold') {
    return 'Belfort is managing a simulated ' + String(latestSimRecord.action || 'trade').toUpperCase() + ' in ' + (latestSimRecord.symbol || 'SPY') + '.';
  }
  if (b.trading_active && !paperSessionOpen) {
    return 'The paper lane is armed, but it will not submit orders until the next paper-tradeable session opens.';
  }
  if (b.trading_active) {
    return 'The paper lane is running and Belfort can send paper orders when a valid setup clears risk.';
  }
  return 'Belfort is waiting for the next market condition or operator action.';
}

function readinessItemHtml(item) {
  const passed = !!item.pass;
  return (
    '<div class="summary-item check-item ' + (passed ? 'pass' : 'fail') + '">' +
      '<div class="check-badge">' + esc(passed ? 'READY' : 'BLOCKED') + '</div>' +
      '<div><strong>' + esc(item.label || 'Gate') + '</strong><span>' + esc(item.note || '') + '</span></div>' +
    '</div>'
  );
}

function candidateTapeLine(candidate, focusSymbol) {
  const symbol = String(candidate.symbol || '--');
  const mid = candidate.mid != null ? fmtMoney(candidate.mid) : 'no quote';
  const catalyst = clip(candidate.catalyst_summary || 'No fresh company catalyst.', 78);
  const relative = candidate.relative_strength_label || 'Relative strength is still unclear.';
  const tradeability = simplifyTradeabilityReason(candidate.tradeability_reason || candidate.tradeability || '');
  const setup = candidate.strategy_fit || 'monitor only';
  const relVol = candidate.relative_volume != null ? (Number(candidate.relative_volume).toFixed(1) + 'x rel vol') : '';
  const gap = candidate.gap_pct != null ? (((Number(candidate.gap_pct) >= 0 ? '+' : '') + (Number(candidate.gap_pct) * 100).toFixed(1) + '% gap')) : '';
  const focusNote = symbol === focusSymbol ? 'Focus now.' : 'Watchlist.';
  const label = String(candidate.tradeability_label || (candidate.paper_eligible ? 'eligible' : 'watch_only')).toLowerCase();
  const setupText = setup === 'monitor only' ? 'General watch.' : ('Setup bias: ' + setup + '.');
  return {
    title: symbol + ' • ' + setup,
    text: [mid + '.', setupText, tradeability + '.', relative + '.', [relVol, gap].filter(Boolean).join(' · '), catalyst, focusNote].filter(Boolean).join(' '),
    tone: symbol === focusSymbol ? (candidate.paper_eligible ? 'ok' : 'warn') : (label === 'blocked' ? 'warn' : ((candidate.paper_eligible || (candidate.score || 0) >= 4) ? 'ok' : 'flat')),
    badgeClass: label,
    badgeLabel: label === 'eligible' ? 'Eligible' : (label === 'blocked' ? 'Blocked' : 'Watch only'),
  };
}

function catalystLine(item) {
  const headline = clip(item.headline || 'No headline', 110);
  const symbols = Array.isArray(item.symbols) && item.symbols.length ? item.symbols.join(', ') : 'market wide';
  const tone = Number(item.sentiment_bias || 0) < 0 ? 'warn' : 'ok';
  return {
    title: symbols,
    text: headline + (item.source ? ('. Source: ' + item.source) : '') + (item.updated_at ? ('. ' + fmtAgo(item.updated_at)) : ''),
    tone,
  };
}

function markdownLite(markdown) {
  const lines = String(markdown || '').replace(/\r/g, '').split('\n');
  const out = [];
  let inList = false;
  let inCode = false;
  lines.forEach((raw) => {
    const line = raw.trimEnd();
    if (line.startsWith('```')) {
      if (!inCode) {
        if (inList) { out.push('</ul>'); inList = false; }
        out.push('<pre><code>');
      } else {
        out.push('</code></pre>');
      }
      inCode = !inCode;
      return;
    }
    if (inCode) {
      out.push(esc(raw) + '\n');
      return;
    }
    if (!line.trim()) {
      if (inList) { out.push('</ul>'); inList = false; }
      return;
    }
    if (line.startsWith('### ')) {
      if (inList) { out.push('</ul>'); inList = false; }
      out.push('<h3>' + esc(line.slice(4)) + '</h3>');
      return;
    }
    if (line.startsWith('## ')) {
      if (inList) { out.push('</ul>'); inList = false; }
      out.push('<h2>' + esc(line.slice(3)) + '</h2>');
      return;
    }
    if (line.startsWith('# ')) {
      if (inList) { out.push('</ul>'); inList = false; }
      out.push('<h1>' + esc(line.slice(2)) + '</h1>');
      return;
    }
    if (line.startsWith('- ')) {
      if (!inList) {
        out.push('<ul>');
        inList = true;
      }
      out.push('<li>' + esc(line.slice(2)) + '</li>');
      return;
    }
    if (inList) { out.push('</ul>'); inList = false; }
    out.push('<p>' + esc(line) + '</p>');
  });
  if (inList) out.push('</ul>');
  if (inCode) out.push('</code></pre>');
  return out.join('');
}

async function loadGuideDoc(file) {
  const target = file || _docs.current || 'BELFORT_HOW_IT_WORKS.md';
  if (_docs.cache[target]) {
    _docs.current = target;
    return _docs.cache[target];
  }
  const payload = await fetchJson('/neighborhood/docs?file=' + encodeURIComponent(target));
  _docs.cache[target] = payload;
  _docs.current = target;
  return payload;
}

function renderOverview() {
  if (!_state) return;
  const b = _state.belfort || {};
  const f = _state.frank_lloyd || {};
  const c = _state.custodian || {};
  const s = _state.sentinel || {};
  const w = _state.warden || {};
  const pnl = Number(b.realized_pnl || 0) + Number(b.unrealized_pnl || 0);
  const paperEquity = Number(b.paper_equity || ((b.cash || 0) + (b.realized_pnl || 0) + (b.unrealized_pnl || 0)));
  const readiness = b.belfort_paper_open_readiness || b.belfort_operator_state || {};
  const heroTitle = document.getElementById('overview-hero-title');
  const heroCopy = document.getElementById('overview-hero-copy');
  const heroNumber = document.getElementById('overview-hero-number');
  const heroSub = document.getElementById('overview-hero-subnumber');
  heroTitle.textContent = b.trading_active ? 'Paper lane is awake.' : 'The house is steady and waiting.';
  heroCopy.textContent = [
    'Belfort mode: ' + (b.belfort_mode || 'unknown'),
    'Readiness: ' + humanVerdictLabel(readiness),
    f.active_job ? ('Frank active: ' + (f.active_job.title || f.active_job.build_id || 'build in progress')) : 'Frank Lloyd is available',
  ].join('  ');
  heroNumber.textContent = fmtMoney(paperEquity);
  heroSub.textContent = 'P&L ' + fmtMoney(pnl) + ' | ' + (b.trade_count || 0) + ' trades';

  const metrics = document.getElementById('overview-metrics');
  metrics.innerHTML = [
    metric('Belfort mode', (b.belfort_mode || '--').toUpperCase(), b.belfort_freshness_label || ''),
    metric('Paper lane', b.trading_active ? 'RUNNING' : 'STOPPED', b.belfort_paper_available === false ? (b.belfort_paper_unavailable_reason || '') : 'Regular session aware'),
    metric('Practice sim', b.sim_active ? 'RUNNING' : 'STOPPED', (b.sim_fills || 0) + ' fills'),
    metric('Frank Lloyd', f.active_job ? (f.active_job.status || '--').replace(/_/g, ' ') : 'IDLE', f.active_job ? (f.active_job.title || f.active_job.build_id || '') : ((f.pending_count || 0) + ' queued')),
  ].join('');

  const attention = [];
  if (_proposal && _proposal.proposal && !_proposal.dismissed) {
    const prop = _proposal.proposal;
    if (prop.current_value === prop.proposed_value) {
      attention.push({title: 'Belfort recommendation', text: 'Current parameter already matches the recommended target.'});
    } else {
      attention.push({title: 'Suggested adjustment', text: prop.parameter + ' from ' + prop.current_value + ' to ' + prop.proposed_value});
    }
  }
  if (f.active_job) attention.push({title: 'Frank Lloyd', text: (f.active_job.next_action || f.active_job.status || '').replace(/_/g, ' ')});
  if (c.overall === 'degraded') attention.push({title: 'Custodian', text: c.summary || 'System health needs review.'});
  if ((s.verdict || '') === 'review' || (s.verdict || '') === 'not_ready') attention.push({title: 'Sentinel', text: 'Patch safety says ' + (s.verdict || '').replace(/_/g, ' ')});
  if (!attention.length) attention.push({title: 'No urgent drift', text: 'The house is readable. Nothing is forcing a decision right now.'});
  document.getElementById('overview-attention').innerHTML = attention.map((item) =>
    '<div class="summary-item"><strong>' + esc(item.title) + '</strong><span>' + esc(item.text) + '</span></div>'
  ).join('');

  const activity = [];
  if (b.belfort_latest_signal) activity.push({kind: 'ok', title: 'Latest Belfort signal', text: (b.belfort_latest_signal.signal_action || 'hold').toUpperCase() + ' via ' + (b.belfort_latest_signal.active_policy || b.belfort_latest_signal.strategy_name || 'policy')});
  if (b.belfort_latest_paper_exec) activity.push({kind: b.belfort_latest_paper_exec.execution_status === 'submitted' ? 'ok' : 'warn', title: 'Paper execution', text: plainPaperSummary(b.belfort_latest_paper_exec, humanSessionLabel(b.belfort_session_type))});
  if (b.belfort_latest_sim_trade) activity.push({kind: 'ok', title: 'Latest sim trade', text: (b.belfort_latest_sim_trade.action || '').toUpperCase() + ' ' + (b.belfort_latest_sim_trade.symbol || '') + ' @ ' + fmtMoney(b.belfort_latest_sim_trade.fill_price || 0)});
  if (f.active_job) activity.push({kind: 'ok', title: 'Frank Lloyd', text: (f.active_job.title || f.active_job.build_id || '') + ' [' + (f.active_job.status || '') + ']'});
  if (!activity.length) activity.push({kind: 'ok', title: 'Quiet surface', text: 'No recent house activity yet.'});
  document.getElementById('overview-activity').innerHTML = activity.map((item) =>
    '<div class="feed-item ' + esc(item.kind || '') + '"><strong>' + esc(item.title) + '</strong><span>' + esc(item.text) + '</span></div>'
  ).join('');
}

function renderBelfort() {
  if (!_state) return;
  const b = _state.belfort || {};
  const scanner = b.belfort_scanner || {};
  const focusSymbol = String(b.belfort_focus_symbol || scanner.focus_symbol || 'SPY').toUpperCase();
  const focusReason = plainScannerReason(b.belfort_focus_reason || scanner.focus_reason || '', focusSymbol);
  const scannerLeaders = Array.isArray(scanner.leaders) ? scanner.leaders : [];
  const relativeVolumeLeaders = Array.isArray(scanner.relative_volume_leaders) ? scanner.relative_volume_leaders : [];
  const gapLeaders = Array.isArray(scanner.gap_leaders) ? scanner.gap_leaders : [];
  const preopenLeaders = Array.isArray(scanner.preopen_leaders) ? scanner.preopen_leaders : [];
  const scannerBenchmarks = Array.isArray(scanner.benchmarks) ? scanner.benchmarks : [];
  const scannerLowerPrice = Array.isArray(scanner.lower_price_watch) ? scanner.lower_price_watch : [];
  const catalysts = Array.isArray(scanner.catalysts) ? scanner.catalysts : [];
  const scannerUniverse = [];
  [...scannerLeaders, ...scannerBenchmarks, ...scannerLowerPrice].forEach((candidate) => {
    if (!candidate || !candidate.symbol) return;
    if (!scannerUniverse.find((item) => String(item.symbol) === String(candidate.symbol))) {
      scannerUniverse.push(candidate);
    }
  });
  const cleanBooks = scannerLeaders.filter((item) => String(item.tradeability || '').includes('clean')).length;
  const relativeLeaders = scannerLeaders.filter((item) => {
    const label = String(item.relative_strength_label || '');
    return label.includes('leading') || label.includes('stronger');
  }).length;
  const laggingTape = scannerLeaders.filter((item) => {
    const label = String(item.relative_strength_label || '');
    return label.includes('lagging') || label.includes('weaker');
  }).length;
  const riskFlagged = scannerLeaders.filter((item) => Array.isArray(item.risk_flags) && item.risk_flags.length).length;
  const setupCounts = scannerLeaders.reduce((acc, item) => {
    const fit = String(item.strategy_fit || 'monitor only');
    if (fit.includes('momentum') || fit.includes('trend')) acc.momentum += 1;
    else if (fit.includes('mean reversion') || fit.includes('fade')) acc.meanReversion += 1;
    else if (fit.includes('news')) acc.news += 1;
    else acc.neutral += 1;
    return acc;
  }, {momentum: 0, meanReversion: 0, news: 0, neutral: 0});
  const simPerf = b.belfort_sim_performance || {};
  const simStats = b.belfort_sim_stats_today || {};
  const latestSimRecord = b.belfort_latest_sim_record || b.belfort_latest_sim_trade || null;
  const simTicks = Number(b.sim_ticks || simStats.ticks || 0);
  const simFills = Number(b.sim_fills || simStats.fills || 0);
  const signalStats = b.belfort_signal_stats_today || {};
  const paperStats = b.belfort_paper_exec_stats_today || {};
  const simBlockedReason = clip(
    (latestSimRecord && (latestSimRecord.rationale || latestSimRecord.selection_reason)) ||
    b.belfort_sim_main_reason ||
    '',
    110,
  );
  const learnStrip = b.belfort_learn_strip || {};
  const stratProfile = b.belfort_strategy_profile || {};
  const setupScorecard = b.belfort_setup_scorecard || {};
  const regimeMetrics = b.belfort_regime_metrics || {};
  const readiness = b.belfort_live_readiness || {};
  const operatorState = b.belfort_paper_open_readiness || b.belfort_operator_state || {};
  const paperPolicy = b.belfort_paper_policy || {};
  const brokerStatus = b.belfort_broker_status || {};
  const reconciliation = b.belfort_reconciliation || {};
  const latestPaperFill = b.belfort_latest_paper_fill || null;
  const latestPaperExec = b.belfort_latest_paper_exec || null;
  const activityFeed = Array.isArray(b.belfort_activity_feed) ? b.belfort_activity_feed.slice() : [];
  const orderMonitor = b.belfort_order_monitor || {};
  const activePolicy = String((_strategy && _strategy.active_policy) || 'warming_up').replace(/_/g, ' ');
  const marketRegime = String((_strategy && _strategy.market_regime) || stratProfile.current_regime || 'unknown').replace(/_/g, ' ');
  const selectionReason = plainSelectionReason((_strategy && _strategy.selection_reason) || stratProfile.fitness_regular || '', activePolicy, focusSymbol);
  const pnl = Number(b.realized_pnl || 0) + Number(b.unrealized_pnl || 0);
  const paperEquity = Number(b.paper_equity || ((b.cash || 0) + (b.realized_pnl || 0) + (b.unrealized_pnl || 0)));
  const buyingPower = Number(b.buying_power || b.broker_buying_power || 0);
  const paperTruthSource = String(b.paper_truth_source || 'local_fallback');
  const brokerPositionWarning = String(b.broker_position_warning || '').trim();
  const simTrainingLabel = simPerf.win_rate != null ? fmtPct(simPerf.win_rate) : (b.sim_active ? 'training' : '--');
  const simTrainingDelta = simPerf.win_rate != null ? fmtSignedMoney(simPerf.realized_pnl || 0) : (simTicks + ' ticks / ' + simFills + ' fills');
  const simTrainingNote = simPerf.win_rate != null
    ? ((simPerf.wins || 0) + 'W / ' + (simPerf.losses || 0) + 'L')
    : (plainSimReason(simBlockedReason, simTicks, simFills) || ((simStats.holds || 0) + ' hold ticks logged today'));
  const operatorSummary = operatorState.summary || readiness.note || 'Readiness is still being evaluated.';
  const currentAction = plainBelfortSummary(b, operatorState, latestSimRecord, simBlockedReason);
  const sessionLabel = humanSessionLabel(b.belfort_session_type || 'unknown');
  const openVerdict = humanVerdictLabel(operatorState);
  const paperReadyNow = operatorState.verdict === 'ready_for_operator_start' || operatorState.verdict === 'actively_trading';
  const activelyTrading = operatorState.verdict === 'actively_trading';
  const stagedForOpen = operatorState.verdict === 'staged_for_open';
  const paperEligibleFocus = String(operatorState.paper_eligible_focus_symbol || b.belfort_paper_focus_symbol || '').toUpperCase();
  const focusGapReason = operatorState.focus_gap_reason || '';
  const whyNotTrading = operatorState.why_not_trading || '';
  const remainingDailyCapacity = Number(operatorState.remaining_daily_capacity || 0);
  const remainingHourlyCapacity = Number(operatorState.remaining_hourly_capacity || 0);
  const remainingExposureCapacity = Number(operatorState.remaining_exposure_capacity || 0);
  const orderPacingState = pacingStateLabel(operatorState.order_pacing_state);
  const allTradeRows = scannerUniverse.length ? scannerUniverse : scannerLeaders;
  const focusCandidate = allTradeRows.find((candidate) => String(candidate.symbol || '').toUpperCase() === focusSymbol) || {};
  const radarBuckets = {
    momentum: scannerLeaders.filter((candidate) => scannerSetupBucket(candidate) === 'momentum'),
    news: scannerLeaders.filter((candidate) => scannerSetupBucket(candidate) === 'news'),
    'mean-reversion': scannerLeaders.filter((candidate) => scannerSetupBucket(candidate) === 'mean-reversion'),
    neutral: scannerLeaders.filter((candidate) => scannerSetupBucket(candidate) === 'neutral'),
  };
  const openingDriveLeaders = allTradeRows
    .filter((candidate) => candidate && candidate.paper_eligible)
    .sort((a, bItem) => {
      const scoreA = Number(a.opportunity_score || a.score || 0);
      const scoreB = Number(bItem.opportunity_score || bItem.score || 0);
      if (scoreB !== scoreA) return scoreB - scoreA;
      const relVolA = Number(a.relative_volume || 0);
      const relVolB = Number(bItem.relative_volume || 0);
      return relVolB - relVolA;
    })
    .slice(0, 4);
  const openPositionSymbols = Array.isArray(b.open_positions) ? b.open_positions : [];
  const shortlistMap = new Map();
  function addShortlistCandidate(candidate) {
    if (!candidate) return;
    const symbol = String(candidate.symbol || '').toUpperCase().trim();
    if (!symbol || shortlistMap.has(symbol)) return;
    shortlistMap.set(symbol, candidate);
  }
  function candidateForSymbol(symbol, fallbackReason) {
    const match = allTradeRows.find((candidate) => String(candidate.symbol || '').toUpperCase() === String(symbol || '').toUpperCase());
    if (match) return match;
    return {
      symbol: String(symbol || '').toUpperCase(),
      tradeability_label: 'eligible',
      tradeability_reason: fallbackReason || 'Already on the paper book and needs active management.',
      strategy_fit: 'manage open position',
      score: '--',
      catalyst_summary: 'Already on the paper book.',
      relative_strength_label: 'Manage the open paper position before adding new risk.',
    };
  }
  addShortlistCandidate(candidateForSymbol(focusSymbol, 'Current scanner focus.'));
  if (paperEligibleFocus && paperEligibleFocus !== focusSymbol) addShortlistCandidate(candidateForSymbol(paperEligibleFocus, 'Current paper-eligible focus.'));
  openPositionSymbols.forEach((symbol) => addShortlistCandidate(candidateForSymbol(symbol, 'Open paper position that still needs active management.')));
  scannerLeaders.filter((candidate) => candidate.paper_eligible).forEach(addShortlistCandidate);
  relativeVolumeLeaders.forEach(addShortlistCandidate);
  gapLeaders.forEach(addShortlistCandidate);
  const watchlistRows = Array.from(shortlistMap.values()).slice(0, 6);
  const scannerRows = (_belfortScannerFilter === 'leaders' ? scannerLeaders : allTradeRows.filter(scannerMatchesFilter)).slice(0, 14);
  document.getElementById('belfort-hero-title').textContent = 'Mr Belfort';
  document.getElementById('belfort-hero-copy').textContent =
    currentAction + ' | session ' + sessionLabel + (b.sim_active ? (' | sim active ' + fmtAgo(b.sim_started_at)) : '');

  document.getElementById('belfort-market-strip').innerHTML = [
    marketCard('Paper Equity', fmtMoney(paperEquity), fmtSignedMoney(pnl), (b.trade_count || 0) + ' paper trades', toneClass(pnl)),
    marketCard('Active Edge', 'Watching ' + focusSymbol, marketRegime, selectionReason, 'flat'),
    marketCard('Practice Sim', simTrainingLabel, simTrainingDelta, simTrainingNote, toneClass((simPerf.win_rate == null ? 0 : simPerf.win_rate - 0.5))),
    marketCard('Paper Window', openVerdict, (paperStats.filled || 0) + ' synced fills', operatorSummary, activelyTrading || paperReadyNow ? 'up' : (stagedForOpen ? 'flat' : 'down')),
  ].join('');

  const chart = _belfortChart || {};
  renderCandleStrip('belfort-chart', chart);
  const chartChange = Number(chart.change || 0);
  const chartBars = Number(chart.bar_count || 0);
  const chartLast = Number(chart.last_close || 0);
  document.getElementById('belfort-chart-meta').textContent =
    (chart.symbol || focusSymbol) + ' · ' + humanTimeframeLabel(chart.timeframe || _belfortChartTimeframe) +
    ' · ' + (chartLast ? (fmtMoney(chartLast) + ' ' + (chartChange >= 0 ? '+' : '') + chartChange.toFixed(2)) : 'waiting for live bars') +
    ' · ' + chartBars + ' candles';
  document.getElementById('belfort-chart-toolbar').innerHTML = ['5Min', '10Min', '15Min'].map((item) =>
    '<button class="chip ' + ((_belfortChartTimeframe === item) ? 'active' : '') + '" onclick="setBelfortChartTimeframe(\'' + item + '\')">' + esc(humanTimeframeLabel(item)) + '</button>'
  ).join('');

  document.querySelectorAll('#belfort-workspace-tabs .workspace-tab').forEach((el) => {
    el.classList.toggle('active', el.textContent.toLowerCase() === _belfortWorkspace);
  });
  ['trade', 'scanner', 'research', 'guide'].forEach((name) => {
    const pane = document.getElementById('belfort-pane-' + name);
    if (pane) pane.classList.toggle('active', name === _belfortWorkspace);
  });

  const focusInfoRows = [
    {
      title: 'Scanner focus',
      text: focusSymbol + ' — ' + focusReason,
    },
    {
      title: 'Paper focus',
      text: paperEligibleFocus ? (paperEligibleFocus + ' — ' + (operatorState.paper_eligible_focus_reason || 'Current paper-eligible name.')) : 'No paper-eligible focus symbol is ready yet.',
    },
    {
      title: 'Board scope',
      text: (scanner.universe_size || 0) + ' symbols ranked across benchmarks, liquid leaders, lower-price watch, and catalyst names.',
    },
    {
      title: 'Framework',
      text: ((scanner.selection_framework || []).join(', ')) || 'quote quality, tape momentum, and catalysts',
    },
  ];
  document.getElementById('belfort-scanner-overview').innerHTML = focusInfoRows.map((item) =>
    '<div class="scanner-summary-card"><strong>' + esc(item.title) + '</strong><span>' + esc(item.text) + '</span></div>'
  ).join('');

  document.getElementById('belfort-focus-symbol').textContent = focusSymbol;
  document.getElementById('belfort-focus-meta').textContent = [
    focusReason,
    focusCandidate.structure_label || '',
    focusCandidate.volatility_profile ? ('Volatility: ' + focusCandidate.volatility_profile + '.') : '',
    focusCandidate.relative_volume != null ? ('Relative volume: ' + Number(focusCandidate.relative_volume).toFixed(1) + 'x.') : '',
    focusCandidate.gap_pct != null ? ('Gap: ' + (Number(focusCandidate.gap_pct) >= 0 ? '+' : '') + (Number(focusCandidate.gap_pct) * 100).toFixed(1) + '%.') : '',
    focusGapReason,
  ].filter(Boolean).join(' ');
  document.getElementById('belfort-focus-badges').innerHTML = [
    '<div class="tight-chip">' + esc(String(b.belfort_mode || 'paper').replace(/_/g, ' ')) + ' mode</div>',
    '<div class="tight-chip">' + esc(sessionLabel) + '</div>',
    '<div class="tight-chip">' + esc(activePolicy) + '</div>',
    '<div class="tight-chip">' + esc(marketRegime) + '</div>',
    (paperEligibleFocus ? '<div class="tight-chip">' + esc('paper focus ' + paperEligibleFocus) + '</div>' : ''),
  ].join('');

  document.getElementById('belfort-opening-drive-strip').innerHTML = openingDriveLeaders.length
    ? openingDriveLeaders.map((candidate) => openingDriveCard(candidate, focusSymbol)).join('')
    : '<div class="leader-card"><div class="leader-card-head"><div class="leader-card-title">No clean leader yet</div><div class="leader-card-score">warming</div></div><div class="leader-card-copy">Belfort has not found a paper-eligible opening-drive name with clean enough tape yet.</div></div>';

  document.getElementById('belfort-watchlist').innerHTML = watchlistRows.length
    ? watchlistRows.map((candidate) => watchlistRow(candidate, focusSymbol, 'trade')).join('')
    : '<div class="watchlist-row warn"><div class="watchlist-symbol">Shortlist warming up</div><div class="watchlist-note">Belfort is still building a focused trade shortlist from the scanner board.</div></div>';

  document.getElementById('belfort-scanner-filter-toolbar').innerHTML = [
    ['leaders', 'Leaders'],
    ['benchmarks', 'Benchmarks'],
    ['lower-price', 'Lower-price'],
    ['news-led', 'News-led'],
  ].map((item) =>
    '<button class="chip ' + (_belfortScannerFilter === item[0] ? 'active' : '') + '" onclick="setBelfortScannerFilter(\'' + item[0] + '\')">' + esc(item[1]) + '</button>'
  ).join('');
  document.getElementById('belfort-scanner-setup-toolbar').innerHTML = [
    ['all', 'All setups'],
    ['momentum', 'Momentum'],
    ['news', 'News-led'],
    ['mean-reversion', 'Mean reversion'],
    ['neutral', 'Neutral'],
  ].map((item) =>
    '<button class="chip ' + (_belfortScannerSetupFilter === item[0] ? 'active' : '') + '" onclick="setBelfortScannerSetupFilter(\'' + item[0] + '\')">' + esc(item[1]) + '</button>'
  ).join('');
  document.getElementById('belfort-scanner-cap-filter-toolbar').innerHTML = [
    ['all', 'All caps'],
    ['mega', 'Mega'],
    ['large', 'Large'],
    ['mid', 'Mid'],
    ['small', 'Small'],
  ].map((item) =>
    '<button class="chip ' + (_belfortScannerMarketCapFilter === item[0] ? 'active' : '') + '" onclick="setBelfortScannerMarketCapFilter(\'' + item[0] + '\')">' + esc(item[1]) + '</button>'
  ).join('');
  document.getElementById('belfort-scanner-float-filter-toolbar').innerHTML = [
    ['all', 'All float'],
    ['high', 'High float'],
    ['medium', 'Medium float'],
    ['low', 'Low float'],
  ].map((item) =>
    '<button class="chip ' + (_belfortScannerFloatFilter === item[0] ? 'active' : '') + '" onclick="setBelfortScannerFloatFilter(\'' + item[0] + '\')">' + esc(item[1]) + '</button>'
  ).join('');

  document.getElementById('belfort-scanner').innerHTML = scannerRows.length
    ? scannerRows.map((candidate) => watchlistRow(candidate, focusSymbol)).join('')
    : '<div class="watchlist-row warn"><div class="watchlist-symbol">No names match this filter</div><div class="watchlist-note">Try another scanner filter or wait for the market board to refresh.</div></div>';
  document.getElementById('belfort-catalysts').innerHTML = catalysts.length
    ? catalysts.slice(0, 6).map((entry) => {
        const item = catalystLine(entry);
        return '<div class="feed-item ' + esc(item.tone) + '"><strong>' + esc(item.title) + '</strong><span>' + esc(item.text) + '</span></div>';
      }).join('')
    : '<div class="feed-item warn"><strong>No fresh catalysts</strong><span>Belfort is falling back to price action and quote quality because no fresh news headlines are available right now.</span></div>';
  const radarCards = [
    ['momentum', 'Momentum / trend setups', String(setupCounts.momentum) + ' leader(s) leaning momentum or continuation.', radarBuckets.momentum],
    ['news', 'News-led names', String(setupCounts.news) + ' leader(s) have fresh catalyst pressure.', radarBuckets.news],
    ['mean-reversion', 'Mean reversion / fade', String(setupCounts.meanReversion) + ' leader(s) look more like fade or reversion candidates.', radarBuckets['mean-reversion']],
    ['neutral', 'Neutral watch', String(setupCounts.neutral) + ' leader(s) are not giving a strong setup bias yet.', radarBuckets.neutral],
  ];
  document.getElementById('belfort-radar').innerHTML = radarCards.map((item) => {
    const [key, title, text, names] = item;
    const active = _belfortScannerSetupFilter === key;
    const symbols = (names || []).slice(0, 4).map((candidate) => String(candidate.symbol || '--').toUpperCase()).join(', ');
    return (
      '<div class="radar-card ' + (active ? 'active' : '') + '" onclick="setBelfortScannerSetupFilter(\'' + key + '\')">' +
        '<div class="leader-card-head"><strong>' + esc(title) + '</strong><div class="radar-count">' + esc(active ? 'showing now' : 'click to show') + '</div></div>' +
        '<span>' + esc(text) + '</span>' +
        '<div class="radar-symbols">' + esc(symbols || 'No names in this lane yet.') + '</div>' +
      '</div>'
    );
  }).join('');
  const detailBucket = _belfortScannerSetupFilter === 'all' ? null : radarBuckets[_belfortScannerSetupFilter];
  document.getElementById('belfort-radar-detail').innerHTML = detailBucket
    ? (
      detailBucket.length
        ? detailBucket.slice(0, 6).map((candidate) =>
            '<div class="summary-item"><strong>' + esc(String(candidate.symbol || '--').toUpperCase()) + '</strong><span>' + esc([
              shortTradeabilityLabel(candidate),
              candidate.relative_strength_label || '',
              candidate.catalyst_summary || '',
            ].filter(Boolean).join(' ')) + '</span></div>'
          ).join('')
        : '<div class="summary-item"><strong>No names in this lane</strong><span>Belfort does not have any current scanner leaders in this setup bucket.</span></div>'
    )
    : '<div class="summary-item"><strong>Choose a setup lane</strong><span>Click a radar card to narrow the scanner board to the names behind that count.</span></div>';
  document.getElementById('belfort-flow-leaders').innerHTML = [
    {
      title: 'Opening-drive leaders',
      text: 'Best current paper-eligible names for the session open.',
      names: preopenLeaders.slice(0, 4),
      metric: 'Opening score',
    },
    {
      title: 'Relative volume leaders',
      text: 'Names pulling the strongest live relative volume right now.',
      names: relativeVolumeLeaders.slice(0, 4),
      metric: 'Rel vol',
    },
    {
      title: 'Gap leaders',
      text: 'Names with the biggest live gap pressure on the board.',
      names: gapLeaders.slice(0, 4),
      metric: 'Gap',
    },
  ].map((item) => {
    const names = item.names || [];
    return (
      '<div class="leaderboard-card">' +
        '<strong>' + esc(item.title) + '</strong>' +
        '<span>' + esc(item.text) + '</span>' +
        '<div class="leader-symbols">' +
          (
            names.length
              ? names.map((candidate) => {
                  const symbol = String(candidate.symbol || '--').toUpperCase();
                  let value = '';
                  if (item.metric === 'Opening score') value = Number(candidate.opportunity_score || 0).toFixed(2);
                  else if (item.metric === 'Rel vol') value = Number(candidate.relative_volume || 0).toFixed(1) + 'x';
                  else if (item.metric === 'Gap') value = (Number(candidate.gap_pct || 0) >= 0 ? '+' : '') + (Number(candidate.gap_pct || 0) * 100).toFixed(1) + '%';
                  return '<div class="leader-symbol">' + esc(symbol + ' ' + value) + '</div>';
                }).join('')
              : '<div class="radar-empty">No names in this leaderboard yet.</div>'
          ) +
        '</div>' +
      '</div>'
    );
  }).join('') + '<div class="leaderboard-card"><strong>Desk read</strong><span>' + esc(preopenLeaders.length ? 'Belfort should favor names that combine clean books, opening-drive score, and fee-surviving setups.' : 'The board is still building; Belfort should stay selective until leadership is clearer.') + '</span></div>';
  document.getElementById('belfort-tradeability').innerHTML = [
    '<div class="summary-item"><strong>Clean books</strong><span>' + esc(String(cleanBooks) + ' leader(s) have the cleanest current spreads.') + '</span></div>',
    '<div class="summary-item"><strong>Relative strength leaders</strong><span>' + esc(String(relativeLeaders) + ' leader(s) are actually outperforming SPY instead of just drifting with it.') + '</span></div>',
    '<div class="summary-item"><strong>Lagging the tape</strong><span>' + esc(String(laggingTape) + ' leader(s) are weaker than SPY and should be treated more like fades or avoids.') + '</span></div>',
    '<div class="summary-item"><strong>Risk-flagged catalysts</strong><span>' + esc(String(riskFlagged) + ' leader(s) carry dilution, earnings-miss, or other headline risk flags.') + '</span></div>',
    '<div class="summary-item"><strong>Desk read</strong><span>' + esc(cleanBooks > 0 ? 'There are tradeable names on the board, but Belfort should favor the ones that are both clean and leading SPY.' : 'The board is mostly observational right now — Belfort should stay selective.') + '</span></div>',
    '<div class="summary-item"><strong>Structure read</strong><span>' + esc(candidateStructureNote(focusCandidate) || 'Company structure data is still loading for the focus symbol.') + '</span></div>',
    '<div class="summary-item"><strong>Flow read</strong><span>' + esc(
      focusCandidate.relative_volume != null || focusCandidate.gap_pct != null || focusCandidate.float_turnover_pct != null
        ? [
            focusCandidate.relative_volume != null ? ('Relative volume ' + Number(focusCandidate.relative_volume).toFixed(1) + 'x') : '',
            focusCandidate.gap_pct != null ? ('gap ' + (Number(focusCandidate.gap_pct) >= 0 ? '+' : '') + (Number(focusCandidate.gap_pct) * 100).toFixed(1) + '%') : '',
            focusCandidate.float_turnover_pct != null ? ('float turnover ' + (Number(focusCandidate.float_turnover_pct) * 100).toFixed(2) + '%') : '',
          ].filter(Boolean).join(' · ')
        : 'Intraday flow data is still loading for the focus symbol.'
    ) + '</span></div>',
  ].join('');

  const tradeWorkspaceState = {
    focusSymbol,
    signal: b.belfort_latest_signal || null,
    account: {
      paperEquity: paperEquity,
      cash: b.cash || 0,
      buyingPower: buyingPower,
      pnl,
      tradeCount: b.trade_count || 0,
      openPositions: b.open_positions || [],
      truthSource: paperTruthSource,
    },
    controls: {
      tradingActive: b.trading_active,
      simActive: b.sim_active,
    },
    readiness: {
      verdict: openVerdict,
      summary: operatorSummary,
    },
    latestOrderPosition: {
      latestPaperFill,
      latestPaperExec,
      latestSimRecord,
    },
  };
  const scannerWorkspaceState = {
    watchlistRows: scannerRows,
    catalysts,
    radar: setupCounts,
    tapeContext: {cleanBooks, relativeLeaders, laggingTape, riskFlagged},
  };
  const researchWorkspaceState = {
    learning: _learning,
    setupScorecard,
    proposal: _proposal,
    blotter: activityFeed,
    readiness: operatorState,
  };

  document.getElementById('belfort-trade-metrics').innerHTML = [
    metric('Readiness', openVerdict.toUpperCase(), operatorSummary),
    metric('Focus symbol', focusSymbol, clip(focusReason, 72)),
    metric('Order capacity', String(remainingDailyCapacity), remainingHourlyCapacity + ' entries left this hour'),
    metric('Buying power room', fmtMoney(remainingExposureCapacity), orderPacingState),
  ].join('');
  document.getElementById('belfort-live-leaders').innerHTML = [
    {
      title: 'Opening-drive names',
      text: preopenLeaders.length
        ? preopenLeaders.slice(0, 3).map((item) => String(item.symbol || '--') + ' (' + Number(item.opportunity_score || 0).toFixed(2) + ')').join(', ')
        : 'No pre-open leaders yet.'
    },
    {
      title: 'Volume leaders',
      text: relativeVolumeLeaders.length
        ? relativeVolumeLeaders.slice(0, 3).map((item) => String(item.symbol || '--') + ' (' + Number(item.relative_volume || 0).toFixed(1) + 'x)').join(', ')
        : 'No strong volume leaders yet.'
    },
    {
      title: 'Gap leaders',
      text: gapLeaders.length
        ? gapLeaders.slice(0, 3).map((item) => String(item.symbol || '--') + ' (' + (Number(item.gap_pct || 0) >= 0 ? '+' : '') + (Number(item.gap_pct || 0) * 100).toFixed(1) + '%)').join(', ')
        : 'No meaningful gap leaders yet.'
    },
    {
      title: 'Desk note',
      text: paperEligibleFocus
        ? ('Trade from ' + paperEligibleFocus + ' first. Use Scanner for the deeper board.')
        : 'Use Scanner to inspect the full board before adding fresh risk.'
    },
  ].map((item) =>
    '<div class="summary-item"><strong>' + esc(item.title) + '</strong><span>' + esc(item.text) + '</span></div>'
  ).join('');

  const liveDeskAction = _belfortPendingAction ? _belfortAction : {
    kind: activelyTrading || paperReadyNow ? 'ok' : (stagedForOpen || b.sim_active ? 'pending' : 'warn'),
    title: activelyTrading ? 'Paper lane active' : (paperReadyNow ? 'Ready for operator start' : (stagedForOpen ? 'Staged for the open' : (b.sim_active ? 'Practice sim training' : 'Operator attention needed'))),
    text: currentAction,
  };
  document.getElementById('belfort-action-status').innerHTML = actionCard(
    liveDeskAction.kind,
    liveDeskAction.title,
    liveDeskAction.text
  );

  const consoleBusy = !!_belfortPendingAction;
  document.getElementById('belfort-console-actions').innerHTML = [
    controlButton(b.trading_active ? 'Paper Running' : 'Start Paper', 'start-paper', {primary: !b.trading_active, live: b.trading_active, disabled: consoleBusy || b.trading_active}),
    controlButton('Stop & Close All', 'stop-paper', {warn: true, disabled: consoleBusy || !b.trading_active}),
    controlButton('Close All Positions', 'flatten-paper', {warn: true, disabled: consoleBusy || !(tradeWorkspaceState.account.openPositions || []).length}),
    controlButton(b.sim_active ? 'Sim Running' : 'Start Sim', 'start-sim', {primary: !b.sim_active, live: b.sim_active, disabled: consoleBusy || b.sim_active}),
    controlButton('Stop Sim', 'stop-sim', {disabled: consoleBusy || !b.sim_active}),
    controlButton('Advance Mode', 'advance-mode', {disabled: consoleBusy}),
    controlButton('Reset Paper', 'reset-paper', {warn: true, disabled: consoleBusy}),
  ].join('');

  const policyItems = [];
  if (_strategy) {
    policyItems.push({title: 'Active policy', text: activePolicy + ' in ' + marketRegime});
    policyItems.push({title: 'Selection reason', text: selectionReason});
    policyItems.push({title: 'Trend lens', text: plainSelectionReason(((_strategy.ma_crossover || {}).rationale || 'trend lens warming up'), 'trend', focusSymbol)});
    policyItems.push({title: 'Mean reversion lens', text: plainSelectionReason(((_strategy.mean_reversion || {}).rationale || 'mean-reversion lens warming up'), 'mean reversion', focusSymbol)});
    if (stratProfile.fitness_regular) policyItems.push({title: 'Regular session fitness', text: stratProfile.fitness_regular});
    if (stratProfile.fitness_sim) policyItems.push({title: 'Closed-session sim fitness', text: stratProfile.fitness_sim});
  } else {
    policyItems.push({title: 'Policy selector', text: 'Loading Belfort policy state...'});
  }
  document.getElementById('belfort-policy').innerHTML = policyItems.map((item) =>
    '<div class="summary-item"><strong>' + esc(item.title) + '</strong><span>' + esc(item.text) + '</span></div>'
  ).join('');

  const sig = b.belfort_latest_signal;
  const signalTone = sig ? String(sig.signal_action || 'hold').toLowerCase() : 'flat';
  const signalEl = document.getElementById('belfort-signal');
  if (sig) {
    const signalSymbol = String(sig.symbol || focusSymbol).toUpperCase();
    const signalPrice = sig.signal_limit_price != null ? fmtMoney(sig.signal_limit_price) : fmtMoney((sig.reference_price || sig.fill_price || 0));
    const signalMeaning = sig.risk_can_proceed === false
      ? ('Signal blocked by ' + (sig.risk_block_reason || 'risk') + '.')
      : ('Signal is cleared by risk and can trade when the paper lane is allowed to fire.');
    const paperFocusLine = paperEligibleFocus
      ? ('Paper-eligible symbol: ' + paperEligibleFocus + '.')
      : 'No paper-eligible symbol is ready yet.';
    signalEl.innerHTML =
      '<div class="signal-card ' + esc(signalTone) + '">' +
        '<div class="signal-head"><div><div class="signal-kicker">Latest signal</div><strong>' + esc((sig.signal_action || 'hold').toUpperCase() + ' ' + (sig.symbol || '')) + '</strong></div><div>' + esc(((sig.active_policy || sig.strategy_name || 'policy').replace(/_/g, ' ')) + ' / ' + ((sig.market_regime || 'unknown').replace(/_/g, ' '))) + '</div></div>' +
        '<div class="signal-quote"><div class="signal-price">' + esc(signalPrice) + '</div><div class="signal-side">' + esc(plainRiskReason(sig)) + '</div></div>' +
        '<div class="signal-body">' + esc(plainSignalBody(sig, paperEligibleFocus)) + '</div>' +
        '<div class="signal-body">' + esc('Setup tag: ' + (sig.setup_tag || 'monitor only') + '.' + (sig.relative_strength_label ? (' ' + sig.relative_strength_label + '.') : '')) + '</div>' +
        '<div class="signal-body">' + esc([
          sig.relative_volume != null ? ('Relative volume ' + Number(sig.relative_volume).toFixed(1) + 'x.') : '',
          sig.gap_pct != null ? ('Gap ' + (Number(sig.gap_pct) >= 0 ? '+' : '') + (Number(sig.gap_pct) * 100).toFixed(1) + '%.') : '',
          sig.float_turnover_pct != null ? ('Float turnover ' + (Number(sig.float_turnover_pct) * 100).toFixed(2) + '%.') : '',
        ].filter(Boolean).join(' ')) + '</div>' +
        '<div class="signal-body">' + esc([
          Number(paperPolicy.round_trip_cost_usd || 0) > 0 ? ('Estimated round-trip cost ' + fmtMoney(paperPolicy.round_trip_cost_usd) + '.') : '',
          Number(paperPolicy.net_expected_edge_usd || 0) > 0 ? ('Expected net edge ' + fmtMoney(paperPolicy.net_expected_edge_usd) + '.') : '',
          Number(paperPolicy.net_expected_edge_pct || 0) > 0 ? ('Net edge ' + (Number(paperPolicy.net_expected_edge_pct) * 100).toFixed(2) + '%.') : '',
        ].filter(Boolean).join(' ')) + '</div>' +
        '<div class="signal-body">' + esc('Scanner focus: ' + focusSymbol + '. Signal symbol: ' + signalSymbol + '. ' + paperFocusLine) + '</div>' +
        '<div class="signal-body">' + esc(signalMeaning) + '</div>' +
      '</div>';
  } else {
    signalEl.innerHTML = '<div class="muted-copy">No Belfort signal recorded yet.</div>';
  }

  const lanes = [];
  lanes.push({
    title: 'Paper lane',
    text:
      (latestPaperFill
        ? ('Last synced fill: ' + String(latestPaperFill.action || 'trade').toUpperCase() + ' ' + (latestPaperFill.symbol || 'SPY') + ' @ ' + fmtMoney(latestPaperFill.broker_fill_price || latestPaperFill.limit_price || 0) + '.')
        : latestPaperExec
          ? (plainPaperSummary(latestPaperExec, sessionLabel) || 'Paper lane updated.')
          : (b.belfort_paper_unavailable_reason || 'No paper order has been submitted today yet.'))
  });
  lanes.push({
    title: 'Practice sim',
    text:
      (b.sim_active ? 'Running. ' : 'Stopped. ') +
      simTicks + ' ticks, ' + simFills + ' fills on ' + focusSymbol + '. ' +
      (latestSimRecord && latestSimRecord.action !== 'hold'
        ? ('Last sim fill: ' + String(latestSimRecord.action || 'trade').toUpperCase() + ' ' + (latestSimRecord.symbol || 'SPY') + ' @ ' + fmtMoney(latestSimRecord.fill_price || 0) + '.')
        : (plainSimReason(simBlockedReason, simTicks, simFills) || 'Belfort is still waiting for a valid simulated setup.'))
  });
  lanes.push({
    title: 'Regular session',
    text: 'Submitted ' + ((paperStats.submitted) || 0) + ', filled ' + ((paperStats.filled) || 0) + ', gated ' + ((paperStats.gated) || 0) + '.'
  });
  lanes.push({
    title: 'Tracking health',
    text:
      (brokerStatus.has_credentials ? 'paper broker online' : 'paper broker not ready') +
      '. ' + (reconciliation.halted ? 'Position tracking is halted.' : 'Position tracking is clear.')
  });
  document.getElementById('belfort-lanes').innerHTML = lanes.map((item) =>
    '<div class="lane-card"><strong>' + esc(item.title) + '</strong><span>' + esc(item.text) + '</span></div>'
  ).join('');

  document.getElementById('belfort-account-summary').innerHTML = [
    compactRow('Paper equity', fmtMoney(tradeWorkspaceState.account.paperEquity)),
    compactRow('Cash available', fmtMoney(tradeWorkspaceState.account.cash)),
    compactRow('Buying power', fmtMoney(tradeWorkspaceState.account.buyingPower)),
    compactRow('Net P&L', fmtMoney(tradeWorkspaceState.account.pnl)),
    compactRow('Trades', String(tradeWorkspaceState.account.tradeCount)),
    compactRow('Open names', tradeWorkspaceState.account.openPositions.length ? tradeWorkspaceState.account.openPositions.join(', ') : 'No open positions'),
  ].join('');
  document.getElementById('belfort-order-summary').innerHTML = [
    compactRow('Paper lane', tradeWorkspaceState.controls.tradingActive ? 'Running' : 'Stopped'),
    compactRow('Broker truth', tradeWorkspaceState.account.truthSource === 'alpaca_broker' ? 'Alpaca paper account' : 'Local fallback'),
    compactRow('Pacing', orderPacingState),
    compactRow('Close-all', (tradeWorkspaceState.account.openPositions || []).length ? ('Ready for ' + tradeWorkspaceState.account.openPositions.length + ' open name(s)') : 'No open paper positions'),
    compactRow('Latest paper', latestPaperFill ? (String(latestPaperFill.action || 'trade').toUpperCase() + ' ' + (latestPaperFill.symbol || 'SPY')) : (latestPaperExec ? clip(plainPaperSummary(latestPaperExec, sessionLabel) || 'Paper lane updated.', 72) : 'No submitted order yet')),
    compactRow('Working orders', String(orderMonitor.open_orders || 0)),
    compactRow('Sim lane', tradeWorkspaceState.controls.simActive ? (simTicks + ' ticks, ' + simFills + ' fills') : 'Stopped'),
  ].join('');
  document.getElementById('belfort-order-monitor').innerHTML = [
    compactRow('Working orders', String(orderMonitor.open_orders || 0)),
    compactRow('Stale orders', String(orderMonitor.stale_open_orders || 0)),
    compactRow('Placed today', String(orderMonitor.orders_placed || 0)),
    compactRow('Fills / rejects', String(orderMonitor.fills || 0) + ' / ' + String(orderMonitor.rejects || 0)),
    compactRow('Oldest working', orderMonitor.open_orders ? String(orderMonitor.oldest_open_age_label || 'unknown') : 'none'),
    compactRow('Last broker update', orderMonitor.latest_update_age_label ? (String(orderMonitor.latest_update_age_label) + ' ago') : 'none'),
    ...(orderMonitor.stale_warning ? [compactRow('Stale warning', clip(String(orderMonitor.stale_warning), 96))] : []),
    compactRow(
      'Latest status',
      Array.isArray(orderMonitor.recent_events) && orderMonitor.recent_events.length
        ? clip(humanizeOrderEvent(orderMonitor.recent_events[orderMonitor.recent_events.length - 1]), 84)
        : 'No recent order updates'
    ),
    ...((Array.isArray(orderMonitor.working_orders) ? orderMonitor.working_orders : []).slice(0, 2).map((row, idx) =>
      compactRow('Working ' + (idx + 1), clip(orderMonitorLine(row), 96))
    )),
  ].join('');
  document.getElementById('belfort-readiness-compact').innerHTML = [
    compactRow('Verdict', tradeWorkspaceState.readiness.verdict),
    compactRow('Session', sessionLabel),
    compactRow('Paper focus', paperEligibleFocus || 'None yet'),
    compactRow('Status', clip(tradeWorkspaceState.readiness.summary, 96)),
  ].join('');
  document.getElementById('belfort-why-not-trading').innerHTML = [
    compactRow('Current', whyNotTrading || 'Belfort is actively trading or waiting for the next allowed setup.'),
    ...(brokerPositionWarning ? [compactRow('Broker note', brokerPositionWarning)] : []),
    compactRow('Order pace', orderPacingState),
    compactRow('Capacity left', fmtMoney(remainingExposureCapacity) + ' buying power room, ' + remainingDailyCapacity + ' order slot(s) left'),
    compactRow('Structure', candidateStructureNote(focusCandidate) || 'Company structure data is still loading.'),
    compactRow('Signal', sig ? (String(sig.symbol || focusSymbol).toUpperCase() + '. ' + plainRiskReason(sig)) : 'No fresh signal yet'),
  ].join('');
  const proofItems = Array.isArray(operatorState.proof_chain) ? operatorState.proof_chain : [];
  document.getElementById('belfort-open-proof').innerHTML = proofItems.length
    ? proofItems.map((item) =>
        '<div class="proof-item"><div class="proof-head"><div class="proof-title">' + esc(item.label || 'Proof') + '</div><div class="proof-status ' + esc(item.status || 'warming') + '">' + esc(item.status || 'warming') + '</div></div><div class="proof-note">' + esc(item.note || '') + '</div></div>'
      ).join('')
    : '<div class="proof-item"><div class="proof-head"><div class="proof-title">Open Proof</div><div class="proof-status warming">warming</div></div><div class="proof-note">Proof chain is still loading.</div></div>';

  const learningRows = [];
  if (_learning) {
    learningRows.push({title: 'Verdict', text: ((_learning.verdict || '--').toUpperCase()) + '. ' + (_learning.verdict_note || '')});
    learningRows.push({title: 'Helping', text: (_learning.helping && _learning.helping[0]) || 'No clear support signal yet.'});
    learningRows.push({title: 'Hurting', text: (_learning.hurting && _learning.hurting[0]) || 'No major issue flagged.'});
    if (_learning.research_goal) learningRows.push({title: 'Research goal', text: _learning.research_goal});
    learningRows.push({title: 'Today paper', text: 'Submitted ' + ((paperStats.submitted) || 0) + ', filled ' + ((paperStats.filled) || 0) + ', gated ' + ((paperStats.gated) || 0) + '.'});
    learningRows.push({title: 'Closed-session training', text: simTicks + ' sim ticks and ' + simFills + ' fills. ' + plainSimReason(simBlockedReason, simTicks, simFills)});
    if (learnStrip.main_blocker) learningRows.push({title: 'Main blocker', text: learnStrip.main_blocker});
  } else {
    learningRows.push({title: 'Learning', text: 'Loading Belfort learning snapshot...'});
  }
  document.getElementById('belfort-learning').innerHTML = learningRows.map((item) =>
    '<div class="summary-item"><strong>' + esc(item.title) + '</strong><span>' + esc(item.text) + '</span></div>'
  ).join('');

  const setupLeaders = Array.isArray(setupScorecard.leaders) ? setupScorecard.leaders : [];
  const bestRegular = setupScorecard.best_regular || null;
  const bestSim = setupScorecard.best_sim || null;
  const bestFeeSurvivor = setupScorecard.best_fee_survivor || null;
  const setupRows = [];
  if (bestRegular) {
    setupRows.push({
      title: 'Regular-session leader',
      text: String(bestRegular.setup_tag || 'monitor only') + '. ' +
        String(bestRegular.paper_submitted || 0) + ' submitted, ' +
        String(bestRegular.paper_filled || 0) + ' filled. ' +
        (Array.isArray(bestRegular.symbols) && bestRegular.symbols.length ? bestRegular.symbols.join(', ') : 'no symbols yet'),
    });
  }
  if (bestSim) {
    setupRows.push({
      title: 'Sim leader',
      text: String(bestSim.setup_tag || 'monitor only') + '. ' +
        String(bestSim.sim_fills || 0) + ' sim fill(s). ' +
        (Array.isArray(bestSim.symbols) && bestSim.symbols.length ? bestSim.symbols.join(', ') : 'no symbols yet'),
    });
  }
  if (bestFeeSurvivor) {
    setupRows.push({
      title: 'Fee survivor',
      text: String(bestFeeSurvivor.setup_tag || 'monitor only') + '. ' +
        'Avg net edge ' + (((Number(bestFeeSurvivor.avg_net_expected_edge_pct || 0) * 100).toFixed(2)) + '%') + ', ' +
        'avg round-trip cost ' + fmtMoney(bestFeeSurvivor.avg_round_trip_cost_usd || 0) + ', ' +
        String(bestFeeSurvivor.fee_blocks || 0) + ' fee-related block(s).',
    });
  }
  setupLeaders.slice(0, 3).forEach((item) => {
    setupRows.push({
      title: String(item.setup_tag || 'monitor only'),
      text: String(item.signals || 0) + ' signals, ' +
        String(item.risk_cleared || 0) + ' cleared, ' +
        String(item.blocked || 0) + ' blocked, ' +
        String(item.paper_filled || 0) + ' paper filled, ' +
        String(item.sim_fills || 0) + ' sim fill(s).',
    });
  });
  if (!setupRows.length) {
    setupRows.push({
      title: 'Setup scorecards warming up',
      text: 'Belfort has not logged enough named setup history yet to score the desk.',
    });
  }
  document.getElementById('belfort-setups').innerHTML = setupRows.map((item) =>
    '<div class="summary-item"><strong>' + esc(item.title) + '</strong><span>' + esc(item.text) + '</span></div>'
  ).join('');

  const readinessChecklist = Array.isArray(operatorState.checklist) ? operatorState.checklist : [];
  const readinessRows = [
    '<div class="summary-item"><strong>' + esc((operatorState.verdict || 'not_ready').replace(/_/g, ' ')) + '</strong><span>' + esc(operatorSummary) + '</span></div>',
  ];
  if (latestPaperFill) {
    readinessRows.push('<div class="summary-item"><strong>Latest tracked paper fill</strong><span>' + esc(String(latestPaperFill.action || 'trade').toUpperCase() + ' ' + (latestPaperFill.symbol || 'SPY') + ' @ ' + fmtMoney(latestPaperFill.broker_fill_price || latestPaperFill.limit_price || 0)) + '</span></div>');
  }
  readinessChecklist.forEach((item) => readinessRows.push(readinessItemHtml(item)));
  document.getElementById('belfort-readiness').innerHTML = readinessRows.join('');

  const propEl = document.getElementById('belfort-proposal');
  const actEl = document.getElementById('belfort-proposal-actions');
  if (_proposal && _proposal.proposal && !_proposal.dismissed) {
    const prop = _proposal.proposal;
    const noop = prop.current_value === prop.proposed_value;
    const body = noop
      ? 'Current parameter already matches the recommended target.'
      : (prop.parameter + ' from ' + prop.current_value + ' to ' + prop.proposed_value + ' - ' + (prop.reason || 'suggested by current evidence'));
    propEl.innerHTML = '<div class="summary-item"><strong>' + esc(prop.parameter || 'Recommendation') + '</strong><span>' + esc(body) + '</span></div>';
    actEl.innerHTML = noop ? '' : [
      proposalButton(_belfortPendingAction === 'proposal-apply' ? 'Applying...' : 'Apply Suggested Adjustment', 'apply', {primary: true, disabled: !!_belfortPendingAction}),
      proposalButton(_belfortPendingAction === 'proposal-dismiss' ? 'Keeping...' : 'Keep Current Strategy', 'dismiss', {disabled: !!_belfortPendingAction}),
    ].join('');
  } else if (_proposal && _proposal.dismissed) {
    propEl.innerHTML = '<div class="summary-item"><strong>Dismissed</strong><span>This suggestion is hidden until the recommendation changes or the cooldown expires.</span></div>';
    actEl.innerHTML = '';
  } else {
    propEl.innerHTML = '<div class="summary-item"><strong>No active proposal</strong><span>Belfort does not have a structured adjustment waiting right now.</span></div>';
    actEl.innerHTML = '';
  }

  const ledgerFilters = [
    ['all', 'All'],
    ['signal', 'Signals'],
    ['paper', 'Paper'],
    ['sim', 'Sim'],
    ['learning', 'Learning'],
    ['adjustment', 'Adjustments'],
  ];
  document.getElementById('belfort-ledger-toolbar').innerHTML = ledgerFilters.map((item) =>
    '<button class="chip ' + (_belfortLedgerFilter === item[0] ? 'active' : '') + '" onclick="setBelfortLedgerFilter(\'' + item[0] + '\')">' + esc(item[1]) + '</button>'
  ).join('');

  const ledgerRows = activityFeed.map((item) => ({
    source: item.source || 'signal',
    kind: item.tone || 'ok',
    title: item.title || 'Activity',
    text: item.summary || '',
    timestamp: item.timestamp || '',
  }));
  if (_learning) {
    ledgerRows.unshift({
      source: 'learning',
      kind: (_learning.verdict === 'continue' ? 'ok' : 'pending'),
      title: 'Learning verdict',
      text: ((_learning.verdict || '--').toUpperCase()) + '. ' + (_learning.verdict_note || 'No learning note yet.'),
      timestamp: '',
    });
  }
  if (_proposal && _proposal.proposal) {
    const prop = _proposal.proposal;
    ledgerRows.unshift({
      source: 'adjustment',
      kind: _proposal.dismissed ? 'warn' : 'pending',
      title: _proposal.dismissed ? 'Adjustment dismissed' : 'Adjustment waiting',
      text: prop.current_value === prop.proposed_value
        ? 'Current parameter already matches the recommended target.'
        : ((prop.parameter || 'parameter') + ' from ' + prop.current_value + ' to ' + prop.proposed_value),
      timestamp: _proposal.dismissed_at || '',
    });
  }
  if (_belfortAction) {
    ledgerRows.unshift({
      source: 'operator',
      kind: _belfortAction.kind || 'ok',
      title: _belfortAction.title || 'Desk update',
      text: _belfortAction.text || '',
      timestamp: '',
    });
  }
  const filteredRows = ledgerRows.filter((item) => _belfortLedgerFilter === 'all' || item.source === _belfortLedgerFilter);
  if (!filteredRows.length) {
    filteredRows.push({source: 'all', kind: 'ok', title: 'Ledger idle', text: 'No Belfort events match this filter yet.', timestamp: ''});
  }
  document.getElementById('belfort-feed').innerHTML = filteredRows.slice(0, 14).map((item) => {
    const clean = humanizeBlotterItem(item);
    return '<div class="blotter-item ' + esc(item.kind || '') + '"><strong>' + esc(clean.title) + '</strong><span>' + esc(clean.text) + '</span>' + (item.timestamp ? '<small>' + esc(fmtAgo(item.timestamp)) + ' • ' + esc(item.source || 'activity') + '</small>' : '<small>' + esc(item.source || 'activity') + '</small>') + '</div>';
  }).join('');
  document.getElementById('belfort-blotter-compact').innerHTML = filteredRows
    .filter((item) => ['signal', 'paper', 'sim', 'operator'].includes(item.source))
    .slice(0, 3)
    .map((item) => {
      const clean = humanizeBlotterItem(item);
      return '<div class="blotter-item ' + esc(item.kind || '') + '"><strong>' + esc(clean.title) + '</strong><span>' + esc(clean.text) + '</span><small>' + esc(item.source || 'activity') + '</small></div>';
    }).join('') || '<div class="blotter-item"><strong>Blotter is quiet</strong><span>No recent signal, paper, or sim activity yet.</span></div>';

  if (Array.isArray(orderMonitor.recent_events) && orderMonitor.recent_events.length) {
    const orderRows = orderMonitor.recent_events.slice(-3).map((event) => ({
      source: 'paper',
      kind: ['reject', 'cancel', 'expired'].includes(String(event.event_type || '').toLowerCase()) ? 'warn' : 'ok',
      title: 'Order ' + String(event.event_type || 'update').replace(/_/g, ' '),
      text: humanizeOrderEvent(event),
      timestamp: event.timestamp_utc || '',
    }));
    document.getElementById('belfort-blotter-compact').innerHTML = orderRows.map((item) =>
      '<div class="blotter-item ' + esc(item.kind || '') + '"><strong>' + esc(item.title) + '</strong><span>' + esc(item.text) + '</span><small>' + esc(item.timestamp ? fmtAgo(item.timestamp) + ' • paper' : 'paper') + '</small></div>'
    ).join('') + document.getElementById('belfort-blotter-compact').innerHTML;
  }
}

function renderPeter() {
  if (!_state) return;
  const b = _state.belfort || {};
  const f = _state.frank_lloyd || {};
  const readiness = b.belfort_paper_open_readiness || b.belfort_operator_state || {};
  const summary = [];
  summary.push({title: 'Front door role', text: 'Peter coordinates the house, routes requests, and keeps the operator oriented.'});
  summary.push({title: 'Belfort now', text: 'Mode ' + (b.belfort_mode || '--') + ', readiness ' + humanVerdictLabel(readiness) + ', last signal ' + (b.belfort_latest_signal ? ((b.belfort_latest_signal.signal_action || 'hold').toUpperCase()) : 'none') + '.'});
  summary.push({title: 'Frank now', text: f.active_job ? ((f.active_job.title || f.active_job.build_id || '') + ' [' + (f.active_job.status || '') + ']') : 'Frank Lloyd is idle.'});
  document.getElementById('peter-summary').innerHTML = summary.map((item) =>
    '<div class="summary-item"><strong>' + esc(item.title) + '</strong><span>' + esc(item.text) + '</span></div>'
  ).join('');
  renderChatHistory('peter-chat-history', _peterChat, 'Peter');
}

function renderFrank() {
  if (!_state) return;
  const f = _state.frank_lloyd || {};
  const rows = [];
  if (f.active_job) {
    rows.push({title: 'Active build', text: (f.active_job.title || f.active_job.build_id || '') + ' [' + (f.active_job.status || '').replace(/_/g, ' ') + ']'});
    rows.push({title: 'Next action', text: f.active_job.next_action || 'Check the draft or stream.'});
  } else {
    rows.push({title: 'No active build', text: (f.pending_count || 0) + ' queued. Frank Lloyd is available for builder work.'});
  }
  rows.push({title: 'Intake', text: f.fl_enabled === false ? 'Frank intake is disabled.' : 'Frank intake is enabled.'});
  document.getElementById('frank-summary').innerHTML = rows.map((item) =>
    '<div class="summary-item"><strong>' + esc(item.title) + '</strong><span>' + esc(item.text) + '</span></div>'
  ).join('');
  renderChatHistory('frank-chat-history', _frankChat, 'Frank Lloyd');
}

function renderControls() {
  if (!_state) return;
  const b = _state.belfort || {};
  const readiness = b.belfort_paper_open_readiness || b.belfort_operator_state || {};
  const rows = [
    {title: 'Belfort mode', text: (b.belfort_mode || '--') + ' | readiness: ' + humanVerdictLabel(readiness)},
    {title: 'Scanner focus', text: (b.belfort_focus_symbol || 'SPY') + ' | ' + clip(plainScannerReason(b.belfort_focus_reason || 'Scanner warming up.', b.belfort_focus_symbol || 'SPY'), 90)},
    {title: 'Paper lane', text: b.trading_active ? 'Running paper/shadow loop.' : 'Paper loop stopped.'},
    {title: 'Sim lane', text: b.sim_active ? ('Running sim with ' + (b.sim_fills || 0) + ' fills.') : 'Sim lane stopped.'},
  ];
  document.getElementById('controls-summary').innerHTML = rows.map((item) =>
    '<div class="summary-item"><strong>' + esc(item.title) + '</strong><span>' + esc(item.text) + '</span></div>'
  ).join('');
  document.getElementById('controls-feed').innerHTML = _controlFeed.map((item) =>
    '<div class="feed-item ' + esc(item.kind || '') + '"><strong>' + esc(item.title) + '</strong><span>' + esc(item.text) + '</span></div>'
  ).join('');
}

function renderGuide() {
  if (!_state) return;
  const b = _state.belfort || {};
  const scanner = b.belfort_scanner || {};
  const summaryRows = [
    {title: 'What Belfort does', text: 'Scans symbols, reads catalysts, evaluates setups, checks risk, and keeps paper and sim separate.'},
    {title: 'Focus right now', text: (b.belfort_focus_symbol || 'SPY') + ' — ' + plainScannerReason(b.belfort_focus_reason || 'Scanner warming up.', b.belfort_focus_symbol || 'SPY')},
    {title: 'Trades when', text: b.belfort_paper_available ? 'Regular session is open and the paper lane can submit orders.' : (b.belfort_paper_unavailable_reason || 'Regular session gate is closed.')},
    {title: 'Connected to', text: 'Alpaca market data, Alpaca paper broker, Belfort policy selector, risk gate, proposal parser, and the local audit logs.'},
    {title: 'Scanner factors', text: ((scanner.selection_framework || []).join(', ')) || 'quote quality, tape momentum, range expansion, relative strength, catalysts, risk flags'},
    {title: 'Learning model', text: 'Belfort now keeps named setup tags and setup scorecards across signal, paper, and sim lanes.'},
    {title: 'Current limits', text: ((scanner.limitations || []).join(' ')) || 'Belfort now reads catalysts, float, market cap, and multi-symbol tape, but paper eligibility is still tighter than research ranking.'},
  ];
  const summaryHtml = summaryRows.map((item) =>
    '<div class="summary-item"><strong>' + esc(item.title) + '</strong><span>' + esc(item.text) + '</span></div>'
  ).join('');
  document.getElementById('guide-summary').innerHTML = summaryHtml;
  document.getElementById('belfort-guide-summary').innerHTML = summaryHtml;

  const docs = [
    ['BELFORT_HOW_IT_WORKS.md', 'How It Works'],
    ['BRD.md', 'BRD'],
    ['TRD.md', 'TRD'],
  ];
  const toolbarHtml = docs.map((item) =>
    '<button class="chip ' + (_docs.current === item[0] ? 'active' : '') + '" onclick="selectGuideDoc(\'' + item[0] + '\')">' + esc(item[1]) + '</button>'
  ).join('');
  document.getElementById('guide-toolbar').innerHTML = toolbarHtml;
  document.getElementById('belfort-guide-toolbar').innerHTML = toolbarHtml;

  const currentDoc = _docs.cache[_docs.current];
  if (currentDoc) {
    document.getElementById('guide-doc-title').textContent = currentDoc.label || _docs.current;
    document.getElementById('guide-doc-meta').textContent = _docs.current;
    document.getElementById('guide-doc').innerHTML = markdownLite(currentDoc.content || '');
    document.getElementById('belfort-guide-doc-title').textContent = currentDoc.label || _docs.current;
    document.getElementById('belfort-guide-doc-meta').textContent = _docs.current;
    document.getElementById('belfort-guide-doc').innerHTML = markdownLite(currentDoc.content || '');
  } else {
    document.getElementById('guide-doc-title').textContent = 'Guide';
    document.getElementById('guide-doc-meta').textContent = _docs.current;
    document.getElementById('guide-doc').innerHTML = '<p>Loading Belfort guide...</p>';
    document.getElementById('belfort-guide-doc-title').textContent = 'Guide';
    document.getElementById('belfort-guide-doc-meta').textContent = _docs.current;
    document.getElementById('belfort-guide-doc').innerHTML = '<p>Loading Belfort guide...</p>';
  }
}

async function selectGuideDoc(file) {
  try {
    await loadGuideDoc(file);
    renderGuide();
  } catch (err) {
    document.getElementById('guide-doc-title').textContent = 'Guide load error';
    document.getElementById('guide-doc-meta').textContent = file;
    document.getElementById('guide-doc').innerHTML = '<p>' + esc(err.message || 'Could not load guide doc.') + '</p>';
    document.getElementById('belfort-guide-doc-title').textContent = 'Guide load error';
    document.getElementById('belfort-guide-doc-meta').textContent = file;
    document.getElementById('belfort-guide-doc').innerHTML = '<p>' + esc(err.message || 'Could not load guide doc.') + '</p>';
  }
}

function renderChatHistory(id, messages, agentName) {
  const el = document.getElementById(id);
  el.innerHTML = messages.map((msg) =>
    '<div class="chat-msg ' + esc(msg.role) + '"><small>' + esc(msg.role === 'agent' ? agentName : 'Operator') + '</small><p>' + esc(msg.text) + '</p></div>'
  ).join('');
  el.scrollTop = el.scrollHeight;
}

async function refreshAll() {
  try {
    _state = await fetchJson('/neighborhood/state');
    const focusSymbol = (((_state || {}).belfort || {}).belfort_focus_symbol || 'SPY');
    const results = await Promise.all([
      fetchJson('/belfort/learning'),
      fetchJson('/monitor/proposal'),
      fetchJson('/monitor/strategy?symbol=' + encodeURIComponent(focusSymbol)),
      fetchJson('/monitor/regime?symbol=' + encodeURIComponent(focusSymbol)),
      loadBelfortChart(focusSymbol).catch(() => _belfortChart),
      loadGuideDoc(_docs.current).catch(() => _docs.cache[_docs.current] || null),
    ]);
    _learning = results[0];
    _proposal = results[1];
    _strategy = results[2];
    _regime = results[3];
    renderAll();
    const now = new Date();
    document.getElementById('pill-refresh').textContent = 'Refresh ' + now.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
    document.getElementById('rail-refresh').textContent = 'Last refresh ' + now.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
  } catch (err) {
    feed('warn', 'Refresh error', err.message || 'Could not load cockpit state.');
  }
}

function renderAll() {
  if (!_state) return;
  const now = new Date();
  const b = _state.belfort || {};
  const readiness = b.belfort_paper_open_readiness || b.belfort_operator_state || {};
  document.getElementById('rail-mode').textContent = 'Belfort: ' + String(b.belfort_mode || '--').toUpperCase();
  document.getElementById('rail-readiness').textContent = 'Readiness ' + humanVerdictLabel(readiness) + ' · focus ' + String(b.belfort_focus_symbol || '--').toUpperCase();
  document.getElementById('rail-loop').textContent = 'Paper lane: ' + (b.trading_active ? 'running' : 'stopped');
  document.getElementById('rail-sim').textContent = humanSessionLabel(b.belfort_session_type || 'unknown') + ' · sim ' + (b.sim_active ? 'running' : 'stopped');
  document.getElementById('rail-clock').textContent = now.toLocaleDateString([], {weekday: 'long', month: 'short', day: 'numeric'}) + '  ' + now.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
  document.getElementById('pill-backend').textContent = 'Backend ' + ((_state.backend || {}).status || '--');
  document.getElementById('pill-lm').textContent = 'LM ' + (_state.lm_available ? 'available' : 'offline');
  renderOverview();
  renderBelfort();
  renderPeter();
  renderFrank();
  renderControls();
  renderGuide();
}

function fillPeter(text) {
  const el = document.getElementById('peter-chat-input');
  el.value = text;
  el.focus();
}

function fillFrank(text) {
  const el = document.getElementById('frank-chat-input');
  el.value = text;
  el.focus();
}

function looksLikeBuildIntent(text) {
  const lower = text.toLowerCase().trim();
  return /\b(build|add|make|create|write|implement|fix|refactor|clean|diagnose|improve|remove|update|rewrite)\b/.test(lower);
}

async function peterSend() {
  const input = document.getElementById('peter-chat-input');
  const button = document.getElementById('peter-send');
  const message = input.value.trim();
  if (!message) return;
  input.value = '';
  button.disabled = true;
  _peterChat.push({role: 'operator', text: message});
  _peterChat.push({role: 'agent', text: '...'});
  renderPeter();
  try {
    let response;
    if (looksLikeBuildIntent(message)) {
      response = await fetchJson('/peter/queue-build', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({message}),
      });
      _peterChat.pop();
      _peterChat.push({role: 'agent', text: response.text || response.question || 'Queued.'});
    } else {
      response = await fetchJson('/peter/action', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({message}),
      });
      if (response.command_type === 'unknown') {
        response = await fetchJson('/peter/chat', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({message}),
        });
        _peterChat.pop();
        _peterChat.push({role: 'agent', text: response.text || 'Peter could not answer that right now.'});
      } else {
        _peterChat.pop();
        _peterChat.push({role: 'agent', text: response.summary || 'Done.'});
      }
    }
  } catch (err) {
    _peterChat.pop();
    _peterChat.push({role: 'agent', text: 'Peter could not be reached right now.'});
  } finally {
    button.disabled = false;
    renderPeter();
    refreshAll();
  }
}

async function frankSend() {
  const input = document.getElementById('frank-chat-input');
  const button = document.getElementById('frank-send');
  const message = input.value.trim();
  if (!message) return;
  input.value = '';
  button.disabled = true;
  _frankChat.push({role: 'operator', text: message});
  _frankChat.push({role: 'agent', text: '...'});
  renderFrank();
  try {
    const response = await fetchJson('/frank-lloyd/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message}),
    });
    _frankChat.pop();
    _frankChat.push({role: 'agent', text: response.text || 'Frank Lloyd completed that action.'});
  } catch (err) {
    _frankChat.pop();
    _frankChat.push({role: 'agent', text: 'Frank Lloyd could not be reached right now.'});
  } finally {
    button.disabled = false;
    renderFrank();
    refreshAll();
  }
}

async function proposalAction(kind) {
  setBelfortAction(
    'pending',
    kind === 'apply' ? 'Applying suggested adjustment' : 'Keeping current strategy',
    kind === 'apply'
      ? 'Belfort is sending the bounded proposal through the audited apply path.'
      : 'Belfort is recording a cooldown dismissal for the current recommendation.',
    kind === 'apply' ? 'proposal-apply' : 'proposal-dismiss'
  );
  try {
    if (kind === 'apply') {
      const result = await fetchJson('/monitor/proposal/apply', {method: 'POST'});
      setBelfortAction('ok', 'Proposal applied', result.message || 'Belfort strategy parameters were updated through the bounded proposal path.');
      feed('ok', 'Proposal applied', result.message || 'Belfort strategy parameters were updated through the bounded proposal path.');
    } else {
      const result = await fetchJson('/monitor/proposal/dismiss', {method: 'POST'});
      setBelfortAction('ok', 'Strategy kept', result.dismissed_at ? ('Recommendation hidden at ' + result.dismissed_at) : 'The current structured recommendation has been hidden for its cooldown window.');
      feed('ok', 'Proposal dismissed', 'The current structured recommendation has been hidden for its cooldown window.');
    }
    await refreshAll();
  } catch (err) {
    setBelfortAction('warn', 'Proposal action failed', err.message || 'Could not complete the proposal action.');
    feed('warn', 'Proposal action failed', err.message || 'Could not complete the proposal action.');
  }
}

async function controlAction(action) {
  const routes = {
    'start-paper': ['/monitor/trading/start?interval=3', {method: 'POST'}, 'ok', 'Paper loop started'],
    'stop-paper': ['/monitor/trading/stop?close_positions=true', {method: 'POST'}, 'ok', 'Stop and close-all requested'],
    'flatten-paper': ['/monitor/trading/flatten', {method: 'POST'}, 'ok', 'Close-all requested'],
    'start-sim': ['/monitor/trading/sim/start?interval=5', {method: 'POST'}, 'ok', 'Practice sim started'],
    'stop-sim': ['/monitor/trading/sim/stop', {method: 'POST'}, 'ok', 'Practice sim stopped'],
    'advance-mode': ['/monitor/belfort/mode/advance', {method: 'POST'}, 'ok', 'Belfort mode advance attempted'],
    'reset-paper': ['/monitor/trading/reset', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({reason: 'Operator reset from analog cockpit'})}, 'warn', 'Paper portfolio reset'],
  };
  const spec = routes[action];
  if (!spec) return;
  setBelfortAction('pending', spec[3], 'Sending operator request through Belfort control lane.', action);
  try {
    const result = await fetchJson(spec[0], spec[1]);
    setBelfortAction(spec[2], spec[3], result.message || result.status || result.error || 'Action completed.');
    feed(spec[2], spec[3], result.message || result.status || result.error || 'Action completed.');
    await refreshAll();
  } catch (err) {
    setBelfortAction('warn', 'Control failed', err.message || 'Could not complete the control action.');
    feed('warn', 'Control failed', err.message || 'Could not complete the control action.');
  }
}

document.addEventListener('DOMContentLoaded', () => {
  bindNav();
  refreshAll();
  setInterval(refreshAll, 5000);
  document.getElementById('peter-chat-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); peterSend(); }
  });
  document.getElementById('frank-chat-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); frankSend(); }
  });
});
</script>
</body>
</html>
"""
