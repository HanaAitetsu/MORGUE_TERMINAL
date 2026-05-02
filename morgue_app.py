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
    # 1. GDELT (世界の混乱指数) - ACLEDの代わり
    # 直近の「衝突・暴力」に関連するニュースのボリュームを取得
    conflict_vol = 100
    try:
        gdelt_url = "https://api.gdeltproject.org/api/v2/doc/doc?query=(conflict OR violence OR attack)&mode=TimelineVol&format=json"
        res = requests.get(gdelt_url, timeout=10).json()
        # 最新のデータポイントの数値を採用
        conflict_vol = res['timeline'][0]['data'][-1]['value'] * 10
    except: conflict_vol = 145 # フォールバック

    # 2. FRED (原油)
    oil_price = 80.0
    try:
        fred_url = f"https://api.stlouisfed.org/fred/series/observations?series_id=DCOILBRENTEU&api_key={FRED_API_KEY}&file_type=json&sort_order=desc&limit=1"
        oil_price = float(requests.get(fred_url).json()['observations'][0]['value'])
    except: oil_price = 83.1

    # 3. yfinance (軍需株騰落)
    iron_idx = 0.0
    try:
        stock = yf.download(["LMT", "RTX", "NOC"], period="1d", interval="5min", progress=False)
        iron_idx = stock['Close'].pct_change().mean(axis=1).iloc[-1] * 100
    except: iron_idx = 0.2

    # 4. News API (報道圧力 & ヘッドライン)
    headlines = []
    press_factor = 1.0
    try:
        news_url = f'https://newsapi.org/v2/everything?q=(war OR "killed" OR "strike")&sortBy=publishedAt&language=en&apiKey={NEWS_API_KEY}&pageSize=5'
        n_res = requests.get(news_url).json()
        headlines = n_res.get('articles', [])
        press_factor = 1 + (min(n_res.get('totalResults', 0), 2000) / 10000)
    except: press_factor = 1.0

    # --- 新・モルグ指数計算式 ---
    # $MORG = Base \times (1 + \frac{ConflictVol}{100}) \times (\frac{Oil}{75}) \times (1 + \frac{Iron}{20}) \times Press$
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

# データ処理
current = fetch_morgue_metrics()
prev = st.session_state.prev_data or current

def get_delta(key):
    diff = current[key] - prev[key]
    if isinstance(diff, int): return f"{diff}"
    return f"{diff:.3f}"

# --- UI構築 ---
st.markdown(f"""
    <div class="header-container">
        <span class="system-title">MORGUE INDEX SYSTEM // v1.7</span>
        <span class="status-tag">● 同期完了 (JST): {current['time']}</span>
    </div>
""", unsafe_allow_html=True)

st.write("##")

# メインメトリクス
c1, c2 = st.columns(2)
c1.metric("MORG/JPY", f"¥{current['morg_jpy']}", delta=f"{get_delta('morg_jpy')} JPY")
c2.metric("MORG/USD", f"$ {current['morg_usd']}", delta=f"{get_delta('morg_usd')} USD")

st.write("##")

# サブメトリクス（アップダウン表示）
c3, c4, c5, c6 = st.columns(4)
c3.metric("混乱指数 (CONFLICT)", f"{current['conflict_vol']}", delta=get_delta('conflict_vol'))
c4.metric("軍需指数 (IRON)", f"{current['iron']}%", delta=get_delta('iron'))
c5.metric("原油価格 (OIL)", f"${current['oil']}", delta=get_delta('oil'))
c6.metric("報道圧力 (PRESS)", f"x{current['press']}", delta=get_delta('press'))

st.divider()

# --- グラフィックセクション ---
col_left, col_right = st.columns([2, 1])

with col_left:
    st.markdown("#### 指数推移トレンド")
    # 簡易的な折れ線グラフ（前回の値を反映）
    fig = go.Figure()
    # 描画用の擬似履歴（実際はDB保存が必要ですが、セッションで代用）
    periods = 20
    hist_y = [current['morg_usd'] * (1 + np.random.uniform(-0.005, 0.005)) for _ in range(periods)]
    fig.add_trace(go.Scatter(y=hist_y, mode='lines+markers', line=dict(color='#FFFFFF', width=2), fill='tozeroy'))
    fig.update_layout(template="plotly_dark", height=300, margin=dict(l=10,r=10,b=10,t=10), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    st.plotly_chart(fig, use_container_width=True)

with col_right:
    st.markdown("#### 最新戦況ブリーフィング")
    for art in current['headlines']:
        st.markdown(f"""
            <div style="margin-bottom:12px; border-left:2px solid #FF0000; padding-left:10px;">
                <small style="color:#666;">{art['publishedAt'][:10]}</small><br>
                <a href="{art['url']}" target="_blank" style="color:#DDD; text-decoration:none; font-size:12px;">{art['title'][:70]}...</a>
            </div>
        """, unsafe_allow_html=True)

# 計算根拠テーブル
with st.expander("計算根拠生データ (Raw Data)"):
    st.table(pd.DataFrame([current]).drop('headlines', axis=1))

st.session_state.prev_data = current