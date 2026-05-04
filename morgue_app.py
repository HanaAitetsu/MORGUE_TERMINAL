"""
MORGUE TERMINAL MRG-v2.8
架空の戦災暗号資産「モルグ」のリアルタイム価格ダッシュボード

v3改善点:
- 文字色を灰色から読みやすい白・黄・緑系に強化
- 係数の導出式（生値 → 式 → 係数値）を詳細表示
- 累積乗算の全ステップを可視化
- ローソク足チャートが「架空通貨シミュレーション」であることを明示
- 個別推移グラフに係数値も追加
"""

import logging
import os
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
    "DEFAULT_CONFLICT": 145.0,
    "DEFAULT_OIL":       82.0,
    "DEFAULT_FX":       155.0,
    "DEFAULT_PRESS":      1.06,
    "BASE_UNIT":          1.0,
    "CONFLICT_SCALE":   100.0,
    "OIL_ANCHOR":        75.0,
    "IRON_SCALE":        20.0,
    "HISTORY_POINTS":    40,
    "MAX_HISTORY":      100,
    "YF_PERIOD":        "2d",
    "YF_INTERVAL":      "15m",
    "DEFENSE_TICKERS": ["LMT", "RTX", "NOC", "GD", "BA", "LHX", "HII", "PLTR", "KTOS", "LDOS"],
    "FX_TICKER":       "JPY=X",
    "GDELT_URL": (
        "https://api.gdeltproject.org/api/v2/doc/doc"
        "?query=(conflict+OR+violence)&mode=TimelineVol&format=json"
    ),
    "FRED_SERIES": "DCOILBRENTEU",
    "AUTO_REFRESH_SEC": 60,
}

FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
NEWS_API_KEY = os.environ.get("NEWS_API_KEY", "")

# ─────────────────────────────────────────────
# 2. ページ設定 & CSS
# ─────────────────────────────────────────────
st.set_page_config(page_title="MORGUE TERMINAL MRG-v2.8", layout="wide")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Rajdhani:wght@400;600;700&display=swap');

    /* ベース */
    html, body, [data-testid="stAppViewContainer"] {
        background-color: #040404;
        color: #e8e8e8;
        font-family: 'Rajdhani', sans-serif;
        font-size: 15px;
    }
    p, li, span { color: #e8e8e8; }
    code, pre, .stCode { font-family: 'Share Tech Mono', monospace !important; }

    /* stCode ブロック内テキストを明るく */
    .stCode code { color: #f0e68c !important; background: #0a0a0a !important; }

    /* メトリクスカード */
    [data-testid="stMetric"] {
        background: linear-gradient(135deg, #0d0d0d 0%, #111 100%);
        border: 1px solid #2a2a2a;
        border-left: 3px solid #ff3030;
        padding: 14px 18px !important;
        border-radius: 2px;
    }
    [data-testid="stMetricValue"]  { color: #ffffff !important; font-size: 2rem !important; font-weight: 700; }
    [data-testid="stMetricDelta"]  { font-size: 0.85rem !important; }
    [data-testid="stMetricLabel"]  { color: #aaaaaa !important; font-size: 0.72rem !important; letter-spacing: 2px; }

    /* セクション見出し */
    .stMarkdown h4 {
        color: #cccccc !important;
        font-size: 0.72rem;
        letter-spacing: 3px;
        text-transform: uppercase;
        margin-bottom: 6px;
    }

    /* caption */
    [data-testid="stCaptionContainer"] p { color: #bbbbbb !important; font-size: 0.72rem; letter-spacing: 2px; }

    /* テーブル */
    table { width: 100%; border-collapse: collapse; font-family: 'Share Tech Mono', monospace; font-size: 0.8rem; }
    th { color: #aaaaaa !important; font-weight: 400; border-bottom: 1px solid #2a2a2a; padding: 5px 10px; }
    td { padding: 6px 10px; border-bottom: 1px solid #1a1a1a; color: #e8e8e8; }
    td:nth-child(2) { color: #7dd3fc; } /* 実測値: 水色 */
    td:nth-child(3) { color: #fde68a; text-align: right; } /* 係数: 黄色 */
    strong { color: #ffffff; }

    /* 計算過程パネル */
    .calc-panel {
        background: #080808;
        border: 1px solid #222;
        border-radius: 3px;
        padding: 14px 16px;
        font-family: 'Share Tech Mono', monospace;
        font-size: 0.8rem;
        line-height: 2;
    }
    .calc-raw   { color: #7dd3fc; }  /* 生の実測値: 水色 */
    .calc-eq    { color: #888888; }  /* 式の説明: 灰 */
    .calc-coef  { color: #fde68a; }  /* 係数値: 黄 */
    .calc-step  { color: #86efac; }  /* 中間結果: 緑 */
    .calc-final { color: #ff6b6b; font-weight: bold; } /* 最終結果: 赤 */
    .calc-jpy   { color: #f9a8d4; font-weight: bold; } /* JPY: ピンク */
    .calc-label { color: #aaaaaa; } /* ラベル: 明るい灰 */
    .calc-divider { color: #333; }

    /* スクロールバー非表示 */
    ::-webkit-scrollbar { display: none; }

    /* サイドバー */
    [data-testid="stSidebar"] { background-color: #060606; border-right: 1px solid #1a1a1a; }
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] span,
    [data-testid="stSidebar"] label { color: #cccccc !important; }
    [data-testid="stSidebar"] h3 { color: #ffffff !important; }

    /* チャートキャプション注記 */
    .sim-badge {
        display: inline-block;
        background: #1a1000;
        border: 1px solid #554400;
        color: #fde68a;
        font-family: 'Share Tech Mono', monospace;
        font-size: 0.68rem;
        padding: 2px 8px;
        border-radius: 2px;
        letter-spacing: 1px;
        margin-left: 8px;
        vertical-align: middle;
    }

    @media (max-width: 768px) {
        [data-testid="column"] { width: 100% !important; flex: 1 1 100% !important; }
    }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# 3. データ取得関数
# ─────────────────────────────────────────────

@st.cache_data(ttl=300)
def fetch_conflict_index() -> float:
    try:
        res = requests.get(CONFIG["GDELT_URL"], timeout=10)
        res.raise_for_status()
        raw = float(res.json()["timeline"][0]["data"][-1]["value"])
        val = raw * 10
        log.info("GDELT conflict index: %.2f", val)
        return val
    except requests.exceptions.RequestException as e:
        log.warning("GDELT fetch failed (%s)", e)
    except (KeyError, IndexError, ValueError) as e:
        log.warning("GDELT parse error (%s)", e)
    return CONFIG["DEFAULT_CONFLICT"]


@st.cache_data(ttl=600)
def fetch_oil_price() -> float:
    if not FRED_API_KEY:
        log.warning("FRED_API_KEY not set, using default.")
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
        log.info("Oil price: %.2f", val)
        return val
    except requests.exceptions.RequestException as e:
        log.warning("FRED fetch failed (%s)", e)
    except (KeyError, IndexError, ValueError) as e:
        log.warning("FRED parse error (%s)", e)
    return CONFIG["DEFAULT_OIL"]


@st.cache_data(ttl=300)
def fetch_market_data() -> tuple[pd.Series, pd.Series]:
    tickers = CONFIG["DEFENSE_TICKERS"] + [CONFIG["FX_TICKER"]]
    try:
        raw = yf.download(
            tickers,
            period=CONFIG["YF_PERIOD"],
            interval=CONFIG["YF_INTERVAL"],
            progress=False,
            auto_adjust=True,
        )
        close = raw["Close"].ffill() if isinstance(raw.columns, pd.MultiIndex) else raw.ffill()
        fx_series      = close[CONFIG["FX_TICKER"]]
        defense_close  = close[CONFIG["DEFENSE_TICKERS"]]
        growth_series  = defense_close.pct_change().mean(axis=1) * 100
        log.info("Market data: %d rows", len(growth_series))
        return growth_series, fx_series
    except Exception as e:
        log.error("yfinance fetch failed: %s", e)
        return pd.Series(dtype=float), pd.Series(dtype=float)


# ─────────────────────────────────────────────
# 4. 計算ロジック
# ─────────────────────────────────────────────

def calculate_mrg_with_steps(conflict: float, oil: float, iron_pct: float, press: float) -> dict:
    """
    MRG/USD を計算し、各ステップの中間値と導出式も返す。
    """
    c_f  = 1.0 + conflict / CONFIG["CONFLICT_SCALE"]
    o_f  = oil            / CONFIG["OIL_ANCHOR"]
    i_f  = 1.0 + iron_pct / CONFIG["IRON_SCALE"]
    p_f  = press

    s0 = CONFIG["BASE_UNIT"]
    s1 = s0 * c_f
    s2 = s1 * o_f
    s3 = s2 * i_f
    s4 = s3 * p_f

    return {
        "mrg_usd": s4,
        "factors": {
            "c": round(c_f, 4),
            "o": round(o_f, 4),
            "i": round(i_f, 4),
            "p": round(p_f, 4),
        },
        "steps": {
            "s0": round(s0, 4),
            "s1": round(s1, 4),
            "s2": round(s2, 4),
            "s3": round(s3, 4),
            "s4": round(s4, 4),
        },
        "derivations": {
            # 式文字列（表示用）
            "c": f"1 + {conflict:.2f} ÷ {CONFIG['CONFLICT_SCALE']:.0f}",
            "o": f"{oil:.2f} ÷ {CONFIG['OIL_ANCHOR']:.0f}",
            "i": f"1 + ({iron_pct:.4f}) ÷ {CONFIG['IRON_SCALE']:.0f}",
            "p": "報道係数（固定）",
        },
    }


def build_ohlc(mrg_usd: float, prev_close: float | None) -> dict:
    """前足終値ベースのローソク足 OHLC を生成（架空通貨シミュレーション）。"""
    rng   = np.random.default_rng()
    o     = prev_close if prev_close is not None else mrg_usd * rng.uniform(0.997, 1.003)
    c     = mrg_usd
    h     = max(o, c) * rng.uniform(1.0005, 1.002)
    l     = min(o, c) * rng.uniform(0.998, 0.9995)
    return {"open": round(o, 4), "high": round(h, 4), "low": round(l, 4), "close": round(c, 4)}


# ─────────────────────────────────────────────
# 5. 履歴構築
# ─────────────────────────────────────────────

def build_history() -> list[dict]:
    c_val = fetch_conflict_index()
    o_val = fetch_oil_price()
    p_f   = CONFIG["DEFAULT_PRESS"]

    growth_series, fx_series = fetch_market_data()
    if growth_series.empty:
        log.warning("Market data empty.")
        return []

    points    = growth_series.dropna().tail(CONFIG["HISTORY_POINTS"])
    h_list: list[dict] = []
    prev_close = None

    for ts, i_val in points.items():
        calc   = calculate_mrg_with_steps(c_val, o_val, float(i_val), p_f)
        fx     = float(fx_series.loc[ts]) if ts in fx_series.index else CONFIG["DEFAULT_FX"]
        ohlc   = build_ohlc(calc["mrg_usd"], prev_close)
        prev_close = ohlc["close"]
        ts_jst = ts.astimezone(JST)

        h_list.append({
            "ts":       ts_jst,
            "time":     ts_jst.strftime("%m/%d %H:%M"),
            **ohlc,
            "morg_jpy": int(ohlc["close"] * fx),
            "fx_rate":  round(fx, 2),
            "iron":     round(float(i_val), 4),
            "conflict": round(c_val, 2),
            "oil":      round(o_val, 2),
            "factors":     calc["factors"],
            "steps":       calc["steps"],
            "derivations": calc["derivations"],
        })

    return h_list


# ─────────────────────────────────────────────
# 6. セッション状態の初期化・更新
# ─────────────────────────────────────────────

if "history" not in st.session_state or not st.session_state.history:
    st.session_state.history     = build_history()
    st.session_state.last_refresh = datetime.now(JST)

fresh = build_history()
if fresh:
    latest     = fresh[-1]
    existing_ts = [e["ts"] for e in st.session_state.history]
    if latest["ts"] not in existing_ts:
        st.session_state.history.append(latest)
        if len(st.session_state.history) > CONFIG["MAX_HISTORY"]:
            st.session_state.history.pop(0)

if not st.session_state.history:
    st.error("データの取得に失敗しました。外部 API の接続を確認してください。")
    st.stop()

current = st.session_state.history[-1]
df      = pd.DataFrame(st.session_state.history)

# ─────────────────────────────────────────────
# 7. サイドバー
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
    st.markdown("**データソース**")
    fred_ok = bool(FRED_API_KEY)
    news_ok = bool(NEWS_API_KEY)
    st.markdown(f"{'🟢' if fred_ok else '🔴'} FRED API {'接続済' if fred_ok else '未設定（デフォルト値）'}")
    st.markdown(f"{'🟢' if news_ok else '🔴'} NEWS API {'接続済' if news_ok else '未設定'}")
    st.markdown("🟢 GDELT（認証不要）")
    st.markdown("🟢 Yahoo Finance（認証不要）")

    st.markdown("---")
    st.markdown("**MRG 価格式**")
    st.code(
        "MRG = 1.0\n"
        "  × (1 + C ÷ 100)   // Conflict\n"
        "  × (OIL ÷ 75)      // Energy\n"
        "  × (1 + DEF ÷ 20)  // Defense\n"
        "  × PRESS            // 報道係数",
        language="text",
    )

    st.markdown("---")
    st.markdown("**⚠ ローソク足について**")
    st.caption(
        "MRG は架空通貨のため OHLC は実データの防衛株騰落率を基に"
        "シミュレーション生成しています。"
        "Close 値のみが実計算値です。"
    )

    last = st.session_state.get("last_refresh")
    if last:
        st.markdown("---")
        st.caption(f"最終更新: {last.strftime('%H:%M:%S')} JST")

# ─────────────────────────────────────────────
# 8. ヘッダー
# ─────────────────────────────────────────────

st.markdown(f"""
<div style="display:flex; justify-content:space-between; align-items:center;
            border-bottom: 2px solid #1e1e1e; padding-bottom: 12px; margin-bottom: 4px;">
    <div>
        <span style="font-family:'Share Tech Mono'; font-weight:bold; letter-spacing:3px;
                     font-size:22px; color:#ffffff;">MORGUE TERMINAL</span>
        <span style="font-family:'Share Tech Mono'; font-size:12px; color:#555555; margin-left:12px;">MRG-v2.8</span>
    </div>
    <div style="font-family:'Share Tech Mono'; font-size:13px; color:#22ff55;">
        ● LIVE&nbsp;&nbsp;{current['time']} JST
    </div>
</div>
""", unsafe_allow_html=True)

st.write("")

# ─────────────────────────────────────────────
# 9. 主要メトリクス
# ─────────────────────────────────────────────

if len(st.session_state.history) > 1:
    prev  = st.session_state.history[-2]
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
# 10. 詳細な計算過程パネル
# ─────────────────────────────────────────────

st.markdown("#### ［ MRG 価格算出プロセス ］")

fac = current["factors"]
drv = current["derivations"]
stp = current["steps"]

cl, cm, cr = st.columns([1.1, 1.2, 1.1])

# ── 左列: 生データ → 係数の導出 ──────────────
with cl:
    st.markdown("**① 係数の導出**")
    st.markdown(f"""
<div class="calc-panel">
<span class="calc-label">CONFLICT INDEX</span><br>
<span class="calc-eq">&nbsp;&nbsp;式 : {drv['c']}</span><br>
<span class="calc-eq">&nbsp;&nbsp;   = </span><span class="calc-coef">{fac['c']}</span>
<br><br>
<span class="calc-label">ENERGY (Brent Oil)</span><br>
<span class="calc-eq">&nbsp;&nbsp;式 : {drv['o']}</span><br>
<span class="calc-eq">&nbsp;&nbsp;   = </span><span class="calc-coef">{fac['o']}</span>
<br><br>
<span class="calc-label">DEFENSE (avg Δ%)</span><br>
<span class="calc-eq">&nbsp;&nbsp;式 : {drv['i']}</span><br>
<span class="calc-eq">&nbsp;&nbsp;   = </span><span class="calc-coef">{fac['i']}</span>
<br><br>
<span class="calc-label">PRESS FACTOR</span><br>
<span class="calc-eq">&nbsp;&nbsp;式 : {drv['p']}</span><br>
<span class="calc-eq">&nbsp;&nbsp;   = </span><span class="calc-coef">{fac['p']}</span>
</div>
""", unsafe_allow_html=True)

# ── 中列: 係数を順番に掛け合わせる ───────────
with cm:
    st.markdown("**② 累積乗算**")
    st.markdown(f"""
<div class="calc-panel">
<span class="calc-label">BASE UNIT</span><br>
<span class="calc-step">&nbsp;&nbsp;$ {stp['s0']:.4f}</span>
<br><br>
<span class="calc-label">× Conflict ({fac['c']})</span><br>
<span class="calc-eq">&nbsp;&nbsp;{stp['s0']:.4f} × {fac['c']}</span><br>
<span class="calc-step">&nbsp;&nbsp;= $ {stp['s1']:.4f}</span>
<br><br>
<span class="calc-label">× Energy ({fac['o']})</span><br>
<span class="calc-eq">&nbsp;&nbsp;{stp['s1']:.4f} × {fac['o']}</span><br>
<span class="calc-step">&nbsp;&nbsp;= $ {stp['s2']:.4f}</span>
<br><br>
<span class="calc-label">× Defense ({fac['i']})</span><br>
<span class="calc-eq">&nbsp;&nbsp;{stp['s2']:.4f} × {fac['i']}</span><br>
<span class="calc-step">&nbsp;&nbsp;= $ {stp['s3']:.4f}</span>
<br><br>
<span class="calc-label">× Press ({fac['p']})</span><br>
<span class="calc-eq">&nbsp;&nbsp;{stp['s3']:.4f} × {fac['p']}</span><br>
<span class="calc-step">&nbsp;&nbsp;= $ {stp['s4']:.4f}</span>
</div>
""", unsafe_allow_html=True)

# ── 右列: 最終換算 ────────────────────────────
with cr:
    st.markdown("**③ 最終換算**")
    st.markdown(f"""
<div class="calc-panel">
<span class="calc-label">MRG/USD (Close)</span><br>
<span class="calc-final">&nbsp;&nbsp;$ {current['close']:.4f}</span>
<br><br>
<span class="calc-label">USD/JPY レート</span><br>
<span class="calc-raw">&nbsp;&nbsp;¥ {current['fx_rate']}</span>
<br><br>
<span class="calc-label">換算式</span><br>
<span class="calc-eq">&nbsp;&nbsp;{current['close']:.4f}</span><br>
<span class="calc-eq">&nbsp;&nbsp;&nbsp;&nbsp;× {current['fx_rate']}</span><br>
<span class="calc-eq">&nbsp;&nbsp;= {current['close'] * current['fx_rate']:.2f}</span>
<br><br>
<span class="calc-divider">──────────────────</span><br>
<span class="calc-label">MRG/JPY (Close)</span><br>
<span class="calc-jpy">&nbsp;&nbsp;¥ {current['morg_jpy']:,}</span>
<br><br>
<span class="calc-label">OHLC (15m足)</span><br>
<span class="calc-eq">&nbsp;&nbsp;O: $ {current['open']:.4f}</span><br>
<span class="calc-eq">&nbsp;&nbsp;H: $ {current['high']:.4f}</span><br>
<span class="calc-eq">&nbsp;&nbsp;L: $ {current['low']:.4f}</span><br>
<span class="calc-step">&nbsp;&nbsp;C: $ {current['close']:.4f}</span>
</div>
""", unsafe_allow_html=True)

st.write("---")

# ─────────────────────────────────────────────
# 11. チャート
# ─────────────────────────────────────────────

gl, gr = st.columns([2, 1])

with gl:
    st.markdown(
        "#### ［ MRG 市場ボラティリティ ］"
        '<span class="sim-badge">▲ SIMULATION — Close値のみ実計算</span>',
        unsafe_allow_html=True,
    )
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
            tickfont=dict(family="Share Tech Mono", size=10, color="#aaaaaa"),
        ),
        xaxis=dict(
            rangeslider_visible=False,
            gridcolor="#161616",
            tickfont=dict(family="Share Tech Mono", size=9, color="#aaaaaa"),
        ),
        legend=dict(font=dict(family="Share Tech Mono", color="#cccccc")),
    )
    st.plotly_chart(fig, use_container_width=True)

with gr:
    st.markdown("#### ［ 個別推移 ］")

    # 係数値の推移も表示できるよう df を拡張
    df["c_factor"] = df["factors"].apply(lambda x: x["c"])
    df["o_factor"] = df["factors"].apply(lambda x: x["o"])
    df["i_factor"] = df["factors"].apply(lambda x: x["i"])

    for label, raw_col, fac_col, color in [
        ("CONFLICT INDEX → 係数C", "conflict", "c_factor", "#ff6b6b"),
        ("DEFENSE Δ% → 係数I",     "iron",     "i_factor", "#fbbf24"),
        ("OIL PRICE → 係数O",      "oil",      "o_factor", "#60a5fa"),
    ]:
        st.caption(label)
        chart_df = df.set_index("time")[[raw_col, fac_col]].rename(
            columns={raw_col: "実測値", fac_col: "係数"}
        )
        st.line_chart(chart_df, height=110, color=[color, "#ffffff"])

# ─────────────────────────────────────────────
# 12. 自動更新
# ─────────────────────────────────────────────

if auto_refresh:
    time.sleep(CONFIG["AUTO_REFRESH_SEC"])
    st.cache_data.clear()
    st.rerun()