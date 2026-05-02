import streamlit as st
import pandas as pd
import yfinance as yf
import requests
import plotly.graph_objects as go
import numpy as np
import os
from datetime import datetime, timedelta, timezone

# --- 設定 ---
JST = timezone(timedelta(hours=9))
ACLED_EMAIL = os.environ.get("ACLED_EMAIL")
ACLED_KEY = os.environ.get("ACLED_KEY")
FRED_API_KEY = os.environ.get("FRED_API_KEY")
NEWS_API_KEY = os.environ.get("NEWS_API_KEY")

def local_css(file_name):
    try:
        with open(file_name, encoding="utf-8") as f:
            st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)
    except: pass

st.set_page_config(page_title="MORGUE TERMINAL", layout="wide")
local_css("style.css")

if 'prev_data' not in st.session_state:
    st.session_state.prev_data = None

# --- データ取得エンジン ---
@st.cache_data(ttl=900)
def fetch_morgue_metrics():
    # 1. ACLED (犠牲者)
    fatalities = 0
    try:
        res = requests.get("https://api.acleddata.com/acled/read", 
                           params={"email": ACLED_EMAIL, "key": ACLED_KEY, "limit": 50}, timeout=10)
        fatalities = sum([int(e.get('fatalities', 0)) for e in res.json().get('data', [])])
    except: fatalities = 120

    # 2. FRED (原油)
    oil_price = 80.0
    try:
        fred_url = f"https://api.stlouisfed.org/fred/series/observations?series_id=DCOILBRENTEU&api_key={FRED_API_KEY}&file_type=json&sort_order=desc&limit=1"
        oil_price = float(requests.get(fred_url).json()['observations'][0]['value'])
    except: oil_price = 82.4

    # 3. yfinance (軍需株)
    iron_idx = 0.0
    try:
        stock = yf.download(["LMT", "RTX", "NOC"], period="1d", interval="5min", progress=False)
        iron_idx = stock['Close'].pct_change().mean(axis=1).iloc[-1] * 100
    except: iron_idx = 0.3

    # 4. News API (報道圧力)
    news_headlines = []
    news_factor = 1.0
    try:
        # 「紛争」「軍事」「戦争」に関連する最新24時間の記事数を取得
        news_url = f"https://newsapi.org/v2/everything?q=(conflict OR war OR military)&sortBy=publishedAt&language=en&apiKey={NEWS_API_KEY}&pageSize=5"
        n_res = requests.get(news_url).json()
        news_headlines = n_res.get('articles', [])
        # 記事数が多いほど指数に微増の圧力をかける（報道の過熱）
        news_count = n_res.get('totalResults', 0)
        news_factor = 1 + (min(news_count, 1000) / 5000) # 最大+20%の報道補正
    except: news_factor = 1.0

    # --- モルグ指数計算式 ---
    # $MORG = Base \times (1 + \frac{Blood}{100}) \times (\frac{Oil}{75}) \times (1 + \frac{Iron}{20}) \times NewsFactor$
    price_usd = 1.0 * (1 + (fatalities/100)) * (oil_price/75) * (1 + (iron_idx/20)) * news_factor
    
    return {
        "morg_usd": round(price_usd, 3),
        "morg_jpy": int(price_usd * 155),
        "fatalities": fatalities,
        "oil": round(oil_price, 2),
        "iron": round(iron_idx, 2),
        "news_factor": round(news_factor, 3),
        "headlines": news_headlines,
        "time": datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    }

# データ処理
current = fetch_morgue_metrics()
prev = st.session_state.prev_data or current
deltas = {k: (current[k] - prev[k]) if isinstance(current[k], (int, float)) else 0 for k in current}

# --- UI構築 ---
st.markdown(f"""
    <div class="header-container">
        <span class="system-title">MORGUE INDEX SYSTEM // v1.6</span>
        <span class="status-tag">● 同期完了 (JST): {current['time']}</span>
    </div>
""", unsafe_allow_html=True)

st.write("##")

# メイン指標
c1, c2 = st.columns(2)
c1.metric("モルグ価格 (日本円)", f"¥{current['morg_jpy']}", delta=f"{deltas['morg_jpy']}円")
c2.metric("モルグ価格 (米ドル)", f"$ {current['morg_usd']}", delta=f"{deltas['morg_usd']:.3f}$")

st.write("##")

# サブ指標
c3, c4, c5, c6 = st.columns(4)
c3.metric("軍需成長 (IRON)", f"{current['iron']}%", delta=f"{deltas['iron']:.2f}%")
c4.metric("犠牲者数 (BLOOD)", current['fatalities'], delta=f"{deltas['fatalities']}人")
c5.metric("原油価格 (OIL)", f"${current['oil']}", delta=f"{deltas['oil']:.2f}$")
c6.metric("報道圧力 (PRESS)", f"x{current['news_factor']}", delta=f"{deltas['news_factor']:.3f}")

st.divider()

# --- チャートとニュース ---
col_left, col_right = st.columns([2, 1])

with col_left:
    st.text("指数推移トレンド (15M)")
    # （折れ線グラフを表示）
    fig = go.Figure()
    # 擬似履歴生成
    periods = 20
    hist_y = [current['morg_usd'] * (1 + np.random.uniform(-0.01, 0.01)) for _ in range(periods)]
    fig.add_trace(go.Scatter(y=hist_y, line=dict(color='#FFFFFF', width=3), fill='tozeroy', fillcolor='rgba(255,255,255,0.05)'))
    fig.update_layout(template="plotly_dark", height=300, margin=dict(l=0,r=0,b=0,t=0))
    st.plotly_chart(fig, use_container_width=True)

with col_right:
    st.text("最新戦況ブリーフィング")
    if current['headlines']:
        for art in current['headlines']:
            st.markdown(f"""
                <div style="margin-bottom:15px; border-left:2px solid #FF0000; padding-left:10px;">
                    <small style="color:#888;">{art['source']['name']}</small><br>
                    <a href="{art['url']}" target="_blank" style="color:#EEE; text-decoration:none; font-size:13px;">{art['title'][:60]}...</a>
                </div>
            """, unsafe_allow_html=True)
    else:
        st.caption("通信待機中...")

st.session_state.prev_data = current