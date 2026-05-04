import streamlit as st
import pandas as pd
import yfinance as yf
import requests
import plotly.graph_objects as go
import numpy as np
import os
from datetime import datetime, timedelta, timezone

# --- システム設定 ---
JST = timezone(timedelta(hours=9))
FRED_API_KEY = os.environ.get("FRED_API_KEY")
NEWS_API_KEY = os.environ.get("NEWS_API_KEY")

st.set_page_config(page_title="MORGUE TERMINAL MRG-v2.8", layout="wide")

# CSS
st.markdown("""
<style>
    body { background-color: #000; color: #fff; }
    [data-testid="stMetric"] { background-color: #111; border: 1px solid #333; padding: 10px !important; }
    @media (max-width: 768px) { [data-testid="column"] { width: 100% !important; flex: 1 1 100% !important; } }
    ::-webkit-scrollbar { display: none; }
</style>
""", unsafe_allow_html=True)

# --- A. 共通計算ロジック ---
def calculate_mrg(c, o, i, p):
    # c:Conflict, o:Oil, i:Iron(%), p:PressFactor
    c_f = 1 + (c / 100)
    o_f = o / 75
    i_f = 1 + (i / 20)
    return 1.0 * c_f * o_f * i_f * p

# --- B. 過去データと最新値の同期取得 ---
@st.cache_data(ttl=600)
def get_synchronized_data():
    # 1. 現在の外部環境（C, O, P）を取得してベースラインにする
    c_val = 145.0
    try:
        res = requests.get('https://api.gdeltproject.org/api/v2/doc/doc?query=(conflict OR violence)&mode=TimelineVol&format=json', timeout=10).json()
        c_val = float(res['timeline'][0]['data'][-1]['value'] * 10)
    except: pass

    o_val = 82.0
    try:
        fred_url = f"https://api.stlouisfed.org/fred/series/observations?series_id=DCOILBRENTEU&api_key={FRED_API_KEY}&file_type=json&sort_order=desc&limit=1"
        o_val = float(requests.get(fred_url).json()['observations'][0]['value'])
    except: pass
    
    p_f = 1.06 # デフォルト報道係数

    # 2. 市場履歴の一括取得 (yfinance)
    tickers = ["LMT", "RTX", "NOC", "GD", "BA", "LHX", "HII", "PLTR", "KTOS", "LDOS", "JPY=X"]
    raw = yf.download(tickers, period="2d", interval="15m", progress=False)['Close'].ffill()
    
    fx_series = raw['JPY=X']
    defense_df = raw.drop(columns=['JPY=X'])
    # 騰落率の履歴
    growth_series = defense_df.pct_change().mean(axis=1) * 100
    
    # 3. 過去履歴の構築
    h_list = []
    points = growth_series.dropna().tail(40) # 直近40ポイント
    
    for ts, i_val in points.items():
        m_usd = calculate_mrg(c_val, o_val, float(i_val), p_f)
        fx = float(fx_series.loc[ts]) if ts in fx_series.index else 155.0
        
        h_list.append({
            "time": ts.astimezone(JST).strftime("%H:%M"),
            "open": round(m_usd * 0.999, 3), "high": round(m_usd * 1.001, 3),
            "low": round(m_usd * 0.998, 3), "close": round(m_usd, 3),
            "morg_jpy": int(m_usd * fx), "fx_rate": round(fx, 2),
            "iron": round(float(i_val), 3), "conflict": round(c_val, 2), "oil": round(o_val, 2),
            "factors": {"c": round(1+c_val/100,3), "o": round(o_val/75,3), "i": round(1+float(i_val)/20,3), "p": p_f}
        })
    return h_list

# セッション管理
if 'history' not in st.session_state or not st.session_state.history:
    st.session_state.history = get_synchronized_data()

# 最新1件を取得して末尾に追加（重複チェック付）
latest_sync = get_synchronized_data()
if latest_sync:
    latest_entry = latest_sync[-1]
    if st.session_state.history[-1]['time'] != latest_entry['time']:
        st.session_state.history.append(latest_entry)
        if len(st.session_state.history) > 100: st.session_state.history.pop(0)

current = st.session_state.history[-1]
df = pd.DataFrame(st.session_state.history)

# --- 3. UI ---
st.markdown(f"""
    <div style="display:flex; justify-content:space-between; border-bottom:2px solid #444; padding-bottom:10px;">
        <span style="font-family:'JetBrains Mono'; font-weight:bold; letter-spacing:2px; font-size:22px;">MORGUE TERMINAL MRG-v2.8</span>
        <span style="color:#00FF00; font-family:'JetBrains Mono'; font-size:16px;">● LIVE: {current['time']} JST</span>
    </div>
""", unsafe_allow_html=True)

st.write("##")

# アップダウン計算（履歴の最後から2番目と比較）
m1, m2, m3 = st.columns([2, 2, 1])
if len(st.session_state.history) > 1:
    prev = st.session_state.history[-2]
    d_jpy = current['morg_jpy'] - prev['morg_jpy']
    d_usd = current['close'] - prev['close']
    d_fx = current['fx_rate'] - prev['fx_rate']
else: d_jpy = d_usd = d_fx = 0

m1.metric("MRG/JPY", f"¥{current['morg_jpy']:,}", delta=int(d_jpy))
m2.metric("MRG/USD", f"$ {current['close']:.3f}", delta=round(float(d_usd), 3))
m3.metric("USD/JPY", f"¥{current['fx_rate']}", delta=round(float(d_fx), 2))

st.write("---")

# 計算プロセス
cl, cr = st.columns([1, 1.2])
with cl:
    st.markdown("#### ［ MRG構成要素 ］")
    st.markdown(f"| パラメータ | 値 | 係数 |\n| :--- | :--- | :--- |\n"
                f"| **Conflict** | {current['conflict']} | **x {current['factors']['c']}** |\n"
                f"| **Energy** | ${current['oil']} | **x {current['factors']['o']}** |\n"
                f"| **Defense** | {current['iron']}% | **x {current['factors']['i']}** |\n"
                f"| **Press** | API連携 | **x {current['factors']['p']}** |")
with cr:
    st.markdown("#### ［ 算出プロセス ］")
    s1 = 1.0 * current['factors']['c']
    s2 = s1 * current['factors']['o']
    s3 = s2 * current['factors']['i']
    s4 = s3 * current['factors']['p']
    log = f"1. Base Unit: $ 1.000\n2. Conflict Adj: $ {s1:.3f}\n3. Energy Adj: $ {s2:.3f}\n4. Defense Adj: $ {s3:.3f}\n5. Final MRG(USD): $ {s4:.3f}\n6. JPY Convert: ¥ {current['morg_jpy']:,}"
    st.code(log, language="bash")

st.write("---")

# チャート
gl, gr = st.columns([2, 1])
with gl:
    st.markdown("#### ［ MRG市場ボラティリティ ］")
    fig = go.Figure(data=[go.Candlestick(
        x=df['time'], open=df['open'], high=df['high'], low=df['low'], close=df['close'],
        increasing_line_color='#FFFFFF', decreasing_line_color='#FF0000',
        increasing_fillcolor='#333', decreasing_fillcolor='#FF0000'
    )])
    fig.update_layout(template="plotly_dark", height=450, margin=dict(l=0,r=0,b=0,t=0),
                      yaxis=dict(autorange=True, fixedrange=False, tickformat=".3f", gridcolor='#222'),
                      xaxis=dict(rangeslider_visible=False, gridcolor='#222'))
    st.plotly_chart(fig, use_container_width=True)

with gr:
    st.markdown("#### ［ 個別推移 ］")
    st.caption("CONFLICT INDEX")
    st.line_chart(df.set_index('time')['conflict'], height=100)
    st.caption("IRON (DEFENSE) %")
    st.line_chart(df.set_index('time')['iron'], height=100)
    st.caption("OIL PRICE")
    st.line_chart(df.set_index('time')['oil'], height=100)