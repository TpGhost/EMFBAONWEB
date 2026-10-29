"""EMFBA Football Analytics V1 — free-tier, read-only, no Telegram.

API-Football: https://v3.football.api-sports.io
football-data.org: https://api.football-data.org/v4
All probabilities are experimental, NOT calibrated investment recommendations.
"""
import math
import os
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import requests
import streamlit as st
from scipy.stats import poisson

st.set_page_config(page_title="EMFBA Football Analytics", page_icon="⚽", layout="wide")
THAI = timezone(timedelta(hours=7))
TODAY = datetime.now(THAI).date()

st.markdown("""<style>
.block-container{padding-top:1.6rem;max-width:1250px}
[data-testid="stMetric"]{border:1px solid #d5e3da;border-radius:12px;padding:12px}
.small-note{color:#6c7b72;font-size:0.9rem}
</style>""", unsafe_allow_html=True)


def secret(name):
    try:
        return st.secrets.get(name, os.environ.get(name, ""))
    except Exception:
        return os.environ.get(name, "")


@st.cache_data(ttl=3600, show_spinner=False)
def api_football(path, params, key):
    if not key:
        return None, "ยังไม่ได้ตั้ง API_FOOTBALL_KEY"
    try:
        r = requests.get("https://v3.football.api-sports.io/" + path,
                         params=dict(params), headers={"x-apisports-key": key}, timeout=15)
        r.raise_for_status()
        obj = r.json()
        if obj.get("errors"):
            return None, str(obj["errors"])
        return obj.get("response", []), None
    except (requests.RequestException, ValueError) as exc:
        return None, str(exc)


@st.cache_data(ttl=3600, show_spinner=False)
def football_data(path, params, key):
    if not key:
        return None, "ยังไม่ได้ตั้ง FOOTBALL_DATA_KEY"
    try:
        r = requests.get("https://api.football-data.org/v4/" + path,
                         params=dict(params), headers={"X-Auth-Token": key}, timeout=15)
        r.raise_for_status()
        return r.json(), None
    except (requests.RequestException, ValueError) as exc:
        return None, str(exc)


def parse_kickoff(iso):
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(THAI)
    except (AttributeError, ValueError):
        return None


def api_fixtures(day, key):
    raw, err = api_football("fixtures", (("date", day.isoformat()), ("timezone", "Asia/Bangkok")), key)
    if err:
        return [], err
    games = []
    for x in raw or []:
        fixture, teams, league = x.get("fixture", {}), x.get("teams", {}), x.get("league", {})
        dt = parse_kickoff(fixture.get("date", ""))
        if not dt or dt.date() != day:
            continue
        home, away = teams.get("home", {}), teams.get("away", {})
        games.append({"id": f"api:{fixture.get('id')}", "api_id": fixture.get("id"),
                      "date": dt, "league": league.get("name", "Unknown"),
                      "home": home.get("name", "?"), "away": away.get("name", "?"),
                      "home_id": home.get("id"), "away_id": away.get("id"),
                      "status": fixture.get("status", {}).get("short", ""), "source": "API-Football"})
    return games, None


def fd_fixtures(day, key):
    # Only use competitions actually accessible under the user's football-data.org plan.
    raw, err = football_data("matches", (("dateFrom", day.isoformat()), ("dateTo", day.isoformat())), key)
    if err:
        return [], err
    games = []
    for x in (raw or {}).get("matches", []):
        dt = parse_kickoff(x.get("utcDate", ""))
        if not dt or dt.date() != day:
            continue
        home, away = x.get("homeTeam", {}), x.get("awayTeam", {})
        games.append({"id": f"fd:{x.get('id')}", "api_id": None, "date": dt,
                      "league": x.get("competition", {}).get("name", "Unknown"),
                      "home": home.get("shortName") or home.get("name", "?"),
                      "away": away.get("shortName") or away.get("name", "?"),
                      "home_id": None, "away_id": None, "status": x.get("status", ""),
                      "source": "football-data.org"})
    return games, None


@st.cache_data(ttl=6*3600, show_spinner=False)
def team_history(team_id, key):
    # Fetch up to 12 finished games; can be unavailable under free-tier coverage.
    raw, err = api_football("fixtures", (("team", str(team_id)), ("last", "12"), ("status", "FT")), key)
    if err:
        # Some API plans do not accept combining 'last' and 'status'.
        raw, err = api_football("fixtures", (("team", str(team_id)), ("last", "12")), key)
    if err:
        return [], err
    out = []
    for x in raw or []:
        t = x.get("teams", {})
        g = x.get("goals", {})
        h, a = t.get("home", {}), t.get("away", {})
        gh, ga = g.get("home"), g.get("away")
        if gh is None or ga is None or x.get("fixture", {}).get("status", {}).get("short") not in ("FT", "AET", "PEN"):
            continue
        if h.get("id") == team_id:
            scored, conceded, venue = gh, ga, "H"
        elif a.get("id") == team_id:
            scored, conceded, venue = ga, gh, "A"
        else:
            continue
        out.append({"scored": int(scored), "conceded": int(conceded), "venue": venue,
                    "opponent": a.get("name") if venue == "H" else h.get("name"),
                    "date": x.get("fixture", {}).get("date", "")[:10]})
    return out, None


def goals_model(home_hist, away_hist):
    if len(home_hist) < 5 or len(away_hist) < 5:
        return None
    def avg(rows, k):
        return float(np.mean([r[k] for r in rows[-10:]]))
    # Conservative shrinkage toward a neutral baseline, not league-calibrated.
    hs = avg(home_hist, "scored"); hc = avg(home_hist, "conceded")
    aws = avg(away_hist, "scored"); awc = avg(away_hist, "conceded")
    lh = float(np.clip(0.55*1.45 + 0.45*(hs+awc)/2, 0.35, 3.1))
    la = float(np.clip(0.55*1.15 + 0.45*(aws+hc)/2, 0.35, 3.1))
    return lh, la


def score_probs(lh, la):
    goals = np.arange(13)
    mat = np.outer(poisson.pmf(goals, lh), poisson.pmf(goals, la))
    mat /= mat.sum()
    h, a = np.indices(mat.shape)
    return {"Over 2.5": float(mat[h+a >= 3].sum()),
            "Under 2.5": float(mat[h+a <= 2].sum()),
            "Home +0.5": float(mat[h >= a].sum()),
            "Away +0.5": float(mat[a >= h].sum())}


def evaluate(game, key):
    if not game.get("home_id") or not game.get("away_id"):
        return None, "ไม่พบ Team ID จาก API-Football"
    hh, he = team_history(int(game["home_id"]), key)
    ah, ae = team_history(int(game["away_id"]), key)
    if he or ae:
        return None, he or ae
    model = goals_model(hh, ah)
    if not model:
        return None, "ประวัติผลแข่งขันไม่พอ (ต้องมีอย่างน้อยทีมละ 5 นัด)"
    lh, la = model
    picks = score_probs(lh, la)
    best = max(picks, key=picks.get)
    # Ranking by probability alone is NOT EV or betting value.
    return {"pick": best, "prob": picks[best], "fair": 1/picks[best],
            "lh": lh, "la": la, "all": picks, "home_hist": hh, "away_hist": ah}, None


st.title("⚽ EMFBA Football Analytics")
st.caption("Web V1 • Free-tier friendly • เวลาไทย (ICT) • ไม่เชื่อม Telegram หรือ Apps Script")
st.warning("โมเดล V1 เป็นการประมาณเบื้องต้น ยังไม่ผ่านการทดสอบ Calibration / ROI; ไม่มีราคาตลาดจริงจึงยังคำนวณ EV หรือจัดอันดับ Value ไม่ได้")

key_api = secret("API_FOOTBALL_KEY")
key_fd = secret("FOOTBALL_DATA_KEY")
if not key_api and not key_fd:
    st.error("ยังไม่ได้ตั้งค่า API Keys ใน Streamlit Secrets — ดู README.md")
    st.stop()

with st.sidebar:
    st.header("ตั้งค่าการแสดงผล")
    source = st.selectbox("แหล่งโปรแกรมแข่งขัน", ["API-Football", "football-data.org"],
                          index=0 if key_api else 1)
    day = st.date_input("วันที่แข่งขัน (เวลาไทย)", value=TODAY)
    st.caption("Cache โปรแกรม 60 นาที / ประวัติทีม 6 ชั่วโมง เพื่อลดโควตาฟรี")
    st.caption("เมื่อข้อมูลหมดโควตาหรือไม่มีสิทธิ์เข้าถึง ระบบจะแสดงข้อความจริง ไม่สร้างข้อมูลสมมติ")

@st.cache_data(ttl=3600, show_spinner=False)
def get_day(day, source, key_api, key_fd):
    if source == "API-Football":
        return api_fixtures(day, key_api)
    # football-data.org filters by UTC date, may miss early ICT games.
    return fd_fixtures(day, key_fd)

with st.spinner("กำลังโหลดโปรแกรมการแข่งขัน..."):
    games, err = get_day(day, source, key_api, key_fd)
if err:
    st.error("ดึงข้อมูลไม่ได้: " + err)
    games = []

c1, c2, c3 = st.columns(3)
c1.metric("แมตช์ที่พบ", len(games))
c2.metric("ทีมในโปรแกรม", len(set([t for g in games for t in (g['home'],g['away'])])))
c3.metric("โมเดล", "Experimental")

tab1, tab2, tab3 = st.tabs(["🏆 Dashboard TOP 10", "🔎 Team Search", "📊 Prediction Audit"])
with tab1:
    st.subheader("TOP 10 — Model Probability (ยังไม่ใช่ EV)")
    st.caption("กดวิเคราะห์เพื่อประหยัด API ฟรี: ระบบประเมินเฉพาะแมตช์ที่มี Team ID และข้อมูลย้อนหลัง")
    leagues = sorted({g["league"] for g in games})
    selected = st.multiselect("เลือกลีก", leagues, default=leagues[:10] if len(leagues)>10 else leagues)
    filtered = [g for g in games if g["league"] in selected]
    st.write(f"พบ {len(filtered)} คู่ในลีกที่เลือก")
    if st.button("วิเคราะห์ TOP 10", type="primary", disabled=not key_api):
        if source != "API-Football":
            st.info("โปรแกรมจาก football-data.org ไม่มี API-Football Team ID — โปรดเลือก API-Football เพื่อใช้โมเดล V1")
        else:
            # Strict cap to protect 100 requests/day free-tier; 2 history requests per match.
            limit = min(10, len(filtered))
            st.info(f"ทดลองวิเคราะห์สูงสุด {limit} คู่แรกตามเวลา (สูงสุดประมาณ {2*limit} คำขอประวัติทีมก่อน Cache)")
            ranked, failures = [], []
            with st.spinner("กำลังคำนวณ..."):
                for g in sorted(filtered, key=lambda x:x["date"])[:limit]:
                    prediction, error = evaluate(g, key_api)
                    if error:
                        failures.append(f"{g['home']} – {g['away']}: {error}")
                        continue
                    ranked.append({"เวลาไทย":g["date"].strftime("%d/%m %H:%M"), "ลีก":g["league"],
                                   "คู่แข่งขัน":f"{g['home']} vs {g['away']}",
                                   "คำแนะนำโมเดล":prediction["pick"],
                                   "Model Prob":f"{prediction['prob']*100:.1f}%",
                                   "Fair Odds":round(prediction["fair"],2),
                                   "EV":"ไม่มีราคาตลาด", "_prob":prediction["prob"]})
            if ranked:
                frame = pd.DataFrame(ranked).sort_values("_prob", ascending=False).head(10)
                st.dataframe(frame.drop(columns="_prob"), hide_index=True, use_container_width=True)
                st.caption("อันดับเรียงตาม Model Probability ไม่ใช่ความคุ้มค่าเดิมพัน; 1 ตลาดต่อแมตช์")
            else:
                st.info("ยังไม่มีคู่ที่ประเมินได้จากข้อมูลที่ API ส่งกลับ")
            if failures:
                with st.expander(f"คู่ที่ยังวิเคราะห์ไม่ได้ ({len(failures)})"):
                    for f in failures: st.write("• " + f)
    st.divider()
    st.subheader("โปรแกรมการแข่งขัน")
    if games:
        st.dataframe(pd.DataFrame([{"เวลาไทย":g["date"].strftime("%d/%m %H:%M"),
                                   "ลีก":g["league"], "เหย้า":g["home"], "เยือน":g["away"],
                                   "สถานะ":g["status"], "แหล่ง":g["source"]} for g in filtered]),
                     hide_index=True, use_container_width=True)
    else:
        st.info("ไม่พบโปรแกรมสำหรับวันและแหล่งข้อมูลที่เลือก")

with tab2:
    st.subheader("ค้นหาทีม")
    query = st.text_input("ชื่อทีม", placeholder="Arsenal, Liverpool, Barcelona ...")
    if query.strip() and key_api:
        teams, team_err = api_football("teams", (("search", query.strip()),), key_api)
        if team_err:
            st.error(team_err)
        elif not teams:
            st.info("ไม่พบทีม")
        else:
            names = [f"{x['team']['name']} · {x['team'].get('country','')} · ID {x['team']['id']}" for x in teams]
            idx = st.selectbox("เลือกทีม", range(len(names)), format_func=lambda i:names[i])
            team = teams[idx]["team"]
            st.markdown(f"### {team['name']}")
            st.write(f"ประเทศ: {team.get('country','—')} | ก่อตั้ง: {team.get('founded','—')}")
            if team.get("logo"):
                st.image(team["logo"], width=80)
            history, h_err = team_history(int(team["id"]), key_api)
            if h_err:
                st.warning("ข้อมูลย้อนหลัง: " + h_err)
            elif history:
                last5 = history[-5:]
                wins = sum(x['scored']>x['conceded'] for x in last5)
                draws = sum(x['scored']==x['conceded'] for x in last5)
                losses = len(last5)-wins-draws
                a,b,c = st.columns(3)
                a.metric("ชนะ 5 นัดล่าสุด", wins); b.metric("เสมอ",draws); c.metric("แพ้",losses)
                st.dataframe(pd.DataFrame(history[::-1]).rename(columns={"scored":"ยิง", "conceded":"เสีย", "venue":"เหย้า/เยือน", "opponent":"คู่แข่ง", "date":"วันที่"}),hide_index=True,use_container_width=True)
            else:
                st.info("ยังไม่มีข้อมูลผลย้อนหลังเพียงพอ")
            st.markdown("#### โปรแกรมและคำแนะนำของทีม")
            matching = [g for g in games if (g.get("home_id") == team["id"] or g.get("away_id") == team["id"])]
            if not matching:
                st.info("ไม่มีเกมของทีมนี้ในวันที่เลือก ลองเปลี่ยนวันที่ด้านซ้าย")
            for g in matching:
                st.write(f"**{g['home']} vs {g['away']}** · {g['date'].strftime('%d/%m %H:%M')} · {g['league']}")
                if st.button("วิเคราะห์คู่นี้", key="team_"+g["id"]):
                    p, e = evaluate(g, key_api)
                    if e: st.warning(e)
                    else:
                        st.write(f"แนวโน้ม: **{p['pick']}** · Probability **{p['prob']*100:.1f}%** · Fair Odds **{p['fair']:.2f}**")
                        st.caption("ยังไม่มีราคาตลาดจริง จึงไม่ใช่คำแนะนำว่าคุ้มค่าเดิมพัน")
    elif query.strip():
        st.info("ต้องตั้ง API_FOOTBALL_KEY เพื่อค้นหาทีม")

with tab3:
    st.subheader("Prediction Audit")
    st.info("V1 ยังไม่บันทึกคำทำนายหรือผลแข่งขันถาวร เพื่อไม่ให้ข้อมูลหายเมื่อโฮสต์ฟรีรีสตาร์ตหรือทำให้เข้าใจผิดว่าเป็น Backtest จริง")
    st.write("เวอร์ชันต่อไปจะเพิ่มฐานข้อมูลถาวรที่ใช้แผนฟรี และเก็บคำทำนายก่อนแข่งพร้อมเวลา ราคา (ถ้ามี) และผลจริง")
    st.metric("Verified Settled Predictions", "—")
    st.metric("Verified ROI", "—")

st.divider()
st.caption("Data: API-Football / football-data.org ตามแผนที่ใช้งาน • ราคาตลาด AH/O-U ยังไม่ได้เชื่อม • ไม่ใช่คำแนะนำทางการเงิน")
