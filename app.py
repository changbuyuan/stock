#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf


DATA_FILE = Path(__file__).with_name("stock_portfolio_data.json")
BACKUP_FILE = Path(__file__).with_name("stock_portfolio_data.bak.json")
TW_SYMBOL_MAP = {"0050": "0050.TW", "0056": "0056.TW"}
ALLOWED_SYMBOLS = tuple(TW_SYMBOL_MAP.keys())
MAX_PRICE = 1_000_000.0
MAX_SHARES = 10_000_000.0
MAX_FEE_TAX = 10_000_000.0


@dataclass
class Position:
    shares: float = 0.0
    cost: float = 0.0
    realized_pnl: float = 0.0

    @property
    def avg_cost(self) -> float:
        return self.cost / self.shares if self.shares > 0 else 0.0


def load_payload() -> Dict:
    if not DATA_FILE.exists():
        return {}
    try:
        payload = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def save_payload(payload: Dict) -> None:
    if DATA_FILE.exists():
        try:
            BACKUP_FILE.write_text(DATA_FILE.read_text(encoding="utf-8"), encoding="utf-8")
        except OSError:
            # 備份失敗不應阻斷主流程，仍繼續寫入主檔案。
            pass
    DATA_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def restore_payload_from_backup() -> bool:
    if not BACKUP_FILE.exists():
        return False
    try:
        DATA_FILE.write_text(BACKUP_FILE.read_text(encoding="utf-8"), encoding="utf-8")
        return True
    except OSError:
        return False


def load_transactions() -> List[Dict]:
    payload = load_payload()
    transactions = payload.get("transactions", [])
    return transactions if isinstance(transactions, list) else []


def save_transactions(transactions: List[Dict]) -> None:
    payload = load_payload()
    payload["transactions"] = transactions
    save_payload(payload)


def load_saving_settings() -> Dict[str, float]:
    payload = load_payload()
    defaults = {
        "current_savings": 0.0,
        "savings_goal": 500000.0,
        "monthly_saving": 10000.0,
    }
    data = payload.get("saving_settings", {})
    if not isinstance(data, dict):
        return defaults
    return {
        "current_savings": float(data.get("current_savings", defaults["current_savings"])),
        "savings_goal": float(data.get("savings_goal", defaults["savings_goal"])),
        "monthly_saving": float(data.get("monthly_saving", defaults["monthly_saving"])),
    }


def save_saving_settings(current_savings: float, savings_goal: float, monthly_saving: float) -> None:
    payload = load_payload()
    payload["saving_settings"] = {
        "current_savings": float(current_savings),
        "savings_goal": float(savings_goal),
        "monthly_saving": float(monthly_saving),
    }
    save_payload(payload)


def build_positions(transactions: List[Dict]) -> Dict[str, Position]:
    positions = {symbol: Position() for symbol in ALLOWED_SYMBOLS}
    for tx in transactions:
        symbol = tx["symbol"]
        side = tx["side"]
        shares = float(tx["shares"])
        total = float(tx["total"])
        pos = positions[symbol]

        if side == "buy":
            pos.shares += shares
            pos.cost += total
            continue

        if shares > pos.shares:
            shares = pos.shares
            if shares <= 0:
                continue

        avg = pos.avg_cost
        pos.realized_pnl += total - avg * shares
        pos.shares -= shares
        pos.cost -= avg * shares
    return positions


@st.cache_data(ttl=30)
def get_live_price(symbol_tw: str) -> float | None:
    ticker = yf.Ticker(symbol_tw)
    history = ticker.history(period="1d", interval="1m")
    if history.empty:
        history = ticker.history(period="5d")
    if history.empty:
        return None
    return float(history["Close"].dropna().iloc[-1])


@st.cache_data(ttl=600)
def get_6m_high(symbol_tw: str) -> float | None:
    ticker = yf.Ticker(symbol_tw)
    history = ticker.history(period="6mo")
    if history.empty:
        return None
    return float(history["High"].max())


@st.cache_data(ttl=600)
def get_price_history(symbol_tw: str, period: str = "6mo") -> pd.Series | None:
    ticker = yf.Ticker(symbol_tw)
    history = ticker.history(period=period)
    if history.empty or "Close" not in history.columns:
        return None
    close = history["Close"].dropna()
    if close.empty:
        return None
    return close


@st.cache_data(ttl=600)
def get_price_history_from_start(symbol_tw: str, start_date: str) -> pd.Series | None:
    ticker = yf.Ticker(symbol_tw)
    history = ticker.history(start=start_date)
    if history.empty or "Close" not in history.columns:
        return None
    close = history["Close"].dropna()
    if close.empty:
        return None
    return close


def compute_summary(transactions: List[Dict], prices: Dict[str, float]) -> Dict:
    positions = build_positions(transactions)
    details: Dict[str, Dict] = {}
    total_market_value = total_cost = total_realized = 0.0

    for symbol in ALLOWED_SYMBOLS:
        pos = positions[symbol]
        market_value = pos.shares * prices[symbol]
        unrealized = market_value - pos.cost
        details[symbol] = {
            "shares": pos.shares,
            "avg_cost": pos.avg_cost,
            "cost": pos.cost,
            "market_value": market_value,
            "unrealized_pnl": unrealized,
            "realized_pnl": pos.realized_pnl,
        }
        total_market_value += market_value
        total_cost += pos.cost
        total_realized += pos.realized_pnl

    total_unrealized = total_market_value - total_cost
    total_pnl = total_unrealized + total_realized
    basis = total_cost if total_cost > 0 else 1.0
    return_rate = total_pnl / basis * 100

    return {
        "details": details,
        "total_market_value": total_market_value,
        "total_cost": total_cost,
        "total_unrealized": total_unrealized,
        "total_realized": total_realized,
        "total_pnl": total_pnl,
        "return_rate": return_rate,
    }


def format_currency(value: float) -> str:
    return f"{value:,.2f}"


def format_side(side: str) -> str:
    return "買進" if side == "buy" else "賣出"


def render_theme() -> None:
    st.markdown(
        """
<style>
    :root {
        --bg-top: #141920;
        --bg-bottom: #1a212b;
        --surface: #202933;
        --surface-muted: #1b242e;
        --text-primary: #d8e0ea;
        --text-secondary: #d8e0ea;
        --border: #2c3846;
        --shadow-soft: 0 8px 20px rgba(3, 8, 16, 0.22);
        --shadow-xs: 0 4px 10px rgba(3, 8, 16, 0.18);
        --brand-1: #4b74b3;
        --brand-2: #3d5f93;
    }
    .stApp {
        background: linear-gradient(180deg, var(--bg-top) 0%, var(--bg-bottom) 100%);
        color: var(--text-primary);
    }
    .main .block-container {
        padding-top: 1.6rem;
        padding-bottom: 2.2rem;
        max-width: 1240px;
    }
    .hero {
        background: linear-gradient(120deg, var(--brand-2) 0%, var(--brand-1) 100%);
        border-radius: 16px;
        padding: 1.1rem 1.3rem;
        color: #ffffff;
        box-shadow: 0 6px 16px rgba(31, 47, 74, 0.28);
        margin-bottom: 1rem;
    }
    .hero h2 {
        margin: 0 0 0.3rem 0;
        font-size: 1.28rem;
        font-weight: 700;
        letter-spacing: 0.01em;
    }
    .hero p {
        margin: 0;
        opacity: 0.92;
        font-size: 0.9rem;
    }
    .section-card {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 14px;
        padding: 0.9rem 1rem;
        margin-top: 0.5rem;
        box-shadow: var(--shadow-soft);
    }
    .quote-title {
        font-size: 0.82rem;
        color: var(--text-primary);
        font-weight: 600;
    }
    .quote-value {
        font-size: 1.65rem;
        line-height: 1.15;
        margin-top: 0.18rem;
        color: var(--text-primary);
        font-weight: 700;
        letter-spacing: 0.01em;
    }
    .quote-holding {
        text-align: right;
        font-size: 0.82rem;
        color: #8ea3bf;
        margin-top: 0.15rem;
    }
    .saving-kpi {
        margin-top: 0.28rem;
        font-size: 1.02rem;
        font-weight: 700;
        color: var(--text-primary);
    }
    .saving-meta {
        margin-top: 0.25rem;
        font-size: 0.8rem;
        color: var(--text-primary);
    }
    .metric-positive {
        color: #8fc59f;
        font-weight: 700;
    }
    .metric-negative {
        color: #d49a9a;
        font-weight: 700;
    }
    div[data-testid="stMetric"] {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 0.62rem 0.78rem;
        box-shadow: var(--shadow-xs);
    }
    div[data-testid="stMetricLabel"] p {
        font-size: 0.84rem;
        color: var(--text-secondary);
        font-weight: 600;
    }
    div[data-testid="stMetricValue"] {
        font-size: 1.28rem;
    }
    div[data-baseweb="tab-list"] {
        gap: 0.35rem;
        background: var(--surface-muted);
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 0.25rem;
    }
    button[data-baseweb="tab"] {
        border-radius: 9px;
        height: 2.1rem;
        padding: 0 0.85rem;
        color: var(--text-primary);
    }
    button[data-baseweb="tab"][aria-selected="true"] {
        background: var(--surface);
        color: var(--text-primary);
        font-weight: 600;
        box-shadow: var(--shadow-xs);
    }
    .stButton > button, .stDownloadButton > button {
        border-radius: 10px;
        border: 1px solid #3a495c;
        background: linear-gradient(180deg, #2a3542 0%, #26313e 100%);
        color: #d3dce7;
        font-weight: 600;
    }
    .stButton > button:hover {
        border-color: #4c5f77;
        background: #2f3b49;
    }
    .stTextInput input, .stNumberInput input, .stSelectbox div[data-baseweb="select"] > div {
        border-radius: 10px !important;
        border-color: #3b4a5e !important;
        background: #1b2530 !important;
        color: #d8e0ea !important;
    }
    div[data-testid="stWidgetLabel"] p,
    .stSelectbox label,
    .stNumberInput label {
        color: var(--text-primary) !important;
    }
    .stSelectbox div[data-baseweb="select"] *,
    .stMultiSelect div[data-baseweb="select"] * {
        color: var(--text-primary) !important;
    }
    div[data-baseweb="popover"] ul li,
    div[data-baseweb="menu"] ul li {
        color: var(--text-primary) !important;
        background: #1b2530 !important;
    }
    div[data-baseweb="popover"] ul li:hover,
    div[data-baseweb="menu"] ul li:hover {
        background: #243140 !important;
    }
    .stNumberInput [data-baseweb="input"] {
        background: #1b2530 !important;
        border: 1px solid #3b4a5e !important;
        border-radius: 10px !important;
    }
    .stNumberInput [data-baseweb="input"] input {
        color: #d8e0ea !important;
    }
    .stNumberInput [data-baseweb="input"] button {
        background: #243140 !important;
        color: #d8e0ea !important;
        border-left: 1px solid #3b4a5e !important;
    }
    .stNumberInput [data-baseweb="input"] button:hover {
        background: #2d3c4d !important;
    }
    .stExpander label, .stExpander p, .stExpander span {
        color: var(--text-primary) !important;
    }
    div[data-testid="stDataFrame"] {
        border: 1px solid var(--border);
        border-radius: 10px;
        overflow: hidden;
        background: var(--surface);
    }
    div[data-testid="stDataFrame"] thead tr th {
        background: #1f2a38 !important;
        color: var(--text-primary) !important;
        border-bottom: 1px solid var(--border) !important;
    }
    div[data-testid="stDataFrame"] tbody tr td {
        background: #18222f !important;
        color: var(--text-primary) !important;
        border-bottom: 1px solid #2a3748 !important;
    }
    .tx-table-wrap {
        border: 1px solid var(--border);
        border-radius: 10px;
        overflow: hidden;
        background: var(--surface);
    }
    .tx-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 0.88rem;
    }
    .tx-table thead th {
        background: #1f2a38;
        color: var(--text-primary);
        text-align: left;
        padding: 0.55rem 0.6rem;
        border-bottom: 1px solid var(--border);
        font-weight: 600;
    }
    .tx-table tbody td {
        background: #18222f;
        color: var(--text-primary);
        padding: 0.52rem 0.6rem;
        border-bottom: 1px solid #2a3748;
    }
    .tx-table tbody tr:last-child td {
        border-bottom: none;
    }
    div[data-testid="stCheckbox"] label span {
        color: var(--text-primary) !important;
    }
    .stAlert {
        border-radius: 12px;
        border: 1px solid #334967;
    }
    .stProgress > div > div > div > div {
        background: linear-gradient(90deg, #5978a5, #4b6b98);
    }
    div[data-testid="stExpander"] details {
        border: 1px solid var(--border);
        border-radius: 12px;
        background: var(--surface);
    }
    .stMarkdown, .stCaption, label, p, span {
        color: inherit;
    }
    .stCaption, [data-testid="stCaptionContainer"] p {
        color: var(--text-primary) !important;
    }
</style>
        """,
        unsafe_allow_html=True,
    )


def build_detail_dataframe(summary: Dict) -> pd.DataFrame:
    rows = []
    for symbol in ALLOWED_SYMBOLS:
        item = summary["details"][symbol]
        rows.append(
            {
                "symbol": symbol,
                "shares": round(item["shares"], 4),
                "avg_cost": round(item["avg_cost"], 2),
                "cost": round(item["cost"], 2),
                "market_value": round(item["market_value"], 2),
                "unrealized_pnl": round(item["unrealized_pnl"], 2),
                "realized_pnl": round(item["realized_pnl"], 2),
            }
        )
    return pd.DataFrame(rows)


def build_transaction_dataframe(transactions: List[Dict]) -> pd.DataFrame:
    rows = []
    for idx, tx in enumerate(transactions):
        rows.append(
            {
                "idx": idx,
                "timestamp": tx.get("timestamp", ""),
                "symbol": tx.get("symbol", ""),
                "side": format_side(tx.get("side", "")),
                "price": tx.get("price", 0.0),
                "shares": tx.get("shares", 0.0),
                "amount": tx.get("amount", 0.0),
                "fee": tx.get("fee", 0.0),
                "tax": tx.get("tax", 0.0),
                "total": tx.get("total", 0.0),
            }
        )
    return pd.DataFrame(rows)


def build_portfolio_history(transactions: List[Dict]) -> pd.DataFrame:
    if not transactions:
        return pd.DataFrame()

    tx_rows = []
    for tx in transactions:
        ts = pd.to_datetime(tx.get("timestamp", ""), errors="coerce")
        symbol = tx.get("symbol")
        side = tx.get("side")
        shares = float(tx.get("shares", 0.0))
        total = float(tx.get("total", 0.0))
        if pd.isna(ts) or symbol not in ALLOWED_SYMBOLS or side not in ("buy", "sell"):
            continue
        tx_rows.append(
            {
                "timestamp": ts,
                "date": ts.normalize(),
                "symbol": symbol,
                "side": side,
                "shares": shares,
                "total": total,
            }
        )

    if not tx_rows:
        return pd.DataFrame()

    tx_df = pd.DataFrame(tx_rows).sort_values("timestamp")
    start_date = (tx_df["date"].min() - pd.Timedelta(days=7)).date().isoformat()

    close_0050 = get_price_history_from_start(TW_SYMBOL_MAP["0050"], start_date)
    close_0056 = get_price_history_from_start(TW_SYMBOL_MAP["0056"], start_date)
    if close_0050 is None or close_0056 is None:
        return pd.DataFrame()

    price_df = pd.concat([close_0050, close_0056], axis=1)
    price_df.columns = ["0050", "0056"]
    price_df.index = pd.to_datetime(price_df.index).tz_localize(None).normalize()
    price_df = price_df.sort_index().ffill()
    price_df = price_df[price_df.index >= tx_df["date"].min()]
    if price_df.empty:
        return pd.DataFrame()

    tx_by_day = {
        day: grp.to_dict("records")
        for day, grp in tx_df.groupby("date", sort=True)
    }
    positions = {symbol: Position() for symbol in ALLOWED_SYMBOLS}
    history_rows = []

    for day, px in price_df.iterrows():
        for tx in tx_by_day.get(day, []):
            pos = positions[tx["symbol"]]
            shares = float(tx["shares"])
            total = float(tx["total"])
            if tx["side"] == "buy":
                pos.shares += shares
                pos.cost += total
            else:
                if shares > pos.shares:
                    shares = pos.shares
                if shares > 0:
                    avg = pos.avg_cost
                    pos.shares -= shares
                    pos.cost -= avg * shares

        market_value = sum(positions[s].shares * float(px[s]) for s in ALLOWED_SYMBOLS)
        total_cost = sum(positions[s].cost for s in ALLOWED_SYMBOLS)
        history_rows.append(
            {
                "date": day,
                "總市值": market_value,
                "持倉成本": total_cost,
                "未實現損益": market_value - total_cost,
            }
        )

    return pd.DataFrame(history_rows).set_index("date")


def build_overview_table(summary: Dict) -> pd.DataFrame:
    rows = []
    for symbol in ALLOWED_SYMBOLS:
        item = summary["details"][symbol]
        rows.append(
            {
                "標的": symbol,
                "持有股數": round(item["shares"], 4),
                "均價": round(item["avg_cost"], 2),
                "成本": round(item["cost"], 2),
                "市值": round(item["market_value"], 2),
                "未實現損益": round(item["unrealized_pnl"], 2),
            }
        )
    return pd.DataFrame(rows)


def _empty_chart(message: str) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        template="plotly_dark",
        margin=dict(l=10, r=10, t=30, b=10),
        height=300,
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        annotations=[
            dict(
                text=message,
                x=0.5,
                y=0.5,
                xref="paper",
                yref="paper",
                showarrow=False,
                font=dict(size=13, color="#d8e0ea"),
            )
        ],
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def render_overview_dashboard(transactions: List[Dict], summary: Dict, prices: Dict[str, float]) -> None:
    history = build_portfolio_history(transactions)
    chart_col1, chart_col2, chart_col3 = st.columns(3, gap="medium")

    with chart_col1:
        st.markdown("#### 總價值")
        if not history.empty:
            line_df = history.reset_index().rename(columns={"date": "日期"})
            line_df["日期"] = pd.to_datetime(line_df["日期"]).dt.floor("D")
            line_df = (
                line_df.groupby("日期", as_index=False)["總市值"]
                .last()
                .sort_values("日期")
            )
            fig_line = px.line(
                line_df,
                x="日期",
                y="總市值",
                template="plotly_dark",
                markers=False,
            )
            fig_line.update_traces(
                line=dict(color="#88a6cf", width=2.4),
                mode="lines+markers",
                marker=dict(size=8, color="#d8e0ea", line=dict(width=1, color="#88a6cf")),
            )
            fig_line.update_layout(
                height=300,
                margin=dict(l=10, r=10, t=20, b=20),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                xaxis_title="",
                yaxis_title="",
                yaxis_tickformat=",.0f",
                xaxis=dict(
                    type="date",
                    tickformat="%Y-%m-%d",
                    dtick="D1",
                ),
                font=dict(color="#d8e0ea"),
            )
            st.plotly_chart(fig_line, use_container_width=True, config={"displayModeBar": False})
        else:
            st.plotly_chart(_empty_chart("尚無足夠交易資料"), use_container_width=True, config={"displayModeBar": False})

    alloc_df = pd.DataFrame(
        {
            "標的": list(ALLOWED_SYMBOLS),
            "市值": [summary["details"][s]["market_value"] for s in ALLOWED_SYMBOLS],
        }
    )
    alloc_df = alloc_df[alloc_df["市值"] > 0]
    total_mv = summary["total_market_value"]

    with chart_col2:
        st.markdown("#### 股票")
        if not alloc_df.empty:
            fig_hold = px.pie(
                alloc_df,
                names="標的",
                values="市值",
                hole=0.68,
                color="標的",
                color_discrete_sequence=["#7899c7", "#c3a67a"],
            )
            fig_hold.update_traces(textinfo="percent", textfont_size=11, marker=dict(line=dict(color="#fff", width=1)))
            fig_hold.update_layout(
                height=300,
                margin=dict(l=0, r=0, t=20, b=20),
                template="plotly_dark",
                paper_bgcolor="rgba(0,0,0,0)",
                showlegend=True,
                legend=dict(orientation="h", y=-0.1, font=dict(color="#d8e0ea")),
                annotations=[
                    dict(
                        text=f"{format_currency(total_mv)}<br><span style='font-size:11px;color:#d8e0ea;'>Total</span>",
                        x=0.5,
                        y=0.5,
                        showarrow=False,
                        font=dict(size=16, color="#d8e0ea"),
                    )
                ],
            )
            st.plotly_chart(fig_hold, use_container_width=True, config={"displayModeBar": False})
        else:
            st.plotly_chart(_empty_chart("目前無持倉配置"), use_container_width=True, config={"displayModeBar": False})

    category_df = pd.DataFrame(
        {
            "類別": ["成長（0050）", "現金流（0056）"],
            "市值": [summary["details"]["0050"]["market_value"], summary["details"]["0056"]["market_value"]],
        }
    )
    category_df = category_df[category_df["市值"] > 0]

    with chart_col3:
        st.markdown("#### 類別")
        if not category_df.empty:
            fig_cat = px.pie(
                category_df,
                names="類別",
                values="市值",
                hole=0.68,
                color="類別",
                color_discrete_sequence=["#9b8ac7", "#b98ba8"],
            )
            fig_cat.update_traces(textinfo="percent", textfont_size=11)
            fig_cat.update_layout(
                height=300,
                margin=dict(l=0, r=0, t=20, b=20),
                template="plotly_dark",
                paper_bgcolor="rgba(0,0,0,0)",
                showlegend=True,
                legend=dict(orientation="h", y=-0.1, font=dict(color="#d8e0ea")),
                annotations=[
                    dict(
                        text=f"{len(category_df)}<br><span style='font-size:11px;color:#d8e0ea;'>類別</span>",
                        x=0.5,
                        y=0.5,
                        showarrow=False,
                        font=dict(size=18, color="#d8e0ea"),
                    )
                ],
            )
            st.plotly_chart(fig_cat, use_container_width=True, config={"displayModeBar": False})
        else:
            st.plotly_chart(_empty_chart("目前無類別資料"), use_container_width=True, config={"displayModeBar": False})

    # 投資組合明細已整合至上方 0050/0056 卡片，避免重複資訊。


def render_add_transaction(transactions: List[Dict]) -> None:
    st.subheader("新增交易")
    col1, col2 = st.columns(2)
    symbol = col1.selectbox("股票代號", ALLOWED_SYMBOLS)
    side = col2.selectbox(
        "買賣方向",
        ("buy", "sell"),
        format_func=lambda v: "買進" if v == "buy" else "賣出",
    )

    price = st.number_input("成交均價", min_value=0.0, value=180.0, step=0.1)
    fee = st.number_input("手續費", min_value=0.0, value=0.0, step=1.0)
    tax = st.number_input("交易稅", min_value=0.0, value=0.0, step=1.0)

    shares = st.number_input("股數", min_value=0.0, value=100.0, step=1.0)
    amount = shares * price
    st.caption(f"買賣金額（不含手續費/稅）：約 {amount:,.2f}")

    submit = st.button("儲存交易", type="primary", use_container_width=True)

    if submit:
        if price <= 0:
            st.error("成交均價必須大於 0")
            return
        if price > MAX_PRICE:
            st.error(f"成交均價過大，請小於 {MAX_PRICE:,.0f}")
            return
        if shares <= 0:
            st.error("股數必須大於 0")
            return
        if shares > MAX_SHARES:
            st.error(f"股數過大，請小於 {MAX_SHARES:,.0f}")
            return
        if fee > MAX_FEE_TAX or tax > MAX_FEE_TAX:
            st.error(f"手續費/交易稅過大，請小於 {MAX_FEE_TAX:,.0f}")
            return
        total = amount + fee + tax if side == "buy" else amount - fee - tax
        transactions.append(
            {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "symbol": symbol,
                "side": side,
                "price": float(price),
                "shares": float(shares),
                "amount": float(amount),
                "fee": float(fee),
                "tax": float(tax),
                "total": float(total),
            }
        )
        save_transactions(transactions)
        st.success("交易已儲存")
        st.rerun()


def render_saving_goal_card() -> None:
    saving_settings = load_saving_settings()
    current_savings = float(saving_settings["current_savings"])
    savings_goal = float(saving_settings["savings_goal"])
    monthly_saving = float(saving_settings["monthly_saving"])
    goal_ratio = (current_savings / savings_goal * 100) if savings_goal > 0 else 0.0
    eta_text = "請設定目標與每月存入"
    if savings_goal > current_savings and monthly_saving > 0:
        months_left = int((savings_goal - current_savings + monthly_saving - 1) // monthly_saving)
        eta_text = f"預估約 {months_left} 個月達標"
    elif savings_goal > 0 and current_savings >= savings_goal:
        eta_text = "目標已達成，請設定下一個目標"

    st.markdown(
        f"""
        <div class="section-card">
            <div class="quote-title">存錢目標</div>
            <div class="saving-kpi">
                {format_currency(current_savings)} / {format_currency(savings_goal)}
            </div>
            <div class="saving-meta">
                達成率：<b>{goal_ratio:.2f}%</b>
            </div>
            <div style="display:flex;align-items:center;gap:8px;margin-top:0.35rem;">
                <div style="flex:1;background:#e2e8f0;border-radius:999px;height:8px;overflow:hidden;">
                    <div style="width:{min(max(goal_ratio, 0.0), 100.0):.2f}%;height:8px;background:linear-gradient(90deg,#2563eb,#1d4ed8);"></div>
                </div>
                <div style="font-size:0.78rem;color:var(--text-primary);font-weight:700;min-width:44px;text-align:right;">
                    {goal_ratio:.0f}%
                </div>
            </div>
            <div class="saving-meta" style="margin-top:0.35rem;">
                {eta_text}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def summarize_strategy_brief(summary: Dict, prices: Dict[str, float]) -> Dict[str, str]:
    high_6m = get_6m_high(TW_SYMBOL_MAP["0050"])
    drop_pct = 0.0
    add_on = 0.0
    if high_6m and high_6m > 0:
        drop_pct = (prices["0050"] - high_6m) / high_6m * 100
        if drop_pct <= -20:
            add_on = 60000
        elif drop_pct <= -15:
            add_on = 40000
        elif drop_pct <= -10:
            add_on = 20000

    total = summary["total_market_value"]
    target_0050_ratio, target_0056_ratio = 0.75, 0.25
    if total >= 8_000_000:
        target_0050_ratio, target_0056_ratio = 0.65, 0.35
    elif total >= 5_000_000:
        target_0050_ratio, target_0056_ratio = 0.70, 0.30

    rebalance_text = "再平衡：目前無持倉，先建立部位。"
    if total > 0:
        mv_0050 = summary["details"]["0050"]["market_value"]
        mv_0056 = summary["details"]["0056"]["market_value"]
        weight_0050 = mv_0050 / total * 100
        weight_0056 = mv_0056 / total * 100
        out_of_range = (
            weight_0050 > (target_0050_ratio * 100 + 5)
            or weight_0050 < (target_0050_ratio * 100 - 10)
            or weight_0056 > (target_0056_ratio * 100 + 10)
            or weight_0056 < (target_0056_ratio * 100 - 5)
        )
        if out_of_range:
            target_0050 = total * target_0050_ratio
            gap_0050 = target_0050 - mv_0050
            if gap_0050 > 0:
                rebalance_text = f"再平衡：偏離區間，優先補 0050 約 {format_currency(gap_0050)}。"
            else:
                rebalance_text = f"再平衡：偏離區間，優先補 0056 約 {format_currency(abs(gap_0050))}。"
        else:
            rebalance_text = "再平衡：目前在容忍區間內，維持固定投入即可。"

    reminder_text = "提醒：薪轉後單次買入，不追高、不停扣。"
    h_1m = get_price_history(TW_SYMBOL_MAP["0050"], period="1mo")
    if h_1m is not None and not h_1m.empty:
        month_high = float(h_1m.max())
        month_drop = (prices["0050"] - month_high) / month_high * 100 if month_high > 0 else 0.0
        if month_drop <= -5:
            reminder_text = "提醒：本月回檔 >= 5%，薪轉後可延後 3~5 天再單次買入。"

    if add_on > 0:
        reminder_text += f" 目前建議加碼 0050 {format_currency(add_on)}。"
    return {"rebalance_text": rebalance_text, "reminder_text": reminder_text}


def render_saving_goal_settings() -> None:
    saving_settings = load_saving_settings()
    with st.expander("設定存錢目標", expanded=False):
        col_s1, col_s2 = st.columns(2)
        new_current = col_s1.number_input(
            "目前存款",
            min_value=0.0,
            value=float(saving_settings["current_savings"]),
            step=1000.0,
            key="saving_current_panel",
        )
        new_goal = col_s2.number_input(
            "目標金額",
            min_value=0.0,
            value=float(saving_settings["savings_goal"]),
            step=10000.0,
            key="saving_goal_panel",
        )
        new_monthly = st.number_input(
            "每月預計存入",
            min_value=0.0,
            value=float(saving_settings["monthly_saving"]),
            step=1000.0,
            key="saving_monthly_panel",
        )
        if st.button("儲存存錢設定", use_container_width=True, key="save_saving_panel"):
            save_saving_settings(new_current, new_goal, new_monthly)
            st.success("已更新存錢目標")
            st.rerun()


def render_strategy_signals(summary: Dict, prices: Dict[str, float]) -> None:
    st.markdown("#### 策略建議")
    st.caption("燈號規則：綠=正常 DCA、黃=回檔可加碼、紅=超區間先再平衡。")
    st.caption("執行方式：薪水入帳後每月單次買入（不分批）。")
    render_saving_goal_settings()

    high_6m = get_6m_high(TW_SYMBOL_MAP["0050"])
    add_on = 0.0
    drop_pct = 0.0
    market_state = "資料不足"
    if high_6m and high_6m > 0:
        drop_pct = (prices["0050"] - high_6m) / high_6m * 100
        if drop_pct <= -20:
            add_on = 60000
        elif drop_pct <= -15:
            add_on = 40000
        elif drop_pct <= -10:
            add_on = 20000

        market_state = "正常（±10%）"
        if drop_pct <= -20:
            market_state = "大跌（<= -20%）"
        elif drop_pct <= -10:
            market_state = "回檔（-10% ~ -20%）"
        elif drop_pct >= 20:
            market_state = "大漲（>= +20%）"

    total = summary["total_market_value"]
    total_cost = summary["total_cost"]
    target_0050_ratio = 0.75
    target_0056_ratio = 0.25
    if total >= 8_000_000:
        target_0050_ratio = 0.65
        target_0056_ratio = 0.35
    elif total >= 5_000_000:
        target_0050_ratio = 0.70
        target_0056_ratio = 0.30

    weight_0050 = 0.0
    weight_0056 = 0.0
    out_of_range = False
    if total > 0:
        mv_0050 = summary["details"]["0050"]["market_value"]
        mv_0056 = summary["details"]["0056"]["market_value"]
        weight_0050 = mv_0050 / total * 100
        weight_0056 = mv_0056 / total * 100
        out_of_range = (
            weight_0050 > (target_0050_ratio * 100 + 5)
            or weight_0050 < (target_0050_ratio * 100 - 10)
            or weight_0056 > (target_0056_ratio * 100 + 10)
            or weight_0056 < (target_0056_ratio * 100 - 5)
        )
    # 三色燈號卡
    if out_of_range:
        signal_title = "紅燈：優先再平衡"
        signal_message = "配置超出容忍區間，先用新資金修正權重，再考慮小額賣出。"
        signal_bg = "#fee2e2"
        signal_color = "#991b1b"
    elif high_6m and drop_pct <= -10:
        signal_title = "黃燈：回檔可加碼"
        signal_message = f"0050 跌幅 {drop_pct:.2f}%，建議加碼 0050 {format_currency(add_on)}。"
        signal_bg = "#fef3c7"
        signal_color = "#92400e"
    else:
        signal_title = "綠燈：正常 DCA"
        signal_message = "維持每月 75/25 定期投入，不追高、不中斷。"
        signal_bg = "#dcfce7"
        signal_color = "#166534"

    st.markdown(
        f"""
        <div style="background:{signal_bg};color:{signal_color};border-radius:12px;padding:0.8rem 0.9rem;margin-bottom:0.7rem;border:1px solid rgba(15,23,42,0.08);">
            <div style="font-weight:700;">{signal_title}</div>
            <div style="margin-top:0.2rem;">{signal_message}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.caption("再平衡與提醒已整合到上方『整體績效』卡片。")

    if high_6m and high_6m > 0:
        st.caption(f"0050 相對六個月高點：{drop_pct:.2f}%｜市場狀態：{market_state}")


def render_transaction_management(transactions: List[Dict]) -> None:
    st.subheader("交易紀錄")
    if not transactions:
        st.write("目前無交易紀錄")
        return

    df = build_transaction_dataframe(transactions)
    display_df = pd.DataFrame(
        {
            "idx": df["idx"].astype(int),
            "時間": pd.to_datetime(df["timestamp"], errors="coerce").dt.strftime("%Y-%m-%d").fillna(""),
            "股票代號": df["symbol"],
            "買賣": df["side"],
            "成交均價": df["price"].astype(float).map(lambda v: f"{v:,.2f}"),
            "股數": df["shares"].astype(float).map(lambda v: f"{v:,.4f}"),
            "金額": df["amount"].astype(float).map(lambda v: f"{v:,.2f}"),
            "手續費": df["fee"].astype(float).map(lambda v: f"{v:,.2f}"),
            "交易稅": df["tax"].astype(float).map(lambda v: f"{v:,.2f}"),
            "總額": df["total"].astype(float).map(lambda v: f"{v:,.2f}"),
        }
    )

    prev_select_all = st.session_state.get("tx_select_all_prev", False)
    select_all = st.checkbox("全選交易", key="tx_select_all")
    if select_all != prev_select_all:
        for idx in display_df["idx"].tolist():
            st.session_state[f"tx_select_{idx}"] = bool(select_all)
    st.session_state["tx_select_all_prev"] = select_all

    col_ratios = [0.42, 1.05, 0.9, 0.7, 0.9, 1.05, 1.2, 0.8, 0.8, 1.2]
    header_cols = st.columns(col_ratios, gap="small")
    header_labels = ["勾選", "時間", "股票代號", "買賣", "成交均價", "股數", "金額", "手續費", "交易稅", "總額"]
    for col, label in zip(header_cols, header_labels):
        col.markdown(
            f"<div style='color:var(--text-primary);font-size:0.95rem;font-weight:700;padding-bottom:0.15rem;'>{label}</div>",
            unsafe_allow_html=True,
        )
    st.markdown("<div style='height:1px;background:#2a3748;margin:0.08rem 0 0.2rem 0;'></div>", unsafe_allow_html=True)

    selected_idx: List[int] = []
    for _, row in display_df.iterrows():
        cols = st.columns(col_ratios, gap="small")
        idx_val = int(row["idx"])
        checked = cols[0].checkbox("", key=f"tx_select_{idx_val}", label_visibility="collapsed")
        if checked:
            selected_idx.append(idx_val)
        row_bg = "rgba(88, 137, 214, 0.16)" if checked else "transparent"
        cell_style_left = (
            "display:block;padding:0.18rem 0.25rem;border-radius:6px;"
            f"background:{row_bg};color:var(--text-primary);font-size:0.86rem;"
        )
        cell_style_right = cell_style_left + "text-align:right;"
        cols[1].markdown(f"<span style='{cell_style_left}'>{row['時間']}</span>", unsafe_allow_html=True)
        cols[2].markdown(f"<span style='{cell_style_left}'>{row['股票代號']}</span>", unsafe_allow_html=True)
        cols[3].markdown(f"<span style='{cell_style_left}'>{row['買賣']}</span>", unsafe_allow_html=True)
        cols[4].markdown(f"<span style='{cell_style_right}'>{row['成交均價']}</span>", unsafe_allow_html=True)
        cols[5].markdown(f"<span style='{cell_style_right}'>{row['股數']}</span>", unsafe_allow_html=True)
        cols[6].markdown(f"<span style='{cell_style_right}'>{row['金額']}</span>", unsafe_allow_html=True)
        cols[7].markdown(f"<span style='{cell_style_right}'>{row['手續費']}</span>", unsafe_allow_html=True)
        cols[8].markdown(f"<span style='{cell_style_right}'>{row['交易稅']}</span>", unsafe_allow_html=True)
        cols[9].markdown(f"<span style='{cell_style_right}'>{row['總額']}</span>", unsafe_allow_html=True)
        st.markdown("<div style='height:1px;background:#2a3748;margin:0.15rem 0 0.2rem 0;'></div>", unsafe_allow_html=True)

    if selected_idx:
        if st.button("🗑️ 刪除勾選", type="primary"):
            st.session_state["tx_delete_confirm"] = True
            st.session_state["tx_delete_targets"] = selected_idx

    if st.session_state.get("tx_delete_confirm", False):
        targets = st.session_state.get("tx_delete_targets", [])
        st.warning(f"確認要刪除 {len(targets)} 筆交易嗎？此操作不可復原。")
        c1, c2 = st.columns(2)
        if c1.button("確認刪除", type="primary", use_container_width=True):
            deleted_count = 0
            for idx in sorted(targets, reverse=True):
                if 0 <= idx < len(transactions):
                    transactions.pop(idx)
                    deleted_count += 1
            save_transactions(transactions)
            st.session_state["tx_delete_confirm"] = False
            st.session_state["tx_delete_targets"] = []
            for idx in display_df["idx"].tolist():
                st.session_state[f"tx_select_{idx}"] = False
            st.success(f"已刪除 {deleted_count} 筆交易")
            st.rerun()
        if c2.button("取消", use_container_width=True):
            st.session_state["tx_delete_confirm"] = False
            st.session_state["tx_delete_targets"] = []
            st.rerun()

    with st.expander("資料還原（備份）", expanded=False):
        st.caption("若誤刪或資料異常，可還原最近一次自動備份。")
        if st.button("還原最近備份", use_container_width=True, key="restore_backup_btn"):
            if restore_payload_from_backup():
                st.success("已還原最近備份。")
                st.rerun()
            st.error("找不到備份檔或還原失敗。")


def main() -> None:
    st.set_page_config(page_title="0050/0056 投資追蹤", layout="wide")
    render_theme()
    st.markdown(
        """
        <div class="hero">
            <h2>0050 / 0056 投資部位追蹤器</h2>
            <p>即時股價、資產總覽、交易管理與再平衡建議，整合在單一儀表板。</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    transactions = load_transactions()

    price_0050 = get_live_price(TW_SYMBOL_MAP["0050"])
    price_0056 = get_live_price(TW_SYMBOL_MAP["0056"])
    if price_0050 is None or price_0056 is None:
        st.error("即時股價抓取失敗，請檢查網路後重試。")
        return

    prices = {"0050": price_0050, "0056": price_0056}
    summary = compute_summary(transactions, prices)
    d50 = summary["details"]["0050"]
    d56 = summary["details"]["0056"]
    hold_0050 = summary["details"]["0050"]["shares"]
    hold_0056 = summary["details"]["0056"]["shares"]
    pnl_50_class = "metric-positive" if d50["unrealized_pnl"] >= 0 else "metric-negative"
    pnl_56_class = "metric-positive" if d56["unrealized_pnl"] >= 0 else "metric-negative"

    c1, c2, c3 = st.columns([1.15, 1.15, 0.9], gap="small")
    c1.markdown(
        f"""
        <div class="section-card">
            <div class="quote-title">0050 即時價</div>
            <div class="quote-value">{price_0050:.2f}</div>
            <div class="quote-holding">
                持有股數：<b>{hold_0050:,.4f}</b>
            </div>
            <div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:0.45rem;">
                <div><div class="quote-title">成本</div><div>{format_currency(d50["cost"])}</div></div>
                <div><div class="quote-title">市值</div><div>{format_currency(d50["market_value"])}</div></div>
                <div><div class="quote-title">未實現</div><div class="{pnl_50_class}">{format_currency(d50["unrealized_pnl"])}</div></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    c2.markdown(
        f"""
        <div class="section-card">
            <div class="quote-title">0056 即時價</div>
            <div class="quote-value">{price_0056:.2f}</div>
            <div class="quote-holding">
                持有股數：<b>{hold_0056:,.4f}</b>
            </div>
            <div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:0.45rem;">
                <div><div class="quote-title">成本</div><div>{format_currency(d56["cost"])}</div></div>
                <div><div class="quote-title">市值</div><div>{format_currency(d56["market_value"])}</div></div>
                <div><div class="quote-title">未實現</div><div class="{pnl_56_class}">{format_currency(d56["unrealized_pnl"])}</div></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with c3:
        render_saving_goal_card()

    strategy_brief = summarize_strategy_brief(summary, prices)
    pnl_class = "metric-positive" if summary["total_pnl"] >= 0 else "metric-negative"
    rate_class = "metric-positive" if summary["return_rate"] >= 0 else "metric-negative"
    st.markdown(
        f"""
        <div class="section-card">
            <div style="font-size:0.85rem;color:var(--text-primary);font-weight:700;margin-bottom:0.45rem;">整體績效</div>
            <div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-bottom:0.55rem;">
                <div><div class="quote-title">總市值</div><div style="font-weight:700;">{format_currency(summary["total_market_value"])}</div></div>
                <div><div class="quote-title">總成本</div><div style="font-weight:700;">{format_currency(summary["total_cost"])}</div></div>
                <div><div class="quote-title">總損益</div><div class="{pnl_class}">{format_currency(summary["total_pnl"])}</div></div>
                <div><div class="quote-title">總報酬率</div><div class="{rate_class}">{summary["return_rate"]:.2f}%</div></div>
            </div>
            <div style="font-size:0.82rem;color:var(--text-primary);">{strategy_brief["rebalance_text"]}</div>
            <div style="font-size:0.82rem;color:var(--text-primary);margin-top:0.2rem;">{strategy_brief["reminder_text"]}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    tab_overview, tab_trade_manage = st.tabs(["總覽儀表板", "交易管理"])

    with tab_overview:
        render_overview_dashboard(transactions, summary, prices)
        st.markdown("---")
        render_strategy_signals(summary, prices)

    with tab_trade_manage:
        left_col, right_col = st.columns([0.85, 1.15], gap="large")
        with left_col:
            render_add_transaction(transactions)
        with right_col:
            render_transaction_management(transactions)


if __name__ == "__main__":
    main()
