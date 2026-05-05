"""
MORGUE TERMINAL MRG-v5.0
架空の戦災暗号資産「モルグ」のリアルタイム価格ダッシュボード

価格形成の仕組み:
  1. yfinance から防衛株 10 銘柄と USD/JPY の 15 分足を取得（過去 60 日）
  2. 15 分ごとに MRG/USD を計算（= ティック）
  3. ティックを日次に resample → O/H/L/C がすべて MRG の実計算値で構成される
  4. Conflict は GDELT 最新値を全ティックに適用
  5. Oil は FRED 日次値を当日の全ティックに適用

これにより「MRGは15分ごとに世界情勢から価格が決まる」というコンセプトが
コードレベルで正確に実装される。
"""

import logging
import os
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import yfinance as yf

# ─────────────────────────────────────────────
# 0. ロギング
# ─────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# 1. 設定
# ─────────────────────────────────────────────
EST = timezone(timedelta(hours=-5))
JST = timezone(timedelta(hours=9))

CONFIG = {
    # フォールバック値
    "DEFAULT_CONFLICT": 145.0,
    "DEFAULT_OIL":       82.0,
    "DEFAULT_FX":       155.0,
    "DEFAULT_PRESS":      1.06,

    # MRG 計算パラメータ
    "BASE_UNIT":        1.0,
    "CONFLICT_SCALE": 100.0,
    "OIL_ANCHOR":      75.0,
    "IRON_SCALE":      20.0,

    # yfinance — 15 分足・60 日（API上限）
    "YF_PERIOD":   "60d",
    "YF_INTERVAL": "15m",
    "DEFENSE_TICKERS": [
        "LMT", "RTX", "NOC", "GD", "BA",
        "LHX", "HII", "PLTR", "KTOS", "LDOS",
    ],
    "FX_TICKER": "JPY=X",

    # NYSE 開場時間（EST）— この時間帯のティックのみ使用
    "MARKET_OPEN_H":  9,
    "MARKET_OPEN_M": 30,
    "MARKET_CLOSE_H": 16,
    "MARKET_CLOSE_M":  0,

    # FRED
    "FRED_SERIES":   "DCOILBRENTEU",
    "FRED_OIL_DAYS": 100,

    # GDELT
    "GDELT_URL": (
        "https://api.gdeltproject.org/api/v2/doc/doc"
        "?query=(conflict+OR+violence)&mode=TimelineVol&format=json"
    ),

    "AUTO_REFRESH_SEC": 300,
}

FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
NEWS_API_KEY = os.environ.get("NEWS_API_KEY", "")

# ─────────────────────────────────────────────
# 2. ページ設定 & CSS
# ─────────────────────────────────────────────
st.set_page_config(page_title="MORGUE TERMINAL MRG-v5.0", layout="wide")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Rajdhani:wght@400;600;700&display=swap');

    html, body, [data-testid="stAppViewContainer"] {
        background-color: #040404;
        color: #e8e8e8;
        font-family: 'Rajdhani', sans-serif;
        font-size: 15px;
    }
    p, li, span { color: #e8e8e8; }
    code, pre { font-family: 'Share Tech Mono', monospace !important; }
    .stCode code { color: #f0e68c !important; background: #0a0a0a !important; }

    [data-testid="stMetric"] {
        background: linear-gradient(135deg, #0d0d0d 0%, #111 100%);
        border: 1px solid #2a2a2a;
        border-left: 3px solid #ff3030;
        padding: 14px 18px !important;
        border-radius: 2px;
    }
    [data-testid="stMetricValue"] { color: #ffffff !important; font-size: 2rem !important; font-weight: 700; }
    [data-testid="stMetricDelta"] { font-size: 0.85rem !important; }
    [data-testid="stMetricLabel"] { color: #aaaaaa !important; font-size: 0.72rem !important; letter-spacing: 2px; }

    .stMarkdown h4 {
        color: #cccccc !important;
        font-size: 0.72rem;
        letter-spacing: 3px;
        text-transform: uppercase;
        margin-bottom: 6px;
    }
    [data-testid="stCaptionContainer"] p {
        color: #bbbbbb !important;
        font-size: 0.72rem;
        letter-spacing: 1px;
        line-height: 1.6;
    }

    table { width: 100%; border-collapse: collapse; font-family: 'Share Tech Mono', monospace; font-size: 0.8rem; }
    th { color: #aaaaaa !important; font-weight: 400; border-bottom: 1px solid #2a2a2a; padding: 5px 10px; }
    td { padding: 6px 10px; border-bottom: 1px solid #1a1a1a; color: #e8e8e8; }
    td:nth-child(2) { color: #7dd3fc; }
    td:nth-child(3) { color: #fde68a; text-align: right; }

    .calc-panel {
        background: #080808;
        border: 1px solid #222;
        border-radius: 3px;
        padding: 14px 16px;
        font-family: 'Share Tech Mono', monospace;
        font-size: 0.8rem;
        line-height: 2;
    }
    .calc-raw   { color: #7dd3fc; }
    .calc-eq    { color: #888888; }
    .calc-coef  { color: #fde68a; }
    .calc-step  { color: #86efac; }
    .calc-final { color: #ff6b6b; font-weight: bold; }
    .calc-jpy   { color: #f9a8d4; font-weight: bold; }
    .calc-label { color: #aaaaaa; }
    .calc-note  { color: #f59e0b; font-size: 0.72rem; }

    ::-webkit-scrollbar { display: none; }
    [data-testid="stSidebar"] { background-color: #060606; border-right: 1px solid #1a1a1a; }
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] span,
    [data-testid="stSidebar"] label { color: #cccccc !important; }
    [data-testid="stSidebar"] h3 { color: #ffffff !important; }

    @media (max-width: 768px) {
        [data-testid="column"] { width: 100% !important; flex: 1 1 100% !important; }
    }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# 3. データ取得
# ─────────────────────────────────────────────

@st.cache_data(ttl=3600)
def fetch_conflict_index() -> float:
    try:
        res = requests.get(CONFIG["GDELT_URL"], timeout=10)
        res.raise_for_status()
        raw = float(res.json()["timeline"][0]["data"][-1]["value"])
        val = raw * 10
        log.info("GDELT conflict: %.2f", val)
        return val
    except requests.exceptions.RequestException as e:
        log.warning("GDELT failed (%s)", e)
    except (KeyError, IndexError, ValueError) as e:
        log.warning("GDELT parse error (%s)", e)
    return CONFIG["DEFAULT_CONFLICT"]


@st.cache_data(ttl=3600)
def fetch_oil_series() -> pd.Series:
    """FRED から日次 Brent 原油を取得。index: "YYYY-MM-DD"文字列, value: float"""
    if not FRED_API_KEY:
        log.warning("FRED_API_KEY not set.")
        return pd.Series(dtype=float)
    try:
        url = (
            f"https://api.stlouisfed.org/fred/series/observations"
            f"?series_id={CONFIG['FRED_SERIES']}&api_key={FRED_API_KEY}"
            f"&file_type=json&sort_order=desc&limit={CONFIG['FRED_OIL_DAYS']}"
        )
        obs = requests.get(url, timeout=10).json()["observations"]
        s = pd.Series(
            {o["date"]: float(o["value"]) for o in obs if o["value"] != "."},
            dtype=float,
        ).sort_index()
        log.info("FRED oil: %d days", len(s))
        return s
    except Exception as e:
        log.error("FRED failed: %s", e)
        return pd.Series(dtype=float)


@st.cache_data(ttl=900)
def fetch_15min_ticks() -> tuple[pd.Series, pd.Series]:
    """
    防衛株 10 銘柄の 15 分足平均騰落率と USD/JPY を取得。
    NYSE 開場時間（09:30–16:00 EST）のティックのみ返す。
    戻り値: (defense_pct: Series, fx: Series)  index = DatetimeTZAware(UTC)
    """
    tickers = CONFIG["DEFENSE_TICKERS"] + [CONFIG["FX_TICKER"]]
    try:
        raw = yf.download(
            tickers,
            period=CONFIG["YF_PERIOD"],
            interval=CONFIG["YF_INTERVAL"],
            progress=False,
            auto_adjust=True,
        )
        if not isinstance(raw.columns, pd.MultiIndex):
            raise ValueError("MultiIndex expected")

        close     = raw["Close"].ffill()
        fx        = close[CONFIG["FX_TICKER"]].ffill()
        defense   = close[CONFIG["DEFENSE_TICKERS"]].ffill()
        def_pct   = defense.pct_change().mean(axis=1) * 100  # 15分騰落率(%)

        # NYSE 開場時間フィルタ（EST）
        def in_market(ts: pd.Timestamp) -> bool:
            t = ts.astimezone(EST).time()
            open_t  = datetime.strptime(
                f"{CONFIG['MARKET_OPEN_H']}:{CONFIG['MARKET_OPEN_M']:02d}", "%H:%M"
            ).time()
            close_t = datetime.strptime(
                f"{CONFIG['MARKET_CLOSE_H']}:{CONFIG['MARKET_CLOSE_M']:02d}", "%H:%M"
            ).time()
            return open_t <= t <= close_t

        mask    = pd.Series(def_pct.index.map(in_market), index=def_pct.index)
        def_pct = def_pct[mask].dropna()
        fx      = fx[mask].dropna()

        log.info("15min ticks (market hours): %d rows", len(def_pct))
        return def_pct, fx

    except Exception as e:
        log.error("yfinance 15min failed: %s", e)
        return pd.Series(dtype=float), pd.Series(dtype=float)


# ─────────────────────────────────────────────
# 4. MRG 計算
# ─────────────────────────────────────────────

def calc_mrg(conflict: float, oil: float, iron_pct: float, press: float) -> float:
    c_f = 1.0 + conflict / CONFIG["CONFLICT_SCALE"]
    o_f = oil            / CONFIG["OIL_ANCHOR"]
    i_f = 1.0 + iron_pct / CONFIG["IRON_SCALE"]
    return round(CONFIG["BASE_UNIT"] * c_f * o_f * i_f * press, 5)


def calc_mrg_detail(conflict: float, oil: float, iron_pct: float, press: float) -> dict:
    """係数・中間ステップ付きで MRG を計算（最新足の表示用）。"""
    c_f = 1.0 + conflict / CONFIG["CONFLICT_SCALE"]
    o_f = oil            / CONFIG["OIL_ANCHOR"]
    i_f = 1.0 + iron_pct / CONFIG["IRON_SCALE"]
    p_f = press
    s   = [CONFIG["BASE_UNIT"]]
    for f in (c_f, o_f, i_f, p_f):
        s.append(round(s[-1] * f, 5))
    return {
        "mrg_usd": s[-1],
        "factors": {"c": round(c_f,4), "o": round(o_f,4), "i": round(i_f,4), "p": round(p_f,4)},
        "steps":   [round(x,5) for x in s],
        "derivations": {
            "c": f"1 + {conflict:.2f} ÷ {CONFIG['CONFLICT_SCALE']:.0f}",
            "o": f"{oil:.2f} ÷ {CONFIG['OIL_ANCHOR']:.0f}",
            "i": f"1 + ({iron_pct:.4f}) ÷ {CONFIG['IRON_SCALE']:.0f}",
            "p": "報道係数（固定）",
        },
    }


# ─────────────────────────────────────────────
# 5. ティック列 → 日次ローソク足
# ─────────────────────────────────────────────

@st.cache_data(ttl=900)
def build_tick_and_daily() -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    15 分ティックを計算し、日次に resample してローソク足を生成する。

    戻り値:
      tick_df  : 全ティックの DataFrame（チャート詳細・デバッグ用）
      daily_df : 日次集計 DataFrame（ローソク足チャート用）
    """
    conflict   = fetch_conflict_index()
    oil_series = fetch_oil_series()
    press      = CONFIG["DEFAULT_PRESS"]
    def_pct, fx_series = fetch_15min_ticks()

    if def_pct.empty:
        return pd.DataFrame(), pd.DataFrame()

    # ── ティックごとに MRG を計算 ──────────────────────────
    records = []
    for ts, iron_pct in def_pct.items():
        date_str = ts.strftime("%Y-%m-%d")

        # Oil: その日以前の最新 FRED 値
        if not oil_series.empty:
            past = oil_series[oil_series.index <= date_str]
            oil  = float(past.iloc[-1]) if not past.empty else CONFIG["DEFAULT_OIL"]
        else:
            oil = CONFIG["DEFAULT_OIL"]

        fx      = float(fx_series.loc[ts]) if ts in fx_series.index else CONFIG["DEFAULT_FX"]
        mrg_usd = calc_mrg(conflict, oil, float(iron_pct), press)

        records.append({
            "ts":       ts,
            "date":     date_str,
            "mrg_usd":  mrg_usd,
            "morg_jpy": int(mrg_usd * fx),
            "fx_rate":  round(fx, 2),
            "iron_pct": round(float(iron_pct), 5),
            "conflict": round(conflict, 2),
            "oil":      round(oil, 2),
        })

    tick_df = pd.DataFrame(records).set_index("ts")

    # ── 日次に resample ──────────────────────────────────
    # MRG の O/H/L/C はすべてティックの実計算値から集計
    daily = tick_df["mrg_usd"].resample("1D").agg(
        open="first",
        high="max",
        low="min",
        close="last",
    ).dropna()

    # 各日の補足情報を付加
    daily_extras = tick_df.resample("1D").agg(
        morg_jpy=("morg_jpy", "last"),
        fx_rate=("fx_rate",   "last"),
        iron_pct=("iron_pct", "last"),   # Close 時点の値
        conflict=("conflict", "last"),
        oil=("oil",           "last"),
        tick_count=("mrg_usd", "count"), # その日何ティックあったか
    ).dropna()

    daily_df = daily.join(daily_extras).reset_index()
    daily_df["date"] = daily_df["ts"].dt.strftime("%Y-%m-%d")

    log.info("Daily candles: %d", len(daily_df))
    return tick_df.reset_index(), daily_df


# ─────────────────────────────────────────────
# 6. データ読み込み
# ─────────────────────────────────────────────

tick_df, daily_df = build_tick_and_daily()

if daily_df.empty:
    st.error("データの取得に失敗しました。外部 API の接続を確認してください。")
    st.stop()

current = daily_df.iloc[-1]   # 最新日

# 最新足の詳細計算（表示用）
detail = calc_mrg_detail(
    conflict  = float(current["conflict"]),
    oil       = float(current["oil"]),
    iron_pct  = float(current["iron_pct"]),
    press     = CONFIG["DEFAULT_PRESS"],
)

# ─────────────────────────────────────────────
# 7. サイドバー
# ─────────────────────────────────────────────

with st.sidebar:
    st.markdown("### ⚙ TERMINAL CONFIG")
    st.caption("MRG-v5.0 // CLASSIFIED")
    st.markdown("---")

    auto_refresh = st.toggle("自動更新 (5min)", value=False)
    if st.button("手動更新", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.markdown("---")
    st.markdown("**データソース**")
    st.markdown(f"{'🟢' if FRED_API_KEY else '🔴'} FRED API (日次原油) "
                f"{'接続済' if FRED_API_KEY else '未設定→デフォルト値'}")
    st.markdown(f"{'🟢' if NEWS_API_KEY else '🔴'} NEWS API "
                f"{'接続済' if NEWS_API_KEY else '未設定'}")
    st.markdown("🟢 GDELT（認証不要）")
    st.markdown("🟢 Yahoo Finance（認証不要）")

    st.markdown("---")
    st.markdown("**価格形成の仕組み**")
    st.caption(
        "① NYSE 開場中（09:30–16:00 EST）に\n"
        "　 15 分ごと MRG/USD を計算・記録\n\n"
        "② その日の全ティックを集計して\n"
        "　 O=最初 H=最高 L=最低 C=最後\n\n"
        "③ Conflict は GDELT 最新値を全日適用\n"
        "　 Oil は FRED 日次値を当日ティックに適用"
    )

    st.markdown("---")
    st.markdown("**MRG 価格式**")
    st.code(
        "MRG = 1.0\n"
        "  × (1 + Conflict ÷ 100)\n"
        "  × (Oil ÷ 75)\n"
        "  × (1 + DefenseΔ% ÷ 20)\n"
        "  × Press",
        language="text",
    )

    st.markdown("---")
    st.caption(f"最終更新: {datetime.now(JST).strftime('%H:%M:%S')} JST")

# ─────────────────────────────────────────────
# 8. ヘッダー
# ─────────────────────────────────────────────

st.markdown(f"""
<div style="display:flex; justify-content:space-between; align-items:center;
            border-bottom: 2px solid #1e1e1e; padding-bottom: 12px; margin-bottom: 4px;">
    <div>
        <span style="font-family:'Share Tech Mono'; font-weight:bold; letter-spacing:3px;
                     font-size:22px; color:#ffffff;">MORGUE TERMINAL</span>
        <span style="font-family:'Share Tech Mono'; font-size:12px; color:#555;
                     margin-left:12px;">MRG-v5.0 // 15min→DAILY</span>
    </div>
    <div style="font-family:'Share Tech Mono'; font-size:13px; color:#22ff55;">
        ● LIVE&nbsp;&nbsp;{current['date']} JST
    </div>
</div>
""", unsafe_allow_html=True)

st.write("")

# ─────────────────────────────────────────────
# 9. 主要メトリクス
# ─────────────────────────────────────────────

if len(daily_df) > 1:
    prev  = daily_df.iloc[-2]
    d_jpy = int(current["morg_jpy"])  - int(prev["morg_jpy"])
    d_usd = float(current["close"])   - float(prev["close"])
    d_fx  = float(current["fx_rate"]) - float(prev["fx_rate"])
    d_oil = float(current["oil"])     - float(prev["oil"])
else:
    d_jpy = d_usd = d_fx = d_oil = 0.0

m1, m2, m3, m4 = st.columns([2, 2, 1.2, 1.2])
m1.metric("MRG/JPY",     f"¥{int(current['morg_jpy']):,}",    delta=int(d_jpy))
m2.metric("MRG/USD",     f"$ {float(current['close']):.5f}",  delta=round(float(d_usd), 5))
m3.metric("USD/JPY",     f"¥ {float(current['fx_rate'])}",    delta=round(float(d_fx), 2))
m4.metric("OIL (Brent)", f"$ {float(current['oil']):.2f}",    delta=round(float(d_oil), 2))

st.write("---")

# ─────────────────────────────────────────────
# 10. 計算過程パネル
# ─────────────────────────────────────────────

st.markdown("#### ［ MRG 価格算出プロセス（直近 Close ティック） ］")

fac = detail["factors"]
drv = detail["derivations"]
stp = detail["steps"]

cl, cm, cr = st.columns([1.1, 1.2, 1.1])

with cl:
    st.markdown("**① 係数の導出**")
    st.markdown(f"""
<div class="calc-panel">
<span class="calc-label">CONFLICT INDEX</span><br>
<span class="calc-eq">&nbsp;&nbsp;式 : {drv['c']}</span><br>
<span class="calc-eq">&nbsp;&nbsp;&nbsp;&nbsp;= </span><span class="calc-coef">{fac['c']}</span>
<br><br>
<span class="calc-label">ENERGY (Brent Oil / 日次)</span><br>
<span class="calc-eq">&nbsp;&nbsp;式 : {drv['o']}</span><br>
<span class="calc-eq">&nbsp;&nbsp;&nbsp;&nbsp;= </span><span class="calc-coef">{fac['o']}</span>
<br><br>
<span class="calc-label">DEFENSE Δ% (Close ティック)</span><br>
<span class="calc-eq">&nbsp;&nbsp;式 : {drv['i']}</span><br>
<span class="calc-eq">&nbsp;&nbsp;&nbsp;&nbsp;= </span><span class="calc-coef">{fac['i']}</span>
<br><br>
<span class="calc-label">PRESS FACTOR</span><br>
<span class="calc-eq">&nbsp;&nbsp;式 : {drv['p']}</span><br>
<span class="calc-eq">&nbsp;&nbsp;&nbsp;&nbsp;= </span><span class="calc-coef">{fac['p']}</span>
</div>
""", unsafe_allow_html=True)

with cm:
    st.markdown("**② 累積乗算**")
    st.markdown(f"""
<div class="calc-panel">
<span class="calc-label">BASE UNIT</span><br>
<span class="calc-step">&nbsp;&nbsp;$ {stp[0]:.5f}</span>
<br><br>
<span class="calc-label">× Conflict ({fac['c']})</span><br>
<span class="calc-eq">&nbsp;&nbsp;{stp[0]:.5f} × {fac['c']}</span><br>
<span class="calc-step">&nbsp;&nbsp;= $ {stp[1]:.5f}</span>
<br><br>
<span class="calc-label">× Energy ({fac['o']})</span><br>
<span class="calc-eq">&nbsp;&nbsp;{stp[1]:.5f} × {fac['o']}</span><br>
<span class="calc-step">&nbsp;&nbsp;= $ {stp[2]:.5f}</span>
<br><br>
<span class="calc-label">× Defense ({fac['i']})</span><br>
<span class="calc-eq">&nbsp;&nbsp;{stp[2]:.5f} × {fac['i']}</span><br>
<span class="calc-step">&nbsp;&nbsp;= $ {stp[3]:.5f}</span>
<br><br>
<span class="calc-label">× Press ({fac['p']})</span><br>
<span class="calc-eq">&nbsp;&nbsp;{stp[3]:.5f} × {fac['p']}</span><br>
<span class="calc-step">&nbsp;&nbsp;= $ {stp[4]:.5f}</span>
</div>
""", unsafe_allow_html=True)

with cr:
    st.markdown("**③ 最終換算 & 日足 OHLC**")
    st.markdown(f"""
<div class="calc-panel">
<span class="calc-label">MRG/USD (Close)</span><br>
<span class="calc-final">&nbsp;&nbsp;$ {float(current['close']):.5f}</span>
<br><br>
<span class="calc-label">USD/JPY レート</span><br>
<span class="calc-raw">&nbsp;&nbsp;¥ {float(current['fx_rate'])}</span>
<br><br>
<span class="calc-label">換算</span><br>
<span class="calc-eq">&nbsp;&nbsp;{float(current['close']):.5f} × {float(current['fx_rate'])}</span><br>
<span class="calc-jpy">&nbsp;&nbsp;= ¥ {int(current['morg_jpy']):,}</span>
<br><br>
<span class="calc-label">── 日足 OHLC (MRG/USD) ──</span><br>
<span class="calc-eq">&nbsp;&nbsp;O: $ {float(current['open']):.5f}</span><br>
<span class="calc-eq">&nbsp;&nbsp;H: </span><span class="calc-step">$ {float(current['high']):.5f}</span><br>
<span class="calc-eq">&nbsp;&nbsp;L: </span><span class="calc-final">$ {float(current['low']):.5f}</span><br>
<span class="calc-eq">&nbsp;&nbsp;C: </span><span class="calc-jpy">$ {float(current['close']):.5f}</span><br>
<br>
<span class="calc-note">※ {int(current['tick_count'])} ティックから集計</span>
</div>
""", unsafe_allow_html=True)

st.write("---")

# ─────────────────────────────────────────────
# 11. チャート
# ─────────────────────────────────────────────

tab_daily, tab_tick = st.tabs(["📊 日足チャート", "📈 15分ティック"])

with tab_daily:
    gl, gr = st.columns([2, 1])

    with gl:
        st.markdown("#### ［ MRG 日足ローソク足 ］")
        st.caption(
            "NYSE 開場中の 15 分ティックを日次集計。"
            f"O=最初のティック / H=最高値 / L=最低値 / C=最後のティック。"
            f"全 {len(daily_df)} 日分を表示。"
        )
        fig = go.Figure(data=[go.Candlestick(
            x=daily_df["date"],
            open=daily_df["open"],
            high=daily_df["high"],
            low=daily_df["low"],
            close=daily_df["close"],
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
            height=460,
            margin=dict(l=0, r=0, b=0, t=0),
            yaxis=dict(
                autorange=True,
                fixedrange=False,
                tickformat=".5f",
                gridcolor="#161616",
                tickfont=dict(family="Share Tech Mono", size=10, color="#aaaaaa"),
            ),
            xaxis=dict(
                rangeslider_visible=False,
                gridcolor="#161616",
                tickfont=dict(family="Share Tech Mono", size=9, color="#aaaaaa"),
                type="category",
            ),
        )
        st.plotly_chart(fig, use_container_width=True)

    with gr:
        st.markdown("#### ［ 個別推移（日次） ］")

        daily_df["c_factor"] = daily_df["conflict"].apply(
            lambda c: round(1 + c / CONFIG["CONFLICT_SCALE"], 4)
        )
        daily_df["o_factor"] = daily_df["oil"].apply(
            lambda o: round(o / CONFIG["OIL_ANCHOR"], 4)
        )
        daily_df["i_factor"] = daily_df["iron_pct"].apply(
            lambda i: round(1 + i / CONFIG["IRON_SCALE"], 4)
        )

        for label, raw_col, fac_col, color in [
            ("CONFLICT → 係数C",    "conflict",  "c_factor", "#ff6b6b"),
            ("DEFENSE Δ% → 係数I", "iron_pct",  "i_factor", "#fbbf24"),
            ("OIL (日次) → 係数O", "oil",       "o_factor", "#60a5fa"),
        ]:
            st.caption(label)
            chart_df = daily_df.set_index("date")[[raw_col, fac_col]].rename(
                columns={raw_col: "実測値", fac_col: "係数"}
            )
            st.line_chart(chart_df, height=110, color=[color, "#ffffff"])

with tab_tick:
    st.markdown("#### ［ 15分ティック（直近 3 日分） ］")
    st.caption("NYSE 開場中のティックのみ表示。これを日次集計するとローソク足になります。")

    if not tick_df.empty:
        # 直近 3 営業日のティックを抽出
        recent_dates = sorted(tick_df["date"].unique())[-3:]
        recent_ticks = tick_df[tick_df["date"].isin(recent_dates)].copy()

        fig2 = go.Figure()
        colors = ["#60a5fa", "#fbbf24", "#86efac"]
        for i, date in enumerate(recent_dates):
            day_ticks = recent_ticks[recent_ticks["date"] == date]
            fig2.add_trace(go.Scatter(
                x=day_ticks["ts"].dt.strftime("%H:%M"),
                y=day_ticks["mrg_usd"],
                mode="lines+markers",
                name=date,
                line=dict(color=colors[i % len(colors)], width=1.5),
                marker=dict(size=3),
            ))

        fig2.update_layout(
            template="plotly_dark",
            paper_bgcolor="#040404",
            plot_bgcolor="#040404",
            height=380,
            margin=dict(l=0, r=0, b=0, t=0),
            yaxis=dict(
                tickformat=".5f",
                gridcolor="#161616",
                tickfont=dict(family="Share Tech Mono", size=10, color="#aaaaaa"),
            ),
            xaxis=dict(
                gridcolor="#161616",
                tickfont=dict(family="Share Tech Mono", size=9, color="#aaaaaa"),
                title=dict(text="EST", font=dict(color="#666")),
            ),
            legend=dict(font=dict(family="Share Tech Mono", color="#cccccc")),
        )
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.warning("ティックデータが取得できませんでした。")

# ─────────────────────────────────────────────
# 12. 自動更新
# ─────────────────────────────────────────────

if auto_refresh:
    time.sleep(CONFIG["AUTO_REFRESH_SEC"])
    st.cache_data.clear()
    st.rerun()