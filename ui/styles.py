"""Thème visuel : marine profond, bleu soutenu, fonds crème, accents ambre."""

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@500;600;700;800&family=Source+Sans+3:wght@400;500;600&display=swap');

:root{
  --navy:#0a2550; --navy-2:#0d3470; --blue:#1d5fae; --blue-soft:#e8f0fb;
  --cream:#fffaf0; --cream-2:#fbf3e2; --ink:#0d1b2e; --muted:#5d6b80;
  --amber:#f5d9a8; --amber-ink:#8a5a12; --green:#127a4c; --green-bg:#e3f4ec;
  --red:#b42318; --display:'Manrope','Segoe UI',system-ui,-apple-system,sans-serif; --red-bg:#fde8e6; --line:#e5e9f1;
}
html, body, [data-testid="stAppViewContainer"]{
  background: linear-gradient(180deg,#f4f7fc 0%, #fbf7ee 100%) !important;
  color: var(--ink); font-family:'Source Sans 3', system-ui, sans-serif;
}
h1,h2,h3,h4,.dc-h{font-family:var(--display) !important; color:var(--navy); letter-spacing:-0.01em}
[data-testid="stHeader"]{background:transparent}
.block-container{padding-top:2rem; max-width:1240px}

/* ---------- sidebar */
[data-testid="stSidebar"]{background:linear-gradient(180deg,#071c3e 0%, #0b2f66 100%)}
[data-testid="stSidebar"] *{color:#e8eefb}
[data-testid="stSidebar"] input, [data-testid="stSidebar"] textarea{color:var(--ink) !important}
[data-testid="stSidebar"] [data-baseweb="select"] *{color:var(--ink) !important}
[data-testid="stSidebar"] [data-testid="stExpander"]{border:1px solid rgba(255,255,255,.14); border-radius:12px; background:rgba(255,255,255,.04)}
[data-testid="stSidebar"] .stButton>button{background:rgba(255,255,255,.06); border:1px solid rgba(255,255,255,.22); color:#fff}
[data-testid="stSidebar"] .stButton>button:hover{background:rgba(255,255,255,.14); border-color:#fff}
.dc-logo{width:62px;height:62px;border-radius:50%;display:grid;place-items:center;margin:8px 0 18px;
  background:radial-gradient(circle at 35% 30%,#6fa8ff,#1d5fae 60%,#0a2550);box-shadow:0 0 0 4px rgba(255,255,255,.12),0 10px 30px rgba(29,95,174,.45);font-size:26px;color:#fff}
.dc-brand{font-family:var(--display);font-weight:800;font-size:22px;color:#fff;margin:0}
.dc-sub{font-size:13px;color:#a9bbd9 !important;margin:2px 0 22px}
.dc-pill{border:1px solid rgba(255,255,255,.16);border-radius:12px;padding:12px 14px;font-weight:600;font-size:14px;margin-bottom:12px;background:rgba(255,255,255,.04)}
.dc-dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:8px;vertical-align:middle}
.dc-active{border-left:3px solid #8fb8ff;border-radius:12px;padding:14px 16px;background:rgba(255,255,255,.06);margin-bottom:12px}
.dc-active small{display:block;font-size:11px;letter-spacing:.08em;color:#a9bbd9 !important;font-weight:700}
.dc-active b{display:block;margin:6px 0 2px;font-size:15px;color:#fff}
.dc-active span{font-size:12px;color:#a9bbd9 !important}

/* ---------- hero */
.dc-hero{position:relative;overflow:hidden;border-radius:26px;padding:48px 52px 64px;color:#fff;
  background:radial-gradient(1200px 400px at 80% -10%,#2f74c9 0%,transparent 60%),linear-gradient(135deg,#0a2a5c 0%,#0d3a7c 55%,#184f97 100%);
  box-shadow:0 24px 60px rgba(10,37,80,.28)}
.dc-hero .eyebrow{font-family:var(--display);font-weight:800;font-size:12px;letter-spacing:.18em;color:#cfe0ff;display:flex;align-items:center;gap:12px}
.dc-hero .eyebrow:before{content:"";width:28px;height:2px;background:#cfe0ff;display:inline-block}
.dc-hero h1{color:#fff !important;font-size:48px;line-height:1.05;font-weight:800;margin:14px 0 14px;max-width:820px}
.dc-hero p{color:#d8e4f8;font-size:16.5px;max-width:760px;line-height:1.55;margin:0}
.dc-hero .bubble{position:absolute;right:190px;top:52px;background:#fde7c2;color:#5a3a06;font-family:var(--display);font-weight:800;font-size:13px;padding:9px 16px;border-radius:12px;box-shadow:0 6px 18px rgba(0,0,0,.18)}
.dc-hero svg.bot{position:absolute;right:48px;top:30px;width:170px;height:auto}
.dc-hero svg.wave{position:absolute;left:0;bottom:0;width:100%;height:70px}
@media (max-width:1000px){.dc-hero .bubble,.dc-hero svg.bot{display:none}.dc-hero h1{font-size:34px}.dc-hero{padding:32px 26px 54px}}
@media (prefers-reduced-motion:no-preference){.dc-hero svg.bot{animation:float 6s ease-in-out infinite}}
@keyframes float{0%,100%{transform:translateY(0)}50%{transform:translateY(-8px)}}

/* ---------- upload */
.dc-upload-head{text-align:center;margin:44px 0 18px}
.dc-upload-head .cube{font-size:44px}
.dc-upload-head h3{margin:4px 0 6px;font-size:23px}
.dc-upload-head p{color:var(--muted);font-size:14.5px;margin:0}
[data-testid="stFileUploader"] section{background:var(--cream);border:2px solid #cfdaeb;border-radius:20px;padding:34px;box-shadow:0 14px 40px rgba(10,37,80,.08)}
[data-testid="stFileUploader"] section button{background:linear-gradient(180deg,#1d5fae,#0d3a7c);color:#fff;border:0;border-radius:10px;font-weight:700;padding:8px 22px}
.dc-feature{background:#fff;border:1px solid var(--line);border-radius:18px;padding:20px 22px;display:flex;gap:14px;min-height:118px}
.dc-feature .ic{font-size:28px;line-height:1}
.dc-feature b{font-family:var(--display);color:var(--navy);font-size:15.5px}
.dc-feature p{color:var(--muted);font-size:13.5px;margin:6px 0 0;line-height:1.45}

/* ---------- stepper */
.dc-steps{display:flex;flex-wrap:wrap;justify-content:center;align-items:center;gap:10px;margin:34px 0 10px}
.dc-step{font-family:var(--display);font-weight:700;font-size:15px;padding:12px 22px;border-radius:999px;background:var(--cream);color:var(--navy);box-shadow:0 6px 18px rgba(10,37,80,.08);border:1px solid #f0e6d1}
.dc-step.done{background:var(--green-bg);border-color:#bfe4d1;color:var(--green)}
.dc-step.current{background:var(--navy);color:#fff;border-color:var(--navy)}
.dc-arrow{color:#e0a85a;font-weight:800}

/* ---------- sections */
.dc-sec{margin:46px 0 14px}
.dc-sec .k{font-family:var(--display);font-weight:800;font-size:12px;letter-spacing:.14em;color:var(--blue);display:flex;align-items:center;gap:10px}
.dc-sec .k:before{content:"";width:30px;height:2px;background:var(--blue)}
.dc-sec h2{font-size:28px;font-weight:800;margin:6px 0 4px !important;padding:0 !important}
.dc-sec p{color:var(--muted);margin:0;font-size:15px}

.dc-kpi{background:var(--cream);border-radius:16px;padding:18px 22px;border-top:4px solid var(--blue);box-shadow:0 10px 30px rgba(10,37,80,.07)}
.dc-kpi small{font-family:var(--display);font-weight:800;font-size:11px;letter-spacing:.1em;color:var(--muted)}
.dc-kpi b{display:block;font-family:var(--display);font-size:30px;color:var(--navy);margin-top:8px}
.dc-kpi span{font-size:12.5px;color:var(--muted)}
.dc-chips{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 4px}
.dc-chip{background:#fff;border:1px solid var(--line);border-radius:999px;padding:4px 12px;font-size:12.5px;color:var(--muted)}
.dc-chip b{color:var(--navy)}

/* ---------- action cards */
.dc-act{background:var(--cream);border-radius:16px;border-left:4px solid var(--blue);padding:18px 22px;box-shadow:0 10px 30px rgba(10,37,80,.07);margin-bottom:6px}
.dc-act.off{opacity:.62;background:#fbfbfb}
.dc-act .row{display:flex;flex-wrap:wrap;align-items:center;gap:10px}
.dc-num{width:32px;height:32px;border-radius:9px;background:linear-gradient(180deg,#1d5fae,#0d3a7c);color:#fff;font-family:var(--display);font-weight:800;display:grid;place-items:center;font-size:14px}
.dc-act .t{font-family:var(--display);font-weight:800;color:var(--navy);font-size:16px}
.dc-tag{font-size:12px;font-weight:700;border-radius:999px;padding:3px 10px;background:var(--amber);color:var(--amber-ink)}
.dc-sev{font-family:var(--display);font-size:11px;font-weight:800;letter-spacing:.06em;border-radius:999px;padding:3px 10px}
.dc-sev.HIGH{background:var(--green-bg);color:var(--green)}
.dc-sev.MEDIUM{background:#fff1d6;color:#9a5b00}
.dc-sev.LOW{background:#eef1f6;color:#4b5a72}
.dc-review{font-family:var(--display);font-size:11px;font-weight:800;letter-spacing:.06em;border-radius:999px;padding:3px 10px;background:var(--red-bg);color:var(--red)}
.dc-act .d{color:var(--muted);font-size:14px;margin:10px 0 0 42px}
.dc-act .why{color:#7a8699;font-size:13px;margin:4px 0 0 42px;font-style:italic}

/* ---------- checks */
.dc-check{display:flex;gap:14px;background:#fff;border:1px solid var(--line);border-radius:14px;padding:14px 18px;margin-bottom:10px}
.dc-check .ic{width:30px;height:30px;border-radius:8px;display:grid;place-items:center;font-weight:800;flex:none}
.dc-check.ok .ic{background:var(--green-bg);color:var(--green)}
.dc-check.warn .ic{background:#fff1d6;color:#b26a00}
.dc-check.fail .ic{background:var(--red-bg);color:var(--red)}
.dc-check b{font-family:var(--display);color:var(--navy);font-size:14.5px}
.dc-check p{margin:3px 0 0;color:var(--muted);font-size:13px}

.dc-banner{border-radius:14px;padding:16px 20px;font-weight:600;margin:10px 0 18px}
.dc-banner.ok{background:var(--green-bg);color:var(--green)}
.dc-banner.warn{background:#fdf6d8;color:#8a6200}
.dc-done{display:flex;gap:14px;align-items:center;background:#eaf6f0;border:1px solid #cbe9da;border-radius:16px;padding:16px 20px;margin:14px 0}
.dc-done .ic{width:40px;height:40px;border-radius:10px;background:var(--green);color:#fff;display:grid;place-items:center;font-size:20px;font-weight:800}
.dc-done b{font-family:var(--display);color:var(--navy);font-size:16px}
.dc-done p{margin:2px 0 0;color:var(--muted);font-size:13.5px}
.dc-summary{background:#fff;border:1px solid var(--line);border-radius:14px;padding:16px 20px;color:var(--ink);line-height:1.55}
.dc-trace{font-size:13.5px;border-left:2px solid #cfdaeb;padding:4px 0 4px 14px;margin:0 0 10px 6px}
.dc-trace code{background:var(--blue-soft);color:var(--navy);padding:1px 6px;border-radius:6px}
.dc-trace .r{color:var(--muted)}
.dc-score{display:flex;align-items:baseline;gap:12px;font-family:var(--display)}
.dc-score b{font-size:44px;color:var(--navy)}
.dc-score span{color:var(--green);font-weight:800}

/* ---------- main buttons */
.main .stButton>button[kind="primary"], [data-testid="stMain"] .stButton>button[kind="primary"]{
  background:linear-gradient(90deg,#5b8fd1 0%,#1d5fae 40%,#0d3a7c 100%);border:0;border-radius:12px;height:54px;font-weight:700;font-size:15.5px;
  box-shadow:0 10px 26px rgba(13,58,124,.25)}
[data-testid="stMain"] .stDownloadButton>button{background:var(--cream);border:1px solid #f0e2c4;border-radius:14px;height:52px;color:var(--navy);font-weight:600;width:100%}
[data-testid="stMain"] .stDownloadButton>button:hover{border-color:var(--blue);color:var(--blue)}
[data-testid="stMain"] [data-testid="stExpander"]{background:var(--cream);border-radius:14px;border:1px solid #f0e6d1}
[data-testid="stDataFrame"]{border-radius:14px;overflow:hidden;box-shadow:0 10px 30px rgba(10,37,80,.06)}
:focus-visible{outline:3px solid #6fa8ff !important;outline-offset:2px}
</style>
"""

ROBOT_SVG = """
<svg class="bot" viewBox="0 0 200 240" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <defs>
    <radialGradient id="g1" cx="40%" cy="30%"><stop offset="0" stop-color="#7fb4ff"/><stop offset="1" stop-color="#1d5fae"/></radialGradient>
    <linearGradient id="g2" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#9cc3ff"/><stop offset="1" stop-color="#2a67b8"/></linearGradient>
  </defs>
  <line x1="120" y1="12" x2="120" y2="34" stroke="#9cc3ff" stroke-width="4"/>
  <circle cx="120" cy="10" r="7" fill="#cfe0ff"/>
  <rect x="78" y="32" width="84" height="66" rx="30" fill="url(#g1)" stroke="#cfe0ff" stroke-width="3"/>
  <rect x="90" y="48" width="60" height="32" rx="16" fill="#0a2550"/>
  <circle cx="108" cy="64" r="8" fill="#cfe9ff"/><circle cx="132" cy="64" r="8" fill="#cfe9ff"/>
  <ellipse cx="120" cy="140" rx="36" ry="38" fill="url(#g2)" stroke="#cfe0ff" stroke-width="3"/>
  <circle cx="120" cy="132" r="9" fill="#e6f1ff"/>
  <path d="M120 178 l-14 24 h28z" fill="#9cc3ff" opacity=".6"/>
  <path d="M154 128 q24 18 18 44" stroke="#9cc3ff" stroke-width="8" fill="none" stroke-linecap="round"/>
  <circle cx="172" cy="176" r="7" fill="#cfe0ff"/>
  <path d="M86 130 q-22 26 -40 50" stroke="#9cc3ff" stroke-width="8" fill="none" stroke-linecap="round"/>
  <line x1="58" y1="150" x2="22" y2="214" stroke="#e8b467" stroke-width="5" stroke-linecap="round"/>
  <path d="M8 206 l20 -6 l10 22 l-26 8z" fill="#f2b04c"/>
  <g transform="translate(6,120)">
    <ellipse cx="22" cy="6" rx="22" ry="7" fill="#c8dcf7"/>
    <rect x="0" y="6" width="44" height="40" fill="#7fa6d8"/>
    <ellipse cx="22" cy="46" rx="22" ry="7" fill="#5f88bf"/>
    <ellipse cx="22" cy="20" rx="22" ry="5" fill="none" stroke="#c8dcf7" stroke-width="2"/>
    <ellipse cx="22" cy="33" rx="22" ry="5" fill="none" stroke="#c8dcf7" stroke-width="2"/>
  </g>
  <path d="M28 104 l3 7 7 3 -7 3 -3 7 -3 -7 -7 -3 7 -3z" fill="#fff"/>
</svg>"""

WAVE_SVG = """<svg class="wave" viewBox="0 0 1200 70" preserveAspectRatio="none" aria-hidden="true">
<path d="M0 40 C200 10 400 70 600 40 C800 10 1000 60 1200 30 L1200 70 L0 70Z" fill="rgba(255,255,255,.07)"/>
<path d="M0 55 C250 30 450 75 700 52 C900 34 1050 64 1200 50 L1200 70 L0 70Z" fill="rgba(255,255,255,.08)"/></svg>"""
