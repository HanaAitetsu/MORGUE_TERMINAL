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
    # 1. GDELT (世界の暴力・混乱ボリューム)
    conflict_vol = 100
    try:
        gdelt_url = 'https://api.gdeltproject.org/api/v2/doc/doc?query=(conflict OR violence OR "military action")&mode=TimelineVol&format=json'
        res = requests.get(gdelt_url, timeout=10).json()
        conflict_vol = res['timeline'][0]['data'][-1]['value'] * 10
    except: conflict_vol = 145.0

    # 2. FRED (原油)
    oil_price = 80.0
    try:
        fred_url = f"https://api.stlouisfed.org/fred/series/observations?series_id=DCOILBRENTEU&api_key={FRED_API_KEY}&file_type=json&sort_order=desc&limit=1"
        oil_price = float(requests.get(fred_url).json()['observations'][0]['value'])
    except: oil_price = 83.1

    # 3. yfinance (軍需株)
    iron_idx = 0.0
    try:
        stock = yf.download(["LMT", "RTX", "NOC"], period="1d", interval="5min", progress=False)
        iron_idx = stock['Close'].pct_change().mean(axis=1).iloc[-1] * 100
    except: iron_idx = 0.15

    # 4. News API (クエリを厳密化してノイズ除去)
    headlines = []
    press_factor = 1.0
    try:
        # スポーツ、エンタメ、ストライキを除外
        q = '("armed conflict" OR "warfare" OR "casualty report" OR "missile strike") -sports -entertainment -baseball'
        news_url = f'https://newsapi.org/v2/everything?q={q}&sortBy=publishedAt&language=en&apiKey={NEWS_API_KEY}&pageSize=5'
        n_res = requests.get(news_url).json()
        headlines = n_res.get('articles', [])
        press_factor = 1 + (min(n_res.get('totalResults', 0), 1500) / 8000)
    except: press_factor = 1.0

    # 指数計算
    price_usd = 1.0 * (1 + (conflict_vol/100)) * (oil_price/75) * (1 + (iron_idx/20)) * press_factor
    
    return {
        "morg_usd": round(price_usd, 3),
        "morg_jpy": int(price_usd * 155),
        "conflict_vol": round(conflict_vol, 1),
        "oil": round(oil_price, 2),
        "iron": round(iron_idx, 2),
        "press": round(press_factor, 3),
        "headlines": headlines,
        "time": datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    }

current = fetch_morgue_metrics()
prev = st.session_state.prev_data or current

# --- UI ---
st.markdown(f"""
    <div style="display:flex; justify-content:space-between; border-bottom:2px solid #333; padding-bottom:10px;">
        <span style="font-family:'JetBrains Mono'; font-weight:bold; letter-spacing:2px;">MORGUE INDEX // SYSTEM v1.8</span>
        <span style="color:#00FF00; font-family:'JetBrains Mono';">● SYNC: {current['time']} JST</span>
    </div>
""", unsafe_allow_html=True)

st.write("##")

# メイン表示
c1, c2 = st.columns(2)
c1.metric("MORG/JPY", f"¥{current['morg_jpy']}", delta=f"{current['morg_jpy'] - prev['morg_jpy']}円")
c2.metric("MORG/USD", f"$ {current['morg_usd']}", delta=f"{current['morg_usd'] - prev['morg_usd']:.3f}$")

st.write("##")

# サブメトリクス
c3, c4, c5, c6 = st.columns(4)
c3.metric("混乱度 (CONFLICT)", current['conflict_vol'])
c4.metric("軍需騰落 (IRON)", f"{current['iron']}%")
c5.metric("原油価格 (OIL)", f"${current['oil']}")
c6.metric("報道圧力 (PRESS)", f"x{current['press']}")

st.divider()

col_left, col_right = st.columns([2, 1])

with col_left:
    st.markdown("### ［ 指数推移 ］")
    fig = go.Figure()
    # セッションを使って簡易的な履歴をシミュレート（実際は20回分のリストを保持するのが理想）
    y_vals = [current['morg_usd'] * (1 + np.random.uniform(-0.003, 0.003)) for _ in range(15)] + [current['morg_usd']]
    fig.add_trace(go.Scatter(y=y_vals, mode='lines+markers', line=dict(color='#FFFFFF', width=3), fill='tozeroy', fillcolor='rgba(255,255,255,0.05)'))
    fig.update_layout(template="plotly_dark", height=300, margin=dict(l=0,r=0,b=0,t=0), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    st.plotly_chart(fig, use_container_width=True)

    # 生データの常時表示（プルダウン廃止）
    st.write("##")
    st.markdown("### ［ 計算根拠データ ］")
    raw_df = pd.DataFrame([current]).drop('headlines', axis=1)
    st.dataframe(raw_df, use_container_width=True)

with col_right:
    st.markdown("### ［ 最新戦況 ］")
    for art in current['headlines']:
        st.markdown(f"""
            <div style="margin-bottom:15px; border-left:3px solid #FF0000; padding-left:12px;">
                <span class="news-source">{art['source']['name']}</span><br>
                <a href="{art['url']}" target="_blank" class="news-title">{art['title']}</a>
            </div>
        """, unsafe_allow_html=True)

st.session_state.prev_data = current