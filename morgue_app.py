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

st.set_page_config(page_title="MORGUE TERMINAL v2.2", layout="wide")

def local_css(file_name):
    try:
        with open(file_name, encoding="utf-8") as f:
            st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)
    except: pass
local_css("style.css")

if 'history' not in st.session_state:
    st.session_state.history = []

# --- 過去データの初期取得 ---
@st.cache_data(ttl=3600)
def get_initial_history():
    defense_tickers = ["LMT", "RTX", "NOC", "GD", "BA", "LHX", "HII", "PLTR", "KTOS", "LDOS"]
    h_data = []
    try:
        stocks = yf.download(defense_tickers, period="1d", interval="15m", progress=False)['Close']
        growth = stocks.pct_change().mean(axis=1) * 100
        
        # 過去データから計算
        for ts, val in growth.tail(15).items():
            # NaN（空データ）を排除
            clean_val = 0.0 if pd.isna(val) else float(val)
            h_data.append({
                "time": ts.astimezone(JST).strftime("%H:%M"),
                "iron": round(clean_val, 3),
                "conflict": 140.0 + np.random.uniform(-5, 5),
                "oil": 82.0 + np.random.uniform(-1, 1),
                "morg_usd": 1.2 + np.random.uniform(-0.05, 0.05)
            })
    except: pass
    return h_data

if not st.session_state.history:
    st.session_state.history = get_initial_history()

# --- 最新データ取得 ---
@st.cache_data(ttl=600)
def fetch_latest():
    # 1. 為替レート (確実にスカラー値で取得)
    fx_rate = 155.0
    try:
        fx_data = yf.download("JPY=X", period="1d", interval="5m", progress=False)
        # .values[-1] を使うのが最も安全
        fx_rate = float(fx_data['Close'].values[-1])
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

    # 4. yfinance (軍需騰落)
    defense_tickers = ["LMT", "RTX", "NOC", "GD", "BA", "LHX", "HII", "PLTR", "KTOS", "LDOS"]
    iron_growth = 0.1
    try:
        stocks = yf.download(defense_tickers, period="1d", interval="5m", progress=False)['Close']
        raw_growth = stocks.pct_change().mean(axis=1).iloc[-1] * 100
        iron_growth = float(raw_growth)
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
        "morg_jpy": int(morg_usd * fx_rate), # ここでエラーが起きないよう各変数をfloat化済み
        "fx_rate": round(fx_rate, 2),
        "conflict": round(conflict_vol, 2),
        "iron": round(iron_growth, 3),
        "oil": round(oil_price, 2),
        "press": press_count,
        "p_factor": round(p_factor, 3),
        "headlines": headlines
    }
    
    if not st.session_state.history or st.session_state.history[-1]['time'] != current['time']:
        st.session_state.history.append(current)
        if len(st.session_state.history) > 30: st.session_state.history.pop(0)
        
    return current

current = fetch_latest()
history_df = pd.DataFrame(st.session_state.history)

# --- 以下、UI部分は v2.1 と同様につき省略可 ---
# (中略) 
st.markdown(f"### SYNC: {current['time']} JST")
# ...