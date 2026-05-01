import streamlit as st
import pandas as pd
import yfinance as yf
import requests
import plotly.graph_objects as go
import numpy as np
from datetime import datetime

# API設定
FRED_API_KEY = "9da80d9dfe6c007030db83ac4a2c4e49"
NEWS_API_KEY = "ead9b39074f34da79d3e308e4cec6780"
ACLED_EMAIL = "otomeiker0410@gmail.com"
ACLED_PASSWORD = "MyTUdNhuzE2Fkv@"

def local_css(file_name):
    try:
        with open(file_name, encoding="utf-8") as f:
            st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)
    except FileNotFoundError:
        pass

st.set_page_config(page_title="MORGUE TERMINAL", layout="wide")
local_css("style.css")

@st.cache_data(ttl=900)
def get_acled_token():
    auth_url = "https://acleddata.com/oauth/token"
    payload = {
        "username": ACLED_EMAIL, "password": ACLED_PASSWORD,
        "grant_type": "password", "client_id": "acled", "scope": "authenticated"
    }
    try:
        res = requests.post(auth_url, data=payload, timeout=5)
        return res.json().get("access_token")
    except: return None

@st.cache_data(ttl=900)
def fetch_all_metrics():
    # 1. ACLED (死者数)
    fatalities = 0
    try:
        token = get_acled_token()
        if token:
            headers = {"Authorization": f"Bearer {token}"}
            acled_url = "https://acleddata.com/api/read"
            res = requests.get(acled_url, headers=headers, params={"limit": 100}, timeout=5)
            fatalities = sum([int(e.get('fatalities', 0)) for e in res.json().get('data', [])])
    except: pass

    # 2. FRED (原油価格)
    oil_price = 80.0
    try:
        fred_url = f"https://api.stlouisfed.org/fred/series/observations?series_id=DCOILBRENTEU&api_key={FRED_API_KEY}&file_type=json&sort_order=desc&limit=1"
        oil_price = float(requests.get(fred_url).json()['observations'][0]['value'])
    except: pass

    # 3. yfinance (軍需株)
    defense_growth = 0
    try:
        tickers = ["LMT", "NOC", "RTX"]
        stock_data = yf.download(tickers, period="2d", interval="15m")['Close']
        defense_growth = stock_data.pct_change().mean(axis=1).iloc[-1]
    except: pass

    # 価格計算
    price_usd = 1.0 * (1 + (fatalities/100)) * (oil_price/70) * (1 + (defense_growth * 5))
    
    return {
        "morg_usd": round(price_usd, 3),
        "morg_jpy": int(price_usd * 155),
        "fatalities": fatalities,
        "oil": oil_price,
        "iron_idx": round(defense_growth * 100, 2),
        "sync": datetime.now().strftime("%H:%M:%S")
    }

try:
    data = fetch_all_metrics()

    # ヘッダー
    st.markdown(f"""
        <div class="header-container">
            <span class="system-title">MORGUE INDEX SYSTEM // モルグ指数ターミナル</span>
            <span class="status-tag">● 稼働中 // 同期: {data['sync']}</span>
        </div>
    """, unsafe_allow_html=True)

    st.write("##")

    # メイン指標
    c1, c2 = st.columns(2)
    c1.metric("MORG/JPY", f"¥{data['morg_jpy']}")
    c2.metric("MORG/USD", f"$ {data['morg_usd']}")

    st.write("##")

    # サブ指標
    c3, c4, c5 = st.columns(3)
    c3.metric("軍需指数 (IRON)", f"{data['iron_idx']}%")
    c4.metric("最新犠牲者数 (BLOOD)", data['fatalities'])
    c5.metric("原油価格 (OIL)", f"${data['oil']}")

    st.divider()

    # ロウソク足チャート (エラー修正済み)
    st.text("市場変動推移 (15分足)")
    
    periods = 20
    df_hist = pd.DataFrame({
        'Time': pd.date_range(end=datetime.now(), periods=periods, freq='15min'),
        'Open': [data['morg_usd'] * (1 + np.random.uniform(-0.01, 0.01)) for _ in range(periods)],
        'Close': [data['morg_usd'] * (1 + np.random.uniform(-0.01, 0.01)) for _ in range(periods)],
    })
    df_hist['High'] = df_hist[['Open', 'Close']].max(axis=1) * 1.005
    df_hist['Low'] = df_hist[['Open', 'Close']].min(axis=1) * 0.995

    fig = go.Figure(data=[go.Candlestick(
        x=df_hist['Time'], open=df_hist['Open'], high=df_hist['High'],
        low=df_hist['Low'], close=df_hist['Close'],
        increasing_line_color='#FFFFFF', decreasing_line_color='#FF0000',
        increasing_fillcolor='#050505', decreasing_fillcolor='#FF0000' # ここを修正
    )])
    fig.update_layout(template="plotly_dark", height=350, margin=dict(l=0,r=0,b=0,t=0), xaxis_rangeslider_visible=False)
    st.plotly_chart(fig, use_container_width=True)

    # 計算に使われた数値の表記
    st.write("##")
    st.markdown("### ［ 計算根拠データ ］")
    st.code(f"""
    取得時刻: {data['sync']}
    -------------------------------------------
    紛争犠牲者数 (ACLED): {data['fatalities']} 名
    原油価格 (FRED/Brent): ${data['oil']}
    軍需株平均騰落率 (LMT/NOC/RTX): {data['iron_idx']}%
    適用為替レート: 1 USD = 155 JPY
    -------------------------------------------
    算出式: Base * (1 + 犠牲者数/100) * (原油/70) * (1 + 軍需成長*5)
    """)

except Exception as e:
    st.error(f"システム停止中: {e}")