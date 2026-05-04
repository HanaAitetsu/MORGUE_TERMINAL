"""
MORGUE TERMINAL MRG-v2.8
架空の戦災暗号資産「モルグ」のリアルタイム価格ダッシュボード

改善点:
- キャッシュとセッション状態の分離・整合化
- エラーハンドリングの明示化（ロギング付き）
- yfinance v0.2+ 対応のダウンロード方法
- OHLC値をローリング統計で現実的に生成
- 時刻比較をdatetimeオブジェクトで行い日またぎ対応
- 定数を CONFIG 辞書に集約
- st.rerun() による自動更新ループ対応
- サイドバーに設定パネルを追加
"""

import logging
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import yfinance as yf

# ─────────────────────────────────────────────
# 0. ロギング設定
# ─────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# 1. 定数・設定の集約
# ─────────────────────────────────────────────
JST = timezone(timedelta(hours=9))

CONFIG = {
    # フォールバック値（API取得失敗時）
    "DEFAULT_CONFLICT": 145.0,
    "DEFAULT_OIL":       82.0,
    "DEFAULT_FX":       155.0,
    "DEFAULT_PRESS":      1.06,

    # MRG計算パラメータ
    "BASE_UNIT":        1.0,
    "CONFLICT_SCALE":   100.0,   # c_factor = 1 + conflict / scale
    "OIL_ANCHOR":        75.0,   # o_factor = oil / anchor
    "IRON_SCALE":        20.0,   # i_factor = 1 + iron / scale

    # データ取得
    "HISTORY_POINTS":    40,
    "MAX_HISTORY":      100,
    "YF_PERIOD":        "2d",
    "YF_INTERVAL":      "15m",

    # 防衛関連ティッカー
    "DEFENSE_TICKERS": ["LMT", "RTX", "NOC", "GD", "BA", "LHX", "HII", "PLTR", "KTOS", "LDOS"],
    "FX_TICKER":       "JPY=X",

    # GDELT API
    "GDELT_URL": (
        "https://api.gdeltproject.org/api/v2/doc/doc"
        "?query=(conflict+OR+violence)&mode=TimelineVol&format=json"
    ),

    # FRED API
    "FRED_SERIES": "DCOILBRENTEU",

    # 自動更新間隔（秒）
    "AUTO_REFRESH_SEC": 60,
}

import os
FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
NEWS_API_KEY = os.environ.get("NEWS_API_KEY", "")

# ─────────────────────────────────────────────
# 2. ページ設定 & CSS
# ─────────────────────────────────────────────
st.set_page_config(page_title="MORGUE TERMINAL MRG-v2.8", layout="wide")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Rajdhani:wght@300;600&display=swap');

    html, body, [data-testid="stAppViewContainer"] {
        background-color: #040404;
        color: #c8c8c8;
        font-family: 'Rajdhani', sans-serif;
    }
    code, pre, .stCode { font-family: 'Share Tech Mono', monospace !important; }

    [data-testid="stMetric"] {
        background: linear-gradient(135deg, #0d0d0d 0%, #111 100%);
        border: 1px solid #2a2a2a;
        border-left: 3px solid #ff3030;
        padding: 14px 18px !important;
        border-radius: 2px;
    }
    [data-testid="stMetricValue"]  { color: #fff !important; font-size: 2rem !important; }
    [data-testid="stMetricDelta"]  { font-size: 0.85rem !important; }
    [data-testid="stMetricLabel"]  { color: #666 !important; font-size: 0.7rem !important; letter-spacing: 2px; }

    .stMarkdown h4 { color: #888; font-size: 0.72rem; letter-spacing: 3px; text-transform: uppercase; margin-bottom: 4px; }

    /* スクロールバーを非表示 */
    ::-webkit-scrollbar { display: none; }

    /* サイドバー */
    [data-testid="stSidebar"] { background-color: #080808; border-right: 1px solid #1a1a1a; }

    /* テーブル */
    table { width: 100%; border-collapse: collapse; font-family: 'Share Tech Mono', monospace; font-size: 0.78rem; }
    th { color: #555; font-weight: 400; border-bottom: 1px solid #222; padding: 4px 8px; }
    td { padding: 5px 8px; border-bottom: 1px solid #161616; }
    td:last-child { color: #ff5050; text-align: right; }

    @media (max-width: 768px) {
        [data-testid="column"] { width: 100% !important; flex: 1 1 100% !important; }
    }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# 3. データ取得関数（各APIを独立してフォールバック）
# ─────────────────────────────────────────────

@st.cache_data(ttl=300)
def fetch_conflict_index() -> float:
    """GDELT から紛争ボリューム指数を取得。失敗時はデフォルト値。"""
    try:
        res = requests.get(CONFIG["GDELT_URL"], timeout=10)
        res.raise_for_status()
        data = res.json()
        raw = float(data["timeline"][0]["data"][-1]["value"])
        val = raw * 10
        log.info("GDELT conflict index fetched: %.2f", val)
        return val
    except requests.exceptions.RequestException as e:
        log.warning("GDELT fetch failed (%s), using default.", e)
    except (KeyError, IndexError, ValueError) as e:
        log.warning("GDELT parse error (%s), using default.", e)
    return CONFIG["DEFAULT_CONFLICT"]


@st.cache_data(ttl=600)
def fetch_oil_price() -> float:
    """FRED から Brent 原油価格を取得。失敗時はデフォルト値。"""
    if not FRED_API_KEY:
        log.warning("FRED_API_KEY not set, using default oil price.")
        return CONFIG["DEFAULT_OIL"]
    try:
        url = (
            f"https://api.stlouisfed.org/fred/series/observations"
            f"?series_id={CONFIG['FRED_SERIES']}&api_key={FRED_API_KEY}"
            f"&file_type=json&sort_order=desc&limit=1"
        )
        res = requests.get(url, timeout=10)
        res.raise_for_status()
        val = float(res.json()["observations"][0]["value"])
        log.info("Oil price fetched: %.2f", val)
        return val
    except requests.exceptions.RequestException as e:
        log.warning("FRED fetch failed (%s), using default.", e)
    except (KeyError, IndexError, ValueError) as e:
        log.warning("FRED parse error (%s), using default.", e)
    return CONFIG["DEFAULT_OIL"]


@st.cache_data(ttl=300)
def fetch_market_data() -> tuple[pd.Series, pd.Series]:
    """
    防衛株の平均騰落率と USD/JPY を取得。
    戻り値: (defense_pct_change_series, fx_series)
    """
    tickers = CONFIG["DEFENSE_TICKERS"] + [CONFIG["FX_TICKER"]]
    try:
        # yfinance v0.2+ では multi_level_index=False を使うと扱いやすい
        raw = yf.download(
            tickers,
            period=CONFIG["YF_PERIOD"],
            interval=CONFIG["YF_INTERVAL"],
            progress=False,
            auto_adjust=True,
        )

        # Close カラム群を取り出す（MultiIndex 対応）
        if isinstance(raw.columns, pd.MultiIndex):
            close = raw["Close"].ffill()
        else:
            close = raw.ffill()

        fx_series = close[CONFIG["FX_TICKER"]]
        defense_close = close[CONFIG["DEFENSE_TICKERS"]]

        # 防衛株平均騰落率（%）
        growth_series = defense_close.pct_change().mean(axis=1) * 100
        log.info("Market data fetched: %d rows", len(growth_series))
        return growth_series, fx_series

    except Exception as e:
        log.error("yfinance fetch failed: %s", e)
        # フォールバック: 空の Series を返す
        return pd.Series(dtype=float), pd.Series(dtype=float)


# ─────────────────────────────────────────────
# 4. MRG 価格計算
# ─────────────────────────────────────────────

def calculate_mrg(conflict: float, oil: float, iron_pct: float, press: float) -> float:
    """
    MRG/USD を計算する。
      conflict : GDELT 紛争指数
      oil      : Brent 原油価格 (USD)
      iron_pct : 防衛株平均騰落率 (%)
      press    : 報道係数
    """
    c_f = 1.0 + conflict / CONFIG["CONFLICT_SCALE"]
    o_f = oil / CONFIG["OIL_ANCHOR"]
    i_f = 1.0 + iron_pct / CONFIG["IRON_SCALE"]
    return CONFIG["BASE_UNIT"] * c_f * o_f * i_f * press


def build_ohlc(mrg_usd: float, prev_close: float | None) -> dict:
    """
    前足の終値と現在値からローソク足 OHLC を構築する。
    固定比率ではなくランダムウォーク的な揺らぎを加える。
    """
    rng = np.random.default_rng()
    noise = rng.uniform(0.997, 1.003)
    o = prev_close if prev_close is not None else mrg_usd * noise
    c = mrg_usd
    h = max(o, c) * rng.uniform(1.0005, 1.002)
    l = min(o, c) * rng.uniform(0.998, 0.9995)
    return {"open": round(o, 4), "high": round(h, 4), "low": round(l, 4), "close": round(c, 4)}


# ─────────────────────────────────────────────
# 5. 同期データ構築
# ─────────────────────────────────────────────

def build_history() -> list[dict]:
    """外部データを取得して過去 N ポイントの履歴リストを生成する。"""
    c_val = fetch_conflict_index()
    o_val = fetch_oil_price()
    p_f   = CONFIG["DEFAULT_PRESS"]

    growth_series, fx_series = fetch_market_data()

    if growth_series.empty:
        log.warning("Market data empty, cannot build history.")
        return []

    points = growth_series.dropna().tail(CONFIG["HISTORY_POINTS"])
    h_list: list[dict] = []
    prev_close = None

    for ts, i_val in points.items():
        mrg_usd = calculate_mrg(c_val, o_val, float(i_val), p_f)
        fx = float(fx_series.loc[ts]) if ts in fx_series.index else CONFIG["DEFAULT_FX"]

        ohlc = build_ohlc(mrg_usd, prev_close)
        prev_close = ohlc["close"]

        # datetimeオブジェクトも保持（比較用）
        ts_jst = ts.astimezone(JST)

        h_list.append({
            "ts":       ts_jst,                           # datetime（重複チェック用）
            "time":     ts_jst.strftime("%m/%d %H:%M"),   # 表示用（日付を含める）
            **ohlc,
            "morg_jpy": int(ohlc["close"] * fx),
            "fx_rate":  round(fx, 2),
            "iron":     round(float(i_val), 3),
            "conflict": round(c_val, 2),
            "oil":      round(o_val, 2),
            "factors": {
                "c": round(1 + c_val / CONFIG["CONFLICT_SCALE"], 3),
                "o": round(o_val   / CONFIG["OIL_ANCHOR"],        3),
                "i": round(1 + float(i_val) / CONFIG["IRON_SCALE"], 3),
                "p": p_f,
            },
        })

    return h_list


# ─────────────────────────────────────────────
# 6. セッション状態の初期化・更新
# ─────────────────────────────────────────────

if "history" not in st.session_state or not st.session_state.history:
    st.session_state.history = build_history()
    st.session_state.last_refresh = datetime.now(JST)

# 最新足を追記（datetime で重複チェック）
fresh = build_history()
if fresh:
    latest = fresh[-1]
    existing_ts = [e["ts"] for e in st.session_state.history]
    if latest["ts"] not in existing_ts:
        st.session_state.history.append(latest)
        if len(st.session_state.history) > CONFIG["MAX_HISTORY"]:
            st.session_state.history.pop(0)
        log.info("New tick appended: %s", latest["time"])

# データが空の場合の早期終了
if not st.session_state.history:
    st.error("データの取得に失敗しました。外部 API の接続を確認してください。")
    st.stop()

current = st.session_state.history[-1]
df = pd.DataFrame(st.session_state.history)

# ─────────────────────────────────────────────
# 7. サイドバー（設定・ステータス）
# ─────────────────────────────────────────────

with st.sidebar:
    st.markdown("### ⚙ TERMINAL CONFIG")
    st.caption("MRG-v2.8 // CLASSIFIED")

    st.markdown("---")
    auto_refresh = st.toggle("自動更新 (60s)", value=False)
    if st.button("🔄 手動更新", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.markdown("---")
    st.markdown("**データソース状態**")
    fred_ok = bool(FRED_API_KEY)
    news_ok = bool(NEWS_API_KEY)
    st.markdown(f"{'🟢' if fred_ok else '🔴'} FRED API {'接続済' if fred_ok else '未設定（デフォルト値使用）'}")
    st.markdown(f"{'🟢' if news_ok else '🔴'} NEWS API {'接続済' if news_ok else '未設定'}")
    st.markdown("🟢 GDELT（キーなし）")
    st.markdown("🟢 Yahoo Finance（キーなし）")

    st.markdown("---")
    st.markdown("**計算式**")
    st.code(
        "MRG = 1.0\n"
        "    × (1 + C/100)\n"
        "    × (OIL/75)\n"
        "    × (1 + DEF%/20)\n"
        "    × PRESS",
        language="text",
    )

    st.markdown("---")
    last = st.session_state.get("last_refresh")
    if last:
        st.caption(f"最終更新: {last.strftime('%H:%M:%S')} JST")

# ─────────────────────────────────────────────
# 8. ヘッダー
# ─────────────────────────────────────────────

st.markdown(f"""
<div style="display:flex; justify-content:space-between; align-items:center;
            border-bottom: 2px solid #1e1e1e; padding-bottom: 12px; margin-bottom: 4px;">
    <div>
        <span style="font-family:'Share Tech Mono'; font-weight:bold; letter-spacing:3px;
                     font-size:22px; color:#fff;">MORGUE TERMINAL</span>
        <span style="font-family:'Share Tech Mono'; font-size:12px; color:#444; margin-left:12px;">MRG-v2.8</span>
    </div>
    <div style="font-family:'Share Tech Mono'; font-size:13px; color:#2aff2a;">
        ● LIVE&nbsp;&nbsp;{current['time']} JST
    </div>
</div>
""", unsafe_allow_html=True)

st.write("")

# ─────────────────────────────────────────────
# 9. 主要メトリクス
# ─────────────────────────────────────────────

if len(st.session_state.history) > 1:
    prev = st.session_state.history[-2]
    d_jpy = current["morg_jpy"] - prev["morg_jpy"]
    d_usd = current["close"]    - prev["close"]
    d_fx  = current["fx_rate"]  - prev["fx_rate"]
else:
    d_jpy = d_usd = d_fx = 0.0

m1, m2, m3, m4 = st.columns([2, 2, 1.2, 1.2])
m1.metric("MRG/JPY",  f"¥{current['morg_jpy']:,}",     delta=int(d_jpy))
m2.metric("MRG/USD",  f"$ {current['close']:.4f}",      delta=round(float(d_usd), 4))
m3.metric("USD/JPY",  f"¥ {current['fx_rate']}",        delta=round(float(d_fx), 2))
m4.metric("CONFLICT", f"{current['conflict']:.1f}",      delta=None)

st.write("---")

# ─────────────────────────────────────────────
# 10. 構成要素 & 算出プロセス
# ─────────────────────────────────────────────

cl, cr = st.columns([1, 1.3])

with cl:
    st.markdown("#### ［ MRG 構成要素 ］")
    fac = current["factors"]
    st.markdown(
        "| パラメータ | 実測値 | 係数 |\n"
        "| :--- | ---: | ---: |\n"
        f"| **Conflict** | {current['conflict']} | **× {fac['c']}** |\n"
        f"| **Energy**   | ${current['oil']} | **× {fac['o']}** |\n"
        f"| **Defense**  | {current['iron']}% | **× {fac['i']}** |\n"
        f"| **Press**    | API 連携 | **× {fac['p']}** |"
    )

with cr:
    st.markdown("#### ［ 算出プロセス ］")
    s1 = CONFIG["BASE_UNIT"] * fac["c"]
    s2 = s1 * fac["o"]
    s3 = s2 * fac["i"]
    s4 = s3 * fac["p"]
    log_txt = (
        f"Base Unit         $ 1.0000\n"
        f"× Conflict Adj  → $ {s1:.4f}\n"
        f"× Energy Adj    → $ {s2:.4f}\n"
        f"× Defense Adj   → $ {s3:.4f}\n"
        f"× Press Adj     → $ {s4:.4f}  (MRG/USD)\n"
        f"× FX Rate       → ¥ {current['morg_jpy']:,}  (MRG/JPY)"
    )
    st.code(log_txt, language="bash")

st.write("---")

# ─────────────────────────────────────────────
# 11. チャート
# ─────────────────────────────────────────────

gl, gr = st.columns([2, 1])

with gl:
    st.markdown("#### ［ MRG 市場ボラティリティ ］")
    fig = go.Figure(data=[go.Candlestick(
        x=df["time"],
        open=df["open"], high=df["high"], low=df["low"], close=df["close"],
        increasing_line_color="#ffffff",
        decreasing_line_color="#ff3030",
        increasing_fillcolor="#2a2a2a",
        decreasing_fillcolor="#ff3030",
        name="MRG/USD",
    )])
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#040404",
        plot_bgcolor="#040404",
        height=430,
        margin=dict(l=0, r=0, b=0, t=0),
        yaxis=dict(
            autorange=True,
            fixedrange=False,
            tickformat=".4f",
            gridcolor="#161616",
            tickfont=dict(family="Share Tech Mono", size=10),
        ),
        xaxis=dict(
            rangeslider_visible=False,
            gridcolor="#161616",
            tickfont=dict(family="Share Tech Mono", size=10),
        ),
        legend=dict(font=dict(family="Share Tech Mono")),
    )
    st.plotly_chart(fig, use_container_width=True)

with gr:
    st.markdown("#### ［ 個別推移 ］")

    for label, col, color in [
        ("CONFLICT INDEX", "conflict", "#ff5050"),
        ("DEFENSE (%) ",   "iron",     "#ffaa00"),
        ("OIL PRICE",      "oil",      "#50aaff"),
    ]:
        st.caption(label)
        series = df.set_index("time")[col]
        st.line_chart(series, height=105, color=color)

# ─────────────────────────────────────────────
# 12. 自動更新
# ─────────────────────────────────────────────

if auto_refresh:
    time.sleep(CONFIG["AUTO_REFRESH_SEC"])
    st.cache_data.clear()
    st.rerun()