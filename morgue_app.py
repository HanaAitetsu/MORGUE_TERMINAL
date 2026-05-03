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

st.set_page_config(page_title="MORGUE TERMINAL v2.5", layout="wide")

def local_css(file_name):
    try:
        with open(file_name, encoding="utf-8") as f:
            st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)
    except: pass
local_css("style.css")

if 'history' not in st.session_state:
    st.session_state.history = []

# --- 過去データの初期生成 (データ構造を完全に統一) ---
@st.cache_data(ttl=3600)
def get_initial_history():
    h_data = []
    base_time = datetime.now(JST)
    current_price = 1.250
    fixed_fx = 154.50 # 初期化用の仮レート
    
    for i in range(25):
        t = (base_time - timedelta(minutes=15*(25-i))).strftime("%H:%M")
        change = np.random.uniform(-0.015, 0.015)
        open_p = current_price
        close_p = open_p + change
        high_p = max(open_p, close_p) + 0.005
        low_p = min(open_p, close_p) - 0.005
        
        # 全てのキーをfetch_latestと合わせる
        h_data.append({
            "time": t,
            "open": round(open_p, 3), "high": round(high_p, 3),
            "low": round(low_p, 3), "close": round(close_p, 3),
            "morg_jpy": int(close_p * fixed_fx),
            "fx_rate": fixed_fx,
            "iron": round(np.random.uniform(-0.5, 0.5), 2),
            "conflict": round(140.0 + np.random.uniform(-5, 5), 1),
            "oil": round(80.0 + np.random.uniform(-2, 2), 2),
            "factors": {"c": 1.4, "o": 1.0, "i": 1.0, "p": 1.0}
        })
        current_price = close_p
    return h_data

if not st.session_state.history:
    st.session_state.history = get_initial_history()

# --- 最新データ取得 ---
@st.cache_data(ttl=600)
def fetch_latest():
    # 為替
    fx_rate = 155.0
    try:
        fx_df = yf.download("JPY=X", period="1d", interval="5m", progress=False)
        fx_rate = float(fx_df['Close'].iloc[-1].item())
    except: pass

    # 混乱度
    conflict_vol = 145.0
    try:
        res = requests.get('https://api.gdeltproject.org/api/v2/doc/doc?query=(conflict OR violence OR "military action")&mode=TimelineVol&format=json', timeout=10).json()
        conflict_vol = float(res['timeline'][0]['data'][-1]['value'] * 10)
    except: pass

    # 原油
    oil_price = 82.0
    try:
        fred_url = f"https://api.stlouisfed.org/fred/series/observations?series_id=DCOILBRENTEU&api_key={FRED_API_KEY}&file_type=json&sort_order=desc&limit=1"
        oil_price = float(requests.get(fred_url).json()['observations'][0]['value'])
    except: pass

    # 軍需株
    iron_growth = 0.1
    try:
        tickers = ["LMT", "RTX", "NOC", "GD", "BA", "LHX", "HII", "PLTR", "KTOS", "LDOS"]
        stocks = yf.download(tickers, period="1d", interval="5m", progress=False)['Close']
        iron_growth = float(stocks.pct_change().mean(axis=1).iloc[-1] * 100)
    except: pass

    # 報道
    press_count = 500
    headlines = []
    try:
        news_url = f'https://newsapi.org/v2/everything?q=("armed conflict" OR warfare)&sortBy=publishedAt&apiKey={NEWS_API_KEY}&pageSize=5'
        n_res = requests.get(news_url).json()
        headlines = n_res.get('articles', [])
        press_count = int(n_res.get('totalResults', 500))
    except: pass

    # 指数計算
    c_f = 1 + (conflict_vol/100)
    o_f = oil_price / 75
    i_f = 1 + (iron_growth/20)
    p_f = 1 + (min(press_count, 2000) / 8000)
    morg_usd = 1.0 * c_f * o_f * i_f * p_f
    
    current_time = datetime.now(JST).strftime("%H:%M")
    
    # ロウソク足の連続性を担保
    prev_close = st.session_state.history[-1]['close'] if st.session_state.history else morg_usd
    
    new_entry = {
        "time": current_time,
        "open": prev_close,
        "high": max(prev_close, morg_usd) + 0.003,
        "low": min(prev_close, morg_usd) - 0.003,
        "close": round(morg_usd, 3),
        "morg_jpy": int(morg_usd * fx_rate),
        "fx_rate": round(fx_rate, 2),
        "conflict": round(conflict_vol, 2),
        "iron": round(iron_growth, 3),
        "oil": round(oil_price, 2),
        "press": press_count,
        "factors": {"c": round(c_f, 3), "o": round(o_f, 3), "i": round(i_f, 3), "p": round(p_f, 3)},
        "headlines": headlines
    }
    
    if not st.session_state.history or st.session_state.history[-1]['time'] != current_time:
        st.session_state.history.append(new_entry)
        if len(st.session_state.history) > 50: st.session_state.history.pop(0)
        
    return new_entry

current = fetch_latest()
df = pd.DataFrame(st.session_state.history)

# --- UI ---
st.markdown(f"""
    <div style="display:flex; justify-content:space-between; border-bottom:2px solid #444; padding-bottom:10px;">
        <span style="font-family:'JetBrains Mono'; font-weight:bold; letter-spacing:2px; font-size:22px;">MORGUE TERMINAL v2.5</span>
        <span style="color:#00FF00; font-family:'JetBrains Mono'; font-size:18px;">● LIVE_SYNC: {current['time']} JST</span>
    </div>
""", unsafe_allow_html=True)

st.write("##")

# メインメトリクス
m1, m2, m3 = st.columns([2, 2, 1])

# deltaの計算を安全に行う
def get_delta(key):
    if len(st.session_state.history) > 1:
        return current[key] - st.session_state.history[-2][key]
    return 0

m1.metric("MORG/JPY", f"¥{current['morg_jpy']}", delta=f"{get_delta('morg_jpy')} JPY")
m2.metric("MORG/USD", f"$ {current['close']}", delta=f"{get_delta('close'):.3f} USD")
m3.metric("USD/JPY", f"¥{current['fx_rate']}", delta=f"{get_delta('fx_rate'):.2f}")

st.write("---")

# 計算根拠パネル
col_calc, col_eq = st.columns([1, 1.2])
with col_calc:
    st.markdown("### ［ 指数構成要素の現在値 ］")
    st.markdown(f"""
    | 要素 | 取得値 | 適用係数 |
    | :--- | :--- | :--- |
    | **混乱度 (Conflict)** | {current['conflict']} | **x {current['factors']['c']}** |
    | **原油価格 (Oil)** | ${current['oil']} | **x {current['factors']['o']}** |
    | **軍需騰落 (Iron)** | {current['iron']}% | **x {current['factors']['i']}** |
    | **報道圧力 (Press)** | {current['press']} | **x {current['factors']['p']}** |
    """)

with col_eq:
    st.markdown("### ［ 算出アルゴリズム ］")
    st.latex(r"MORG_{USD} = 1.0 \times \left(1 + \frac{C}{100}\right) \times \frac{O}{75} \times \left(1 + \frac{I}{20}\right) \times P_{factor}")
    st.info(f"最終計算結果: $1.0 × {current['factors']['c']} × {current['factors']['o']} × {current['factors']['i']} × {current['factors']['p']} = **$ {current['close']}**")

st.write("---")

# グラフセクション
col_left, col_right = st.columns([2, 1])

with col_left:
    st.markdown("### ［ 市場ボラティリティ ］")
    fig = go.Figure(data=[go.Candlestick(
        x=df['time'], open=df['open'], high=df['high'], low=df['low'], close=df['close'],
        increasing_line_color='#FFFFFF', decreasing_line_color='#FF0000',
        increasing_fillcolor='#111', decreasing_fillcolor='#FF0000'
    )])
    
    # Y軸を動的にスケーリング
    y_min, y_max = df['low'].min() * 0.998, df['high'].max() * 1.002
    fig.update_layout(
        template="plotly_dark", height=450, margin=dict(l=10,r=10,b=10,t=10),
        yaxis=dict(range=[y_min, y_max], gridcolor='#222', tickformat=".3f"),
        xaxis=dict(gridcolor='#222'), xaxis_rangeslider_visible=False
    )
    st.plotly_chart(fig, use_container_width=True)

with col_right:
    st.markdown("### ［ 最新戦況 ］")
    for art in current['headlines']:
        st.markdown(f"""
            <div style="margin-bottom:15px; border-left:3px solid #FF0000; padding-left:12px;">
                <span style="color:#FF4B4B; font-size:11px; font-weight:bold;">{art['source']['name']}</span><br>
                <a href="{art['url']}" target="_blank" style="color:#EEE; text-decoration:none; font-size:13px; font-weight:bold;">{art['title']}</a>
            </div>
        """, unsafe_allow_html=True)

st.write("---")
st.markdown("### ［ 指数構成要素の推移 ］")
t1, t2, t3 = st.columns(3)
# インデックスを時間に設定して表示
chart_df = df.set_index('time')
t1.caption("CONFLICT VOL")
t1.line_chart(chart_df['conflict'], height=120)
t2.caption("IRON (DEFENSE INDEX)")
t2.line_chart(chart_df['iron'], height=120)
t3.caption("OIL PRICE (BRENT)")
t3.line_chart(chart_df['oil'], height=120)