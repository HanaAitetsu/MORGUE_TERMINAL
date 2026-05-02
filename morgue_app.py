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

def local_css(file_name):
    try:
        with open(file_name, encoding="utf-8") as f:
            st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)
    except: pass

st.set_page_config(page_title="MORGUE TERMINAL v2.0", layout="wide")
local_css("style.css")

# --- セッション履歴の保持 (トレンド表示用) ---
if 'history' not in st.session_state:
    st.session_state.history = []

# --- データ取得エンジン ---
@st.cache_data(ttl=600)
def fetch_morgue_metrics():
    # 1. 為替 (USD/JPY)
    fx_rate = 155.0
    try:
        fx_data = yf.download("JPY=X", period="1d", interval="5m", progress=False)
        fx_rate = fx_data['Close'].iloc[-1]
    except: pass

    # 2. GDELT (混乱度: CONFLICT)
    # ニュースに占める「紛争・暴力」の割合
    conflict_vol = 100.0
    try:
        gdelt_url = 'https://api.gdeltproject.org/api/v2/doc/doc?query=(conflict OR violence OR "military action")&mode=TimelineVol&format=json'
        res = requests.get(gdelt_url, timeout=10).json()
        conflict_vol = res['timeline'][0]['data'][-1]['value'] * 10
    except: conflict_vol = 145.0

    # 3. FRED (原油: OIL)
    oil_price = 80.0
    try:
        fred_url = f"https://api.stlouisfed.org/fred/series/observations?series_id=DCOILBRENTEU&api_key={FRED_API_KEY}&file_type=json&sort_order=desc&limit=1"
        oil_price = float(requests.get(fred_url).json()['observations'][0]['value'])
    except: oil_price = 82.5

    # 4. yfinance (軍需株: IRON) - 銘柄を10種類に拡充
    # LMT: ロッキード, RTX: レイセオン, NOC: ノースロップ, GD: ジェネラル・ダイナミクス, BA: ボーイング
    # LHX: L3ハリス, HII: ハンティントン・インガルス, PLTR: パランティア(防衛AI), KTOS: クレイトス(無人機), LDOS: レイドス
    defense_tickers = ["LMT", "RTX", "NOC", "GD", "BA", "LHX", "HII", "PLTR", "KTOS", "LDOS"]
    iron_growth = 0.0
    try:
        stocks = yf.download(defense_tickers, period="1d", interval="15m", progress=False)['Close']
        # 全銘柄の平均騰落率
        iron_growth = stocks.pct_change().mean(axis=1).iloc[-1] * 100
    except: iron_growth = 0.15

    # 5. News API (報道圧力: PRESS)
    press_count = 0
    headlines = []
    try:
        q = '("armed conflict" OR "warfare" OR "missile strike") -sports -entertainment'
        news_url = f'https://newsapi.org/v2/everything?q={q}&sortBy=publishedAt&language=en&apiKey={NEWS_API_KEY}&pageSize=5'
        n_res = requests.get(news_url).json()
        headlines = n_res.get('articles', [])
        press_count = n_res.get('totalResults', 0)
    except: press_count = 500

    # --- 数値から「係数」への変換ロジック ---
    c_factor = 1 + (conflict_vol / 100)      # 混乱係数
    o_factor = oil_price / 75                # 原油補正（75ドルを基準）
    i_factor = 1 + (iron_growth / 20)        # 軍需補正
    p_factor = 1 + (min(press_count, 2000) / 8000) # 報道補正

    morg_usd = 1.0 * c_factor * o_factor * i_factor * p_factor
    morg_jpy = morg_usd * fx_rate
    
    data = {
        "morg_usd": round(morg_usd, 3), "morg_jpy": int(morg_jpy), "fx_rate": round(fx_rate, 2),
        "conflict": round(conflict_vol, 2), "oil": round(oil_price, 2), "iron": round(iron_growth, 3),
        "press": press_count, "p_factor": round(p_factor, 3), "headlines": headlines,
        "time": datetime.now(JST).strftime("%H:%M:%S")
    }
    
    # 履歴に追加
    st.session_state.history.append(data)
    if len(st.session_state.history) > 20: st.session_state.history.pop(0)
    
    return data

current = fetch_morgue_metrics()
history_df = pd.DataFrame(st.session_state.history)

# --- UI ---
st.markdown(f"""
    <div style="display:flex; justify-content:space-between; border-bottom:2px solid #444; padding-bottom:10px;">
        <span style="font-family:'JetBrains Mono'; font-weight:bold; letter-spacing:2px; font-size:20px;">MORGUE TERMINAL v2.0 // ANALYTICS MODE</span>
        <span style="color:#00FF00; font-family:'JetBrains Mono';">● DATA_STREAM: {current['time']} JST</span>
    </div>
""", unsafe_allow_html=True)

st.write("##")

# メインメトリクス
c1, c2, c3 = st.columns([2, 2, 1])
c1.metric("モルグ指数 (円)", f"¥{current['morg_jpy']}")
c2.metric("モルグ指数 (ドル)", f"$ {current['morg_usd']}")
c3.metric("ドル円為替", f"{current['fx_rate']}")

st.divider()

# トレンド分析セクション
st.markdown("### ［ 指数構成要素の推移 ］")
col_t1, col_t2, col_t3 = st.columns(3)

with col_t1:
    st.caption("CONFLICT (混乱度)")
    st.line_chart(history_df['conflict'], height=150, use_container_width=True)
with col_t2:
    st.caption("IRON (軍需平均騰落)")
    st.line_chart(history_df['iron'], height=150, use_container_width=True)
with col_t3:
    st.caption("OIL (原油価格)")
    st.line_chart(history_df['oil'], height=150, use_container_width=True)

st.divider()

# 計算プロセスの透明化
st.markdown("### ［ 指数算出ロジックの透明化 ］")
st.write("現在の市場レートは、以下のアルゴリズムによってリアルタイム算出されています。")

# LaTeX形式で数式を表示
st.latex(r"MORG_{USD} = 1.0 \times \left(1 + \frac{Conflict}{100}\right) \times \frac{Oil}{75} \times \left(1 + \frac{Iron}{20}\right) \times \left(1 + \frac{\min(Press, 2000)}{8000}\right)")

# ステップごとの計算過程
calc_col1, calc_col2 = st.columns(2)
with calc_col1:
    st.markdown(f"""
    **1. 基礎係数の算出**
    *   **混乱係数**: `1 + ({current['conflict']} / 100)` = **{1 + current['conflict']/100:.3f}**
    *   **原油補正**: `{current['oil']} / 75` = **{current['oil']/75:.3f}**
    *   **軍需補正**: `1 + ({current['iron']} / 20)` = **{1 + current['iron']/20:.3f}**
    *   **報道補正**: **{current['p_factor']:.3f}** (記事数: {current['press']})
    """)
with calc_col2:
    st.markdown(f"""
    **2. 最終統合**
    *   **ドルベース単価**: $1.0 × 各係数 = **$ {current['morg_usd']}**
    *   **円換算**: $ {current['morg_usd']} × {current['fx_rate']} (FX)
    *   **最終モルグレート**: **¥ {current['morg_jpy']}**
    """)

st.divider()

# 下部レイアウト
col_left, col_right = st.columns([2, 1])

with col_left:
    st.markdown("### ［ ボラティリティ・チャート ］")
    # ロウソク足（シミュレーション）
    y_vals = history_df['morg_usd'].tolist()
    if len(y_vals) < 5: y_vals = [current['morg_usd'] * (1+np.random.uniform(-0.01,0.01)) for _ in range(10)]
    
    fig = go.Figure(data=[go.Candlestick(
        x=list(range(len(y_vals))),
        open=y_vals[:-1], high=[v*1.002 for v in y_vals[:-1]],
        low=[v*0.998 for v in y_vals[:-1]], close=y_vals[1:],
        increasing_line_color='#FFFFFF', decreasing_line_color='#FF0000',
        increasing_fillcolor='#111', decreasing_fillcolor='#FF0000'
    )])
    fig.update_layout(template="plotly_dark", height=350, margin=dict(l=0,r=0,b=0,t=0), xaxis_rangeslider_visible=False)
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