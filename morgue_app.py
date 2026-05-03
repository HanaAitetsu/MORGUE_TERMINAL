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

st.set_page_config(page_title="MORGUE TERMINAL v2.5", layout="wide")

# --- モバイル対応用カスタムCSS ---
st.markdown("""
<style>
    /* 全体背景とフォント */
    body { background-color: #000; color: #fff; }
    
    /* 指数メトリクスの調整（モバイルで横幅が足りない場合、自動で折り返す） */
    [data-testid="stMetric"] {
        background-color: #111;
        border: 1px solid #333;
        padding: 10px !important;
        border-radius: 5px;
    }

    /* iPhone/iPad用のレスポンシブ設定 */
    @media (max-width: 768px) {
        [data-testid="column"] {
            width: 100% !important;
            flex: 1 1 100% !important;
        }
        .stMetric {
            margin-bottom: 10px;
        }
    }
    
    /* スクロールバーの非表示（ターミナル感） */
    ::-webkit-scrollbar { display: none; }
</style>
""", unsafe_allow_html=True)

if 'history' not in st.session_state:
    st.session_state.history = []

# --- 過去データの初期生成（ランダムウォークでチャート崩れを防止） ---
@st.cache_data(ttl=3600)
def get_initial_history():
    h_data = []
    base_time = datetime.now(JST)
    current_price = 1.250
    for i in range(30):
        t = (base_time - timedelta(minutes=10*(30-i))).strftime("%H:%M")
        # ランダムウォークによるボラティリティ生成
        volatility = np.random.uniform(-0.015, 0.015)
        open_p = current_price
        close_p = open_p + volatility
        high_p = max(open_p, close_p) + np.random.uniform(0, 0.005)
        low_p = min(open_p, close_p) - np.random.uniform(0, 0.005)
        
        h_data.append({
            "time": t, "open": round(open_p, 3), "high": round(high_p, 3),
            "low": round(low_p, 3), "close": round(close_p, 3),
            "iron": round(np.random.uniform(-0.8, 0.8), 2),
            "conflict": round(140.0 + np.random.uniform(-8, 8), 1),
            "oil": round(80.0 + np.random.uniform(-3, 3), 2),
            "morg_jpy": int(close_p * 155), "fx_rate": 155.0
        })
        current_price = close_p
    return h_data

if not st.session_state.history:
    st.session_state.history = get_initial_history()

# --- データ取得エンジン ---
@st.cache_data(ttl=600)
def fetch_latest():
    # USD/JPY
    fx_rate = 155.0
    try:
        fx_df = yf.download("JPY=X", period="1d", interval="5m", progress=False)
        fx_rate = float(fx_df['Close'].iloc[-1].item())
    except: pass

    # 混乱度 (GDELT)
    conflict_vol = 145.0
    try:
        res = requests.get('https://api.gdeltproject.org/api/v2/doc/doc?query=(conflict OR violence)&mode=TimelineVol&format=json', timeout=10).json()
        conflict_vol = float(res['timeline'][0]['data'][-1]['value'] * 10)
    except: pass

    # 原油 (FRED)
    oil_price = 82.0
    try:
        fred_url = f"https://api.stlouisfed.org/fred/series/observations?series_id=DCOILBRENTEU&api_key={FRED_API_KEY}&file_type=json&sort_order=desc&limit=1"
        oil_price = float(requests.get(fred_url).json()['observations'][0]['value'])
    except: pass

    # 軍需株 (10銘柄)
    iron_growth = 0.1
    try:
        tickers = ["LMT", "RTX", "NOC", "GD", "BA", "LHX", "HII", "PLTR", "KTOS", "LDOS"]
        stocks = yf.download(tickers, period="1d", interval="5m", progress=False)['Close']
        iron_growth = float(stocks.pct_change().mean(axis=1).iloc[-1] * 100)
    except: pass

    # ニュース
    press_count = 500
    headlines = []
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
    prev_close = st.session_state.history[-1]['close']
    
    entry = {
        "time": current_time, "open": prev_close,
        "high": max(prev_close, morg_usd) + 0.003,
        "low": min(prev_close, morg_usd) - 0.003,
        "close": round(morg_usd, 3), "morg_jpy": int(morg_usd * fx_rate),
        "fx_rate": round(fx_rate, 2), "conflict": round(conflict_vol, 2),
        "iron": round(iron_growth, 3), "oil": round(oil_price, 2), "press": press_count,
        "factors": {"c": round(c_f, 3), "o": round(o_f, 3), "i": round(i_f, 3), "p": round(p_f, 3)},
        "headlines": headlines
    }
    
    if st.session_state.history[-1]['time'] != current_time:
        st.session_state.history.append(entry)
        if len(st.session_state.history) > 50: st.session_state.history.pop(0)
    return entry

current = fetch_latest()
df = pd.DataFrame(st.session_state.history)

# --- 画面表示 ---
st.markdown(f"""
    <div style="display:flex; justify-content:space-between; border-bottom:2px solid #444; padding-bottom:10px;">
        <span style="font-family:'JetBrains Mono'; font-weight:bold; letter-spacing:2px; font-size:22px;">MORGUE TERMINAL v2.5</span>
        <span style="color:#00FF00; font-family:'JetBrains Mono'; font-size:16px;">● ONLINE: {current['time']} JST</span>
    </div>
""", unsafe_allow_html=True)

st.write("##")

# 指標セクション（数値の増減によって自動で色が変わる設定）
m1, m2, m3 = st.columns([2, 2, 1])
if len(st.session_state.history) > 1:
    delta_jpy = current['morg_jpy'] - st.session_state.history[-2]['morg_jpy']
    delta_usd = current['close'] - st.session_state.history[-2]['close']
    delta_fx = current['fx_rate'] - st.session_state.history[-2]['fx_rate']
else:
    delta_jpy = delta_usd = delta_fx = 0

m1.metric("MORG/JPY", f"¥{current['morg_jpy']}", delta=delta_jpy)
m2.metric("MORG/USD", f"$ {current['close']}", delta=round(delta_usd, 3))
m3.metric("USD/JPY", f"¥{current['fx_rate']}", delta=round(delta_fx, 2))

st.write("---")

# 計算ロジック・パネル
with st.container():
    col_c1, col_c2 = st.columns([1, 1.2])
    with col_c1:
        st.markdown("#### ［ 構成要素と係数 ］")
        st.markdown(f"""
        | 要素 | 現在値 | 適用係数 |
        | :--- | :--- | :--- |
        | **CONFLICT** | {current['conflict']} | **x {current['factors']['c']}** |
        | **OIL** | ${current['oil']} | **x {current['factors']['o']}** |
        | **IRON** | {current['iron']}% | **x {current['factors']['i']}** |
        | **PRESS** | {current['press']} | **x {current['factors']['p']}** |
        """)
    with col_c2:
        st.markdown("#### ［ 算出アルゴリズム ］")
        st.latex(r"MORG_{USD} = 1.0 \times \text{C}_{f} \times \text{O}_{f} \times \text{I}_{f} \times \text{P}_{f}")
        st.caption(f"統合計算式: 1.0 × {current['factors']['c']} × {current['factors']['o']} × {current['factors']['i']} × {current['factors']['p']} = {current['close']}")

st.write("---")

# メインチャートとニュース
gl, gr = st.columns([2, 1])
with gl:
    st.markdown("#### ［ 市場ボラティリティ ］")
    fig = go.Figure(data=[go.Candlestick(
        x=df['time'], open=df['open'], high=df['high'], low=df['low'], close=df['close'],
        increasing_line_color='#FFFFFF', decreasing_line_color='#FF0000',
        increasing_fillcolor='#333', decreasing_fillcolor='#FF0000'
    )])
    fig.update_layout(
        template="plotly_dark", height=400, margin=dict(l=0,r=0,b=0,t=0),
        yaxis=dict(autorange=True, fixedrange=False, tickformat=".3f", gridcolor='#222'),
        xaxis=dict(rangeslider_visible=False, gridcolor='#222')
    )
    st.plotly_chart(fig, use_container_width=True)

with gr:
    st.markdown("#### ［ 最新戦況 ］")
    for art in current['headlines']:
        st.markdown(f"""
            <div style="margin-bottom:12px; border-left:3px solid #FF0000; padding-left:10px;">
                <span style="color:#FF4B4B; font-size:10px; font-weight:bold;">{art['source']['name']}</span><br>
                <a href="{art['url']}" target="_blank" style="color:#DDD; text-decoration:none; font-size:12px;">{art['title']}</a>
            </div>
        """, unsafe_allow_html=True)

st.write("---")
# 個別指標のミニグラフ
st.markdown("#### ［ 構成要素の個別推移 ］")
ti1, ti2, ti3 = st.columns(3)
ti1.caption("CONFLICT VOL")
ti1.line_chart(df.set_index('time')['conflict'], height=100)
ti2.caption("IRON INDEX")
ti2.line_chart(df.set_index('time')['iron'], height=100)
ti3.caption("OIL PRICE")
ti3.line_chart(df.set_index('time')['oil'], height=100)