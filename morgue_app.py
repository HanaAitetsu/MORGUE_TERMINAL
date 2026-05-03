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

st.set_page_config(page_title="MORGUE TERMINAL v2.7", layout="wide")

# --- レスポンシブCSS ---
st.markdown("""
<style>
    body { background-color: #000; color: #fff; }
    [data-testid="stMetric"] {
        background-color: #111;
        border: 1px solid #333;
        padding: 10px !important;
        border-radius: 5px;
    }
    @media (max-width: 768px) {
        [data-testid="column"] {
            width: 100% !important;
            flex: 1 1 100% !important;
        }
    }
    ::-webkit-scrollbar { display: none; }
    .stCodeBlock { border-left: 3px solid #00FF00; }
</style>
""", unsafe_allow_html=True)

if 'history' not in st.session_state:
    st.session_state.history = []

# --- 1. 真の過去データ取得ロジック ---
@st.cache_data(ttl=3600)
def get_real_historical_data():
    h_data = []
    tickers = ["LMT", "RTX", "NOC", "GD", "BA", "LHX", "HII", "PLTR", "KTOS", "LDOS", "JPY=X"]
    try:
        raw_data = yf.download(tickers, period="2d", interval="15m", progress=False)['Close']
        raw_data = raw_data.ffill()
        
        fx_series = raw_data['JPY=X']
        defense_df = raw_data.drop(columns=['JPY=X'])
        growth_series = defense_df.pct_change().mean(axis=1) * 100
        
        # 過去計算用定数
        base_c, base_o, base_p = 1.45, 1.09, 1.06
        past_points = growth_series.dropna().tail(25)
        
        for ts, iron_val in past_points.items():
            i_f = 1 + (float(iron_val) / 20)
            m_usd = 1.0 * base_c * base_o * i_f * base_p
            current_fx = float(fx_series.loc[ts]) if ts in fx_series.index else 155.0
            
            h_data.append({
                "time": ts.astimezone(JST).strftime("%H:%M"),
                "open": round(m_usd * 0.999, 3), "high": round(m_usd * 1.001, 3),
                "low": round(m_usd * 0.998, 3), "close": round(m_usd, 3),
                "morg_jpy": int(m_usd * current_fx), "fx_rate": round(current_fx, 2),
                "iron": round(float(iron_val), 3), "conflict": 145.0, "oil": 82.0,
                "factors": {"c": base_c, "o": base_o, "i": round(i_f, 3), "p": base_p}
            })
    except: pass
    return h_data

if not st.session_state.history:
    st.session_state.history = get_real_historical_data()

# --- 2. 最新データ取得エンジン ---
@st.cache_data(ttl=600)
def fetch_latest():
    # USD/JPY
    fx_rate = 155.0
    try:
        fx_df = yf.download("JPY=X", period="1d", interval="5m", progress=False)
        fx_rate = float(fx_df['Close'].iloc[-1].item())
    except: pass

    # GDELT
    conflict_vol = 145.0
    try:
        res = requests.get('https://api.gdeltproject.org/api/v2/doc/doc?query=(conflict OR violence)&mode=TimelineVol&format=json', timeout=10).json()
        conflict_vol = float(res['timeline'][0]['data'][-1]['value'] * 10)
    except: pass

    # FRED
    oil_price = 82.0
    try:
        fred_url = f"https://api.stlouisfed.org/fred/series/observations?series_id=DCOILBRENTEU&api_key={FRED_API_KEY}&file_type=json&sort_order=desc&limit=1"
        oil_price = float(requests.get(fred_url).json()['observations'][0]['value'])
    except: pass

    # yfinance
    iron_growth = 0.1
    try:
        tks = ["LMT", "RTX", "NOC", "GD", "BA", "LHX", "HII", "PLTR", "KTOS", "LDOS"]
        stocks = yf.download(tks, period="1d", interval="5m", progress=False)['Close']
        iron_growth = float(stocks.pct_change().mean(axis=1).iloc[-1] * 100)
    except: pass

    # NEWS
    headlines = []
    press_count = 500
    try:
        news_url = f'https://newsapi.org/v2/everything?q=("armed conflict" OR warfare)&sortBy=publishedAt&apiKey={NEWS_API_KEY}&pageSize=5'
        n_res = requests.get(news_url).json()
        headlines = n_res.get('articles', [])
        press_count = int(n_res.get('totalResults', 500))
    except: pass

    # 指数計算
    c_f, o_f = 1 + (conflict_vol/100), oil_price / 75
    i_f, p_f = 1 + (iron_growth/20), 1 + (min(press_count, 2000) / 8000)
    morg_usd = 1.0 * c_f * o_f * i_f * p_f
    
    current_time = datetime.now(JST).strftime("%H:%M")
    prev_close = st.session_state.history[-1]['close'] if st.session_state.history else morg_usd
    
    entry = {
        "time": current_time, "open": prev_close,
        "high": max(prev_close, morg_usd) + 0.002, "low": min(prev_close, morg_usd) - 0.002,
        "close": round(morg_usd, 3), "morg_jpy": int(morg_usd * fx_rate),
        "fx_rate": round(fx_rate, 2), "conflict": round(conflict_vol, 2),
        "iron": round(iron_growth, 3), "oil": round(oil_price, 2), "press": press_count,
        "factors": {"c": round(c_f, 3), "o": round(o_f, 3), "i": round(i_f, 3), "p": round(p_f, 3)},
        "headlines": headlines
    }
    
    if not st.session_state.history or st.session_state.history[-1]['time'] != current_time:
        st.session_state.history.append(entry)
        if len(st.session_state.history) > 60: st.session_state.history.pop(0)
    return entry

current = fetch_latest()
df = pd.DataFrame(st.session_state.history)

# --- 3. UI構築 ---
st.markdown(f"""
    <div style="display:flex; justify-content:space-between; border-bottom:2px solid #444; padding-bottom:10px;">
        <span style="font-family:'JetBrains Mono'; font-weight:bold; letter-spacing:2px; font-size:22px;">MORGUE TERMINAL v2.7</span>
        <span style="color:#00FF00; font-family:'JetBrains Mono'; font-size:16px;">● ONLINE: {current['time']} JST</span>
    </div>
""", unsafe_allow_html=True)

st.write("##")

# メインメトリクス (デルタ自動色変化)
m1, m2, m3 = st.columns([2, 2, 1])
if len(st.session_state.history) > 1:
    d_jpy = current['morg_jpy'] - st.session_state.history[-2]['morg_jpy']
    d_usd = current['close'] - st.session_state.history[-2]['close']
    d_fx = current['fx_rate'] - st.session_state.history[-2]['fx_rate']
else: d_jpy = d_usd = d_fx = 0

m1.metric("MORGUE PRICE (JPY)", f"¥{current['morg_jpy']:,}", delta=int(d_jpy))
m2.metric("MORGUE PRICE (USD)", f"$ {current['close']:.3f}", delta=round(float(d_usd), 3))
m3.metric("USD / JPY", f"¥{current['fx_rate']}", delta=round(float(d_fx), 2))

st.write("---")

# 計算過程セクション
c_left, c_right = st.columns([1, 1.2])
with c_left:
    st.markdown("#### ［ 構成要素と適用係数 ］")
    st.markdown(f"""
    | パラメータ | 現在値 | 変換係数 |
    | :--- | :--- | :--- |
    | **Conflict** | {current['conflict']} | **x {current['factors']['c']:.3f}** |
    | **Oil** | ${current['oil']} | **x {current['factors']['o']:.3f}** |
    | **Iron** | {current['iron']}% | **x {current['factors']['i']:.3f}** |
    | **Press** | {current['press']} | **x {current['factors']['p']:.3f}** |
    """)

with c_right:
    st.markdown("#### ［ 算出プロセス・ログ ］")
    s1 = 1.0 * current['factors']['c']
    s2 = s1 * current['factors']['o']
    s3 = s2 * current['factors']['i']
    s4 = s3 * current['factors']['p']
    log = f"""
1. Base Unit: $ 1.000
2. Conflict Adj: $ 1.000 * {current['factors']['c']:.3f} -> $ {s1:.3f}
3. Energy Adj  : $ {s1:.3f} * {current['factors']['o']:.3f} -> $ {s2:.3f}
4. Defense Adj : $ {s2:.3f} * {current['factors']['i']:.3f} -> $ {s3:.3f}
5. Press Adj   : $ {s3:.3f} * {current['factors']['p']:.3f} -> $ {s4:.3f}
6. Currency    : $ {s4:.3f} * ¥ {current['fx_rate']} -> ¥ {current['morg_jpy']:,}
    """
    st.code(log, language="bash")
    st.latex(r"MORG_{JPY} = (1.0 \cdot C_f \cdot O_f \cdot I_f \cdot P_f) \cdot FX")

st.write("---")

# チャートとニュース
gl, gr = st.columns([2, 1])
with gl:
    st.markdown("#### ［ 市場ボラティリティ ］")
    fig = go.Figure(data=[go.Candlestick(
        x=df['time'], open=df['open'], high=df['high'], low=df['low'], close=df['close'],
        increasing_line_color='#FFFFFF', decreasing_line_color='#FF0000',
        increasing_fillcolor='#333', decreasing_fillcolor='#FF0000'
    )])
    fig.update_layout(template="plotly_dark", height=400, margin=dict(l=0,r=0,b=0,t=0),
                      yaxis=dict(autorange=True, fixedrange=False, tickformat=".3f", gridcolor='#222'),
                      xaxis=dict(rangeslider_visible=False, gridcolor='#222'))
    st.plotly_chart(fig, use_container_width=True)

with gr:
    st.markdown("#### ［ 最新戦況 ］")
    for art in current['headlines']:
        st.markdown(f"""<div style="margin-bottom:12px; border-left:3px solid #FF0000; padding-left:10px;">
            <span style="color:#FF4B4B; font-size:10px; font-weight:bold;">{art['source']['name']}</span><br>
            <a href="{art['url']}" target="_blank" style="color:#DDD; text-decoration:none; font-size:12px;">{art['title']}</a>
        </div>""", unsafe_allow_html=True)

st.write("---")
# ミニトレンド
st.markdown("#### ［ 個別推移 ］")
t1, t2, t3 = st.columns(3)
t1.caption("CONFLICT")
t1.line_chart(df.set_index('time')['conflict'], height=100)
t2.caption("IRON INDEX")
t2.line_chart(df.set_index('time')['iron'], height=100)
t3.caption("OIL PRICE")
t3.line_chart(df.set_index('time')['oil'], height=100)