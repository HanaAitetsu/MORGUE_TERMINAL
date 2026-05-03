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

st.set_page_config(page_title="MORGUE TERMINAL v2.1", layout="wide")

# CSS読み込み (変更なし)
def local_css(file_name):
    try:
        with open(file_name, encoding="utf-8") as f:
            st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)
    except: pass
local_css("style.css")

# --- 履歴の初期化 (過去データを最初に詰め込む) ---
if 'history' not in st.session_state:
    st.session_state.history = []

# --- 過去データの初期取得関数 ---
@st.cache_data(ttl=3600)
def get_initial_history():
    # 軍需株10銘柄の過去1日の推移を取得
    defense_tickers = ["LMT", "RTX", "NOC", "GD", "BA", "LHX", "HII", "PLTR", "KTOS", "LDOS"]
    h_data = []
    try:
        # yfinanceから過去1日のデータを15分間隔で取得
        stocks = yf.download(defense_tickers, period="1d", interval="15m", progress=False)['Close']
        growth = stocks.pct_change().mean(axis=1) * 100
        
        # 過去のタイムスタンプに合わせてダミーも含めたヒストリカルデータを作成
        for i, (ts, val) in enumerate(growth.tail(15).items()):
            h_data.append({
                "time": ts.astimezone(JST).strftime("%H:%M"),
                "iron": round(val, 3),
                "conflict": 140.0 + np.random.uniform(-5, 5), # 過去分は推計
                "oil": 82.0 + np.random.uniform(-1, 1),
                "morg_usd": 1.2 + (i * 0.01) # 右肩上がりのシミュレーション
            })
    except:
        pass
    return h_data

# 履歴が空なら初期データを注入
if not st.session_state.history:
    st.session_state.history = get_initial_history()

# --- 最新データ取得 ---
@st.cache_data(ttl=600)
def fetch_latest():
    # 為替レート
    fx_rate = 155.0
    try:
        fx_data = yf.download("JPY=X", period="1d", interval="5m", progress=False)
        fx_rate = fx_data['Close'].iloc[-1]
    except: pass

    # GDELT (混乱度)
    conflict_vol = 145.0
    try:
        gdelt_url = 'https://api.gdeltproject.org/api/v2/doc/doc?query=(conflict OR violence OR "military action")&mode=TimelineVol&format=json'
        res = requests.get(gdelt_url, timeout=10).json()
        conflict_vol = res['timeline'][0]['data'][-1]['value'] * 10
    except: pass

    # FRED (原油)
    oil_price = 82.0
    try:
        fred_url = f"https://api.stlouisfed.org/fred/series/observations?series_id=DCOILBRENTEU&api_key={FRED_API_KEY}&file_type=json&sort_order=desc&limit=1"
        oil_price = float(requests.get(fred_url).json()['observations'][0]['value'])
    except: pass

    # yfinance (軍需騰落)
    defense_tickers = ["LMT", "RTX", "NOC", "GD", "BA", "LHX", "HII", "PLTR", "KTOS", "LDOS"]
    iron_growth = 0.1
    try:
        stocks = yf.download(defense_tickers, period="1d", interval="5m", progress=False)['Close']
        iron_growth = stocks.pct_change().mean(axis=1).iloc[-1] * 100
    except: pass

    # News API
    press_count = 500
    headlines = []
    try:
        q = '("armed conflict" OR "warfare" OR "missile strike") -sports -entertainment'
        news_url = f'https://newsapi.org/v2/everything?q={q}&sortBy=publishedAt&language=en&apiKey={NEWS_API_KEY}&pageSize=5'
        n_res = requests.get(news_url).json()
        headlines = n_res.get('articles', [])
        press_count = n_res.get('totalResults', 0)
    except: pass

    # 指数計算
    p_factor = 1 + (min(press_count, 2000) / 8000)
    morg_usd = 1.0 * (1 + (conflict_vol/100)) * (oil_price/75) * (1 + (iron_growth/20)) * p_factor
    
    current = {
        "time": datetime.now(JST).strftime("%H:%M"),
        "morg_usd": round(morg_usd, 3),
        "morg_jpy": int(morg_usd * fx_rate),
        "fx_rate": round(fx_rate, 2),
        "conflict": round(conflict_vol, 2),
        "iron": round(iron_growth, 3),
        "oil": round(oil_price, 2),
        "press": press_count,
        "p_factor": round(p_factor, 3),
        "headlines": headlines
    }
    
    # 履歴を更新 (重複を避けるため、最新の時間をチェック)
    if not st.session_state.history or st.session_state.history[-1]['time'] != current['time']:
        st.session_state.history.append(current)
        if len(st.session_state.history) > 30: st.session_state.history.pop(0)
        
    return current

current = fetch_latest()
history_df = pd.DataFrame(st.session_state.history)

# --- UI ---
st.markdown(f"""
    <div style="display:flex; justify-content:space-between; border-bottom:2px solid #444; padding-bottom:10px;">
        <span style="font-family:'JetBrains Mono'; font-weight:bold; letter-spacing:2px; font-size:20px;">MORGUE TERMINAL v2.1 // TRADING MODE</span>
        <span style="color:#00FF00; font-family:'JetBrains Mono';">● SYNC: {current['time']} JST</span>
    </div>
""", unsafe_allow_html=True)

st.write("##")

# メインメトリクス
c1, c2, c3 = st.columns([2, 2, 1])
c1.metric("MORG/JPY", f"¥{current['morg_jpy']}")
c2.metric("MORG/USD", f"$ {current['morg_usd']}")
c3.metric("USD/JPY", f"{current['fx_rate']}")

st.divider()

# --- 個別指標トレンド (横軸を時間に固定) ---
st.markdown("### ［ 指数構成要素の推移 ］")
if not history_df.empty:
    # 横軸を「時間」にするための設定
    chart_df = history_df.set_index('time')
    
    t1, t2, t3 = st.columns(3)
    with t1:
        st.caption("CONFLICT (混乱度)")
        st.line_chart(chart_df['conflict'], height=180)
    with t2:
        st.caption("IRON (軍需10銘柄平均)")
        st.line_chart(chart_df['iron'], height=180)
    with t3:
        st.caption("OIL (原油価格)")
        st.line_chart(chart_df['oil'], height=180)

st.divider()

# --- 計算式の透明化 (詳細版) ---
with st.expander("詳細な算出プロセスを表示"):
    st.latex(r"MORG_{JPY} = [ 1.0 \times \text{ConflictF} \times \text{OilF} \times \text{IronF} \times \text{PressF} ] \times FX")
    st.markdown(f"""
    | 項目 | 生データ | 適用係数 | 計算式 |
    | :--- | :--- | :--- | :--- |
    | **混乱 (Conflict)** | {current['conflict']} | **{1 + current['conflict']/100:.3f}** | 1 + (Val/100) |
    | **原油 (Oil)** | ${current['oil']} | **{current['oil']/75:.3f}** | Val / 75 |
    | **軍需 (Iron)** | {current['iron']}% | **{1 + current['iron']/20:.3f}** | 1 + (Val/20) |
    | **報道 (Press)** | {current['press']}件 | **{current['p_factor']}** | 1 + (min(Val,2k)/8k) |
    | **為替 (FX)** | ¥{current['fx_rate']} | - | USD/JPY 市場レート |
    """)

st.write("##")

# --- チャートとニュース ---
col_left, col_right = st.columns([2, 1])

with col_left:
    st.markdown("### ［ 市場ボラティリティ (MORG/USD) ］")
    # ロウソク足のスケール調整
    h_usd = history_df['morg_usd'].tolist()
    fig = go.Figure(data=[go.Candlestick(
        x=history_df['time'],
        open=h_usd[:-1], high=[v*1.002 for v in h_usd[:-1]],
        low=[v*0.998 for v in h_usd[:-1]], close=h_usd[1:],
        increasing_line_color='#FFFFFF', decreasing_line_color='#FF0000',
        increasing_fillcolor='#111', decreasing_fillcolor='#FF0000'
    )])
    y_min, y_max = min(h_usd)*0.995, max(h_usd)*1.005
    fig.update_layout(template="plotly_dark", height=400, margin=dict(l=0,r=0,b=0,t=0),
                      yaxis=dict(range=[y_min, y_max], tickformat=".3f"),
                      xaxis_rangeslider_visible=False)
    st.plotly_chart(fig, use_container_width=True)

with col_right:
    st.markdown("### ［ 最新戦況 ］")
    for art in current['headlines']:
        st.markdown(f"""
            <div style="margin-bottom:12px; border-left:3px solid #FF0000; padding-left:12px;">
                <span style="color:#FF4B4B; font-size:11px; font-weight:bold;">{art['source']['name']}</span><br>
                <a href="{art['url']}" target="_blank" style="color:#EEE; text-decoration:none; font-size:13px; font-weight:bold;">{art['title']}</a>
            </div>
        """, unsafe_allow_html=True)