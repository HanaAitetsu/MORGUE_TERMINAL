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

st.set_page_config(page_title="MORGUE TERMINAL v2.3", layout="wide")

# CSS適用
def local_css(file_name):
    try:
        with open(file_name, encoding="utf-8") as f:
            st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)
    except:
        st.markdown("""<style>
            body { background-color: #000; color: #fff; }
            .stMetric { border: 1px solid #333; padding: 10px; }
        </style>""", unsafe_allow_html=True)

local_css("style.css")

# --- セッション履歴の管理 ---
if 'history' not in st.session_state:
    st.session_state.history = []

# --- 過去データの初期シミュレーション ---
@st.cache_data(ttl=3600)
def get_initial_history():
    h_data = []
    base_time = datetime.now(JST)
    for i in range(20):
        t = (base_time - timedelta(minutes=15*(20-i))).strftime("%H:%M")
        h_data.append({
            "time": t,
            "iron": round(np.random.uniform(-0.5, 0.5), 3),
            "conflict": round(140.0 + np.random.uniform(-5, 5), 2),
            "oil": round(80.0 + np.random.uniform(-2, 2), 2),
            "morg_usd": round(1.2 + (i * 0.005), 3)
        })
    return h_data

if not st.session_state.history:
    st.session_state.history = get_initial_history()

# --- データ取得エンジン ---
@st.cache_data(ttl=600)
def fetch_latest_data():
    # 1. 為替レート
    fx_rate = 155.0
    try:
        fx_df = yf.download("JPY=X", period="1d", interval="5m", progress=False)
        if not fx_df.empty:
            # 最新のClose値を確実にスカラー数値として取得
            fx_rate = float(fx_df['Close'].iloc[-1].item())
    except: pass

    # 2. GDELT (混乱度)
    conflict_vol = 145.0
    try:
        gdelt_url = 'https://api.gdeltproject.org/api/v2/doc/doc?query=(conflict OR violence OR "military action")&mode=TimelineVol&format=json'
        res = requests.get(gdelt_url, timeout=10).json()
        conflict_vol = float(res['timeline'][0]['data'][-1]['value'] * 10)
    except: pass

    # 3. FRED (原油)
    oil_price = 82.0
    try:
        fred_url = f"https://api.stlouisfed.org/fred/series/observations?series_id=DCOILBRENTEU&api_key={FRED_API_KEY}&file_type=json&sort_order=desc&limit=1"
        oil_price = float(requests.get(fred_url).json()['observations'][0]['value'])
    except: pass

    # 4. yfinance (軍需株10銘柄)
    iron_growth = 0.1
    try:
        defense_tickers = ["LMT", "RTX", "NOC", "GD", "BA", "LHX", "HII", "PLTR", "KTOS", "LDOS"]
        stocks = yf.download(defense_tickers, period="1d", interval="5m", progress=False)['Close']
        # 全銘柄の平均騰落率を算出
        avg_pct = stocks.pct_change().mean(axis=1).iloc[-1]
        iron_growth = float(avg_pct * 100)
    except: pass

    # 5. News API
    press_count = 500
    headlines = []
    try:
        q = '("armed conflict" OR "warfare" OR "missile strike") -sports -entertainment'
        news_url = f'https://newsapi.org/v2/everything?q={q}&sortBy=publishedAt&language=en&apiKey={NEWS_API_KEY}&pageSize=5'
        n_res = requests.get(news_url).json()
        headlines = n_res.get('articles', [])
        press_count = int(n_res.get('totalResults', 500))
    except: pass

    # 指数計算
    p_factor = 1 + (min(press_count, 2000) / 8000)
    morg_usd = 1.0 * (1 + (conflict_vol/100)) * (oil_price/75) * (1 + (iron_growth/20)) * p_factor
    
    current = {
        "time": datetime.now(JST).strftime("%H:%M"),
        "morg_usd": round(float(morg_usd), 3),
        "morg_jpy": int(morg_usd * fx_rate),
        "fx_rate": round(fx_rate, 2),
        "conflict": round(conflict_vol, 2),
        "iron": round(iron_growth, 3),
        "oil": round(oil_price, 2),
        "press": press_count,
        "p_factor": round(p_factor, 3),
        "headlines": headlines
    }
    
    # 履歴を更新
    if not st.session_state.history or st.session_state.history[-1]['time'] != current['time']:
        st.session_state.history.append(current)
        if len(st.session_state.history) > 40: st.session_state.history.pop(0)
        
    return current

# --- 実行 ---
current = fetch_latest_data()
history_df = pd.DataFrame(st.session_state.history)

# --- UI構築 ---
st.markdown(f"""
    <div style="display:flex; justify-content:space-between; border-bottom:2px solid #444; padding-bottom:10px;">
        <span style="font-family:'JetBrains Mono'; font-weight:bold; letter-spacing:2px; font-size:20px;">MORGUE TERMINAL v2.3</span>
        <span style="color:#00FF00; font-family:'JetBrains Mono';">● SYNC: {current['time']} JST</span>
    </div>
""", unsafe_allow_html=True)

st.write("##")

# メイン数値
c1, c2, c3 = st.columns([2, 2, 1])
c1.metric("MORG/JPY", f"¥{current['morg_jpy']}")
c2.metric("MORG/USD", f"$ {current['morg_usd']}")
c3.metric("USD/JPY", f"{current['fx_rate']}")

st.divider()

# トレンドグラフ
st.markdown("### ［ 指数構成要素の推移 ］")
if not history_df.empty:
    chart_data = history_df.set_index('time')
    t1, t2, t3 = st.columns(3)
    with t1:
        st.caption("CONFLICT (混乱度)")
        st.line_chart(chart_data['conflict'], height=180)
    with t2:
        st.caption("IRON (軍需平均騰落 %)")
        st.line_chart(chart_data['iron'], height=180)
    with t3:
        st.caption("OIL (原油価格 $)")
        st.line_chart(chart_data['oil'], height=180)

st.divider()

# 計算根拠のエクスパンダー
with st.expander("アルゴリズム詳細を確認"):
    st.latex(r"MORG_{USD} = 1.0 \times (1 + \frac{Conflict}{100}) \times \frac{Oil}{75} \times (1 + \frac{Iron}{20}) \times PressFactor")
    st.markdown(f"""
    | 要素 | 現在値 | 適用係数 |
    | :--- | :--- | :--- |
    | **混乱 (Conflict)** | {current['conflict']} | **x{1 + current['conflict']/100:.3f}** |
    | **原油 (Oil)** | ${current['oil']} | **x{current['oil']/75:.3f}** |
    | **軍需 (Iron)** | {current['iron']}% | **x{1 + current['iron']/20:.3f}** |
    | **報道 (Press)** | {current['press']}件 | **x{current['p_factor']}** |
    """)

st.write("##")

# 下部レイアウト
col_left, col_right = st.columns([2, 1])

with col_left:
    st.markdown("### ［ 市場ボラティリティ ］")
    h_usd = history_df['morg_usd'].tolist()
    fig = go.Figure(data=[go.Candlestick(
        x=history_df['time'],
        open=h_usd[:-1], high=[v*1.001 for v in h_usd[:-1]],
        low=[v*0.999 for v in h_usd[:-1]], close=h_usd[1:],
        increasing_line_color='#FFFFFF', decreasing_line_color='#FF0000',
        increasing_fillcolor='#111', decreasing_fillcolor='#FF0000'
    )])
    fig.update_layout(template="plotly_dark", height=400, margin=dict(l=0,r=0,b=0,t=0),
                      yaxis=dict(autorange=True, fixedrange=False, tickformat=".3f"),
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