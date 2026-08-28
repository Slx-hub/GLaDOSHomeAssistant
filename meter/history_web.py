"""Read-only web UI for the 5-minute power history.

Separate process from meter.service on purpose: that service is the slow
correction path for the power controller and must not share a process with a
web server. This one opens the SQLite file read-only (WAL, so it never blocks
the recorder) and serves a single page plus a small JSON API.

    ./venv/bin/python history_web.py [--port 8086]
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, request, Response

import history
from meter_service import load_config

app = Flask(__name__)
DB_PATH = None
TZ = ZoneInfo("Europe/Berlin")


def db():
    if not os.path.exists(DB_PATH):
        return None
    return history.connect(DB_PATH, read_only=True)


@app.route("/api/days")
def api_days():
    conn = db()
    if conn is None:
        return jsonify({"days": []})
    try:
        return jsonify({"days": history.days_with_data(conn, TZ)})
    finally:
        conn.close()


@app.route("/api/day")
def api_day():
    date = request.args.get("date")
    if not date:
        return jsonify({"error": "date=YYYY-MM-DD required"}), 400
    conn = db()
    if conn is None:
        return jsonify({"date": date, "series": [], "summary": None})
    try:
        start, end = history.day_bounds_utc(date, TZ)
        # Hand the client the exact local-day window: it must not re-derive
        # midnight from a UTC timestamp (offset) or assume 86400s (DST days).
        return jsonify({"date": date, "start_ts": start, "end_ts": end,
                        "series": history.series(conn, start, end),
                        "summary": history.summary(conn, start, end)})
    except ValueError:
        return jsonify({"error": "bad date"}), 400
    finally:
        conn.close()


@app.route("/api/summary")
def api_summary():
    """No from/to -> summary over ALL available data (the default view)."""
    frm, to = request.args.get("from"), request.args.get("to")
    conn = db()
    if conn is None:
        return jsonify({"summary": None, "range": "none"})
    try:
        if frm and to:
            start, _ = history.day_bounds_utc(frm, TZ)
            _, end = history.day_bounds_utc(to, TZ)
            return jsonify({"summary": history.summary(conn, start, end),
                            "range": f"{frm} .. {to}"})
        return jsonify({"summary": history.summary(conn), "range": "all"})
    except ValueError:
        return jsonify({"error": "bad date"}), 400
    finally:
        conn.close()


@app.route("/")
def index():
    return Response(PAGE, mimetype="text/html")


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Power History</title>
<style>
  :root{--bg:#14161a;--panel:#1c1f26;--line:#2a2f3a;--fg:#e6e8ec;--dim:#9aa3b2;
        --accent:#5cc8ff;--accent2:#ffb454}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);
       font:14px/1.5 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
  header{padding:16px 20px;border-bottom:1px solid var(--line);display:flex;
         align-items:baseline;gap:14px;flex-wrap:wrap}
  h1{font-size:17px;margin:0;font-weight:650;letter-spacing:.2px}
  .sub{color:var(--dim);font-size:12px}
  main{padding:20px;max-width:1100px;margin:0 auto}
  .panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;
         padding:16px;margin-bottom:18px}
  .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
  button,select,input{background:#242833;color:var(--fg);border:1px solid var(--line);
         border-radius:7px;padding:7px 11px;font:inherit;cursor:pointer}
  button:hover:not(:disabled){border-color:var(--accent)}
  button:disabled{opacity:.4;cursor:default}
  .stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:12px;margin-top:6px}
  .stat{background:#20242e;border:1px solid var(--line);border-radius:8px;padding:10px 12px}
  .stat .k{color:var(--dim);font-size:11px;text-transform:uppercase;letter-spacing:.6px}
  .stat .v{font-size:19px;font-weight:600;margin-top:3px;font-variant-numeric:tabular-nums}
  .chartwrap{overflow-x:auto}
  svg{display:block}
  .empty{color:var(--dim);padding:26px 0;text-align:center}
  h2{font-size:13px;color:var(--dim);text-transform:uppercase;letter-spacing:.7px;
     margin:0 0 10px;font-weight:600}
  table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
  th,td{text-align:right;padding:5px 8px;border-bottom:1px solid var(--line)}
  th:first-child,td:first-child{text-align:left}
  th{color:var(--dim);font-weight:600;font-size:11px;text-transform:uppercase}
  tr.sel td{background:#26303a}
  td a{color:var(--accent);text-decoration:none}
</style></head><body>
<header><h1>Power History</h1>
  <span class="sub">5-minute averages · from the FRITZ!Box statistics buffer</span></header>
<main>
  <div class="panel">
    <h2>All data</h2>
    <div id="allstats" class="stats"></div>
  </div>

  <div class="panel">
    <h2>Period</h2>
    <div class="row">
      <label>from <input type="date" id="pfrom"></label>
      <label>to <input type="date" id="pto"></label>
      <button onclick="loadPeriod()">Average</button>
      <button onclick="clearPeriod()">Reset to all</button>
    </div>
    <div id="pstats" class="stats"></div>
  </div>

  <div class="panel">
    <h2>Day</h2>
    <div class="row">
      <button id="prev" onclick="step(-1)">&larr; Prev</button>
      <select id="daysel" onchange="loadDay(this.value)"></select>
      <button id="next" onclick="step(1)">Next &rarr;</button>
      <span class="sub" id="daymeta"></span>
    </div>
    <div class="chartwrap" id="chart"></div>
  </div>

  <div class="panel">
    <h2>Days</h2>
    <div id="daytable"></div>
  </div>
</main>
<script>
const fmt=(v,u)=>v==null?'&mdash;':v.toLocaleString(undefined,{maximumFractionDigits:1})+' '+u;
let DAYS=[],CUR=null;

function statBlock(el,s){
  if(!s||!s.buckets){el.innerHTML='<div class="empty">No data yet.</div>';return;}
  const f=new Date(s.first_ts*1000),l=new Date(s.last_ts*1000);
  el.innerHTML=[
    ['Average',fmt(s.avg_w,'W')],['Min',fmt(s.min_w,'W')],['Max',fmt(s.max_w,'W')],
    ['Energy',fmt(s.kwh,'kWh')],['Covered',fmt(s.covered_h,'h')],
    ['Range',f.toLocaleDateString()+' &ndash; '+l.toLocaleDateString()]
  ].map(([k,v])=>`<div class="stat"><div class="k">${k}</div><div class="v">${v}</div></div>`).join('');
}

function chart(series,startTs,endTs){
  const box=document.getElementById('chart');
  if(!series.length){box.innerHTML='<div class="empty">No data for this day.</div>';return;}
  const W=1040,H=260,padL=52,padR=12,padT=12,padB=28;
  const iw=W-padL-padR, ih=H-padT-padB;
  const maxW=Math.max(...series.map(p=>p.watt))*1.1||1;
  // x by time-of-day, using the server's local-day window so the axis is not
  // shifted by the UTC offset and DST-length days still span correctly.
  const t0=startTs, span=Math.max(1,endTs-startTs);
  const X=ts=>padL+((ts-t0)/span)*iw, Y=w=>padT+ih-(w/maxW)*ih;
  let d='',prev=null;
  for(const p of series){
    const x=X(p.ts),y=Y(p.watt);
    d += (prev===null||p.ts-prev>900?'M':'L')+x.toFixed(1)+' '+y.toFixed(1)+' ';
    prev=p.ts;
  }
  const yt=[0,.25,.5,.75,1].map(f=>Math.round(maxW*f));
  const grid=yt.map(v=>`<line x1="${padL}" x2="${W-padR}" y1="${Y(v)}" y2="${Y(v)}"
      stroke="#2a2f3a"/><text x="${padL-8}" y="${Y(v)+4}" fill="#9aa3b2"
      font-size="10" text-anchor="end">${v}</text>`).join('');
  const hours=Math.round(span/3600);
  const xt=[0,4,8,12,16,20,hours].filter((h,i,a)=>a.indexOf(h)===i&&h<=hours)
    .map(h=>{const x=X(t0+h*3600);
    return `<line x1="${x}" x2="${x}" y1="${padT}" y2="${padT+ih}" stroke="#22262f"/>
      <text x="${x}" y="${H-8}" fill="#9aa3b2" font-size="10" text-anchor="middle">${h}:00</text>`;}).join('');
  box.innerHTML=`<svg width="${W}" height="${H}" role="img" aria-label="power over the day">
    ${grid}${xt}<path d="${d}" fill="none" stroke="#5cc8ff" stroke-width="1.6"
    stroke-linejoin="round"/></svg>`;
}

async function loadAll(){
  const r=await (await fetch('/api/summary')).json();
  statBlock(document.getElementById('allstats'),r.summary);
  if(r.summary&&r.summary.first_ts){
    const a=new Date(r.summary.first_ts*1000),b=new Date(r.summary.last_ts*1000);
    const iso=d=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
    document.getElementById('pfrom').value=iso(a);
    document.getElementById('pto').value=iso(b);
  }
  statBlock(document.getElementById('pstats'),r.summary);
}
async function loadDays(){
  DAYS=(await (await fetch('/api/days')).json()).days;
  const sel=document.getElementById('daysel');
  sel.innerHTML=DAYS.map(d=>`<option value="${d.date}">${d.date}</option>`).join('');
  document.getElementById('daytable').innerHTML=DAYS.length?
    `<table><tr><th>Day</th><th>Average</th><th>Energy</th><th>Buckets</th></tr>`+
    DAYS.slice().reverse().map(d=>`<tr data-d="${d.date}"><td><a href="#"
      onclick="loadDay('${d.date}');return false">${d.date}</a></td>
      <td>${fmt(d.avg_w,'W')}</td><td>${fmt(d.kwh,'kWh')}</td><td>${d.buckets}</td></tr>`).join('')
    +`</table>`:'<div class="empty">No days recorded yet.</div>';
  if(DAYS.length) loadDay(DAYS[DAYS.length-1].date);
}
async function loadDay(date){
  CUR=date;
  document.getElementById('daysel').value=date;
  const r=await (await fetch('/api/day?date='+date)).json();
  chart(r.series||[], r.start_ts, r.end_ts);
  const s=r.summary;
  document.getElementById('daymeta').innerHTML = s&&s.buckets
    ? `avg ${fmt(s.avg_w,'W')} · min ${fmt(s.min_w,'W')} · max ${fmt(s.max_w,'W')} · ${fmt(s.kwh,'kWh')}`
    : '';
  const i=DAYS.findIndex(d=>d.date===date);
  document.getElementById('prev').disabled=(i<=0);
  document.getElementById('next').disabled=(i<0||i>=DAYS.length-1);
  document.querySelectorAll('#daytable tr').forEach(tr=>
    tr.classList.toggle('sel',tr.dataset.d===date));
}
function step(n){const i=DAYS.findIndex(d=>d.date===CUR);
  if(i>=0&&DAYS[i+n]) loadDay(DAYS[i+n].date);}
async function loadPeriod(){
  const f=document.getElementById('pfrom').value,t=document.getElementById('pto').value;
  if(!f||!t)return;
  const r=await (await fetch(`/api/summary?from=${f}&to=${t}`)).json();
  statBlock(document.getElementById('pstats'),r.summary);
}
async function clearPeriod(){
  const r=await (await fetch('/api/summary')).json();
  statBlock(document.getElementById('pstats'),r.summary);
}
loadAll();loadDays();
setInterval(()=>{loadAll();loadDays();},300000);
</script></body></html>"""


def main():
    global DB_PATH
    ap = argparse.ArgumentParser(description="Power history web UI")
    ap.add_argument("--config", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                     "config.yaml"))
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8086)
    args = ap.parse_args()
    cfg = load_config(args.config)
    DB_PATH = cfg["history"]["db_path"]
    print(f"history db: {DB_PATH}")
    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
