"""
Covered Call System - Cloud Edition (中文版)
=============================================
回測 + 篩選 + 操作手冊

執行：
    streamlit run app.py
"""
import streamlit as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from ui.auth import check_password, logout_button
from ui.backtest_page import render_backtest_page
from ui.screener_page import render_screener_page
from ui.manual_page import render_manual_page


# ---------------- Page setup ----------------
st.set_page_config(
    page_title="Covered Call 系統",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
    .main > div { padding-top: 1rem; }
    [data-testid="stMetricValue"] { font-size: 1.4rem; }
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 16px;
        background-color: rgba(38, 39, 48, 0.4);
        border-radius: 4px 4px 0 0;
    }
    .stTabs [aria-selected="true"] {
        background-color: rgba(255, 75, 75, 0.15);
    }
    .stDeployButton { display: none; }
    div[data-testid="stToolbar"] { display: none; }
</style>
""", unsafe_allow_html=True)

# ---------------- Auth ----------------
check_password()

# ---------------- Sidebar ----------------
with st.sidebar:
    st.markdown("### 📈 Covered Call 系統")
    st.caption("雲端版（不含 IBKR 連接）")
    st.divider()
    st.markdown("**功能 Features**")
    st.caption(
        "✅ 多策略回測 Backtest  \n"
        "✅ 機會篩選 Screener  \n"
        "✅ 操作手冊 Manual  \n"
        "❌ IBKR 即時連接*  \n\n"
        "*IBKR 連接需本機安裝"
    )
    st.divider()
    st.markdown("**📚 快速指引**")
    st.caption(
        "**新手第一次用**：先看「📖 操作手冊」  \n"
        "**研究策略**：用「🧪 回測」  \n"
        "**找今天機會**：用「🔍 篩選器」  \n"
    )
    st.divider()
    logout_button()

# ---------------- Main ----------------
st.title("📈 Covered Call 交易系統")
st.caption("回測 4 種策略（CC / CSP / Wheel / PMCC）+ 篩選當前 CC 機會 + 完整操作手冊")

tab_manual, tab_backtest, tab_screener, tab_about = st.tabs([
    "📖 操作手冊", "🧪 回測 Backtest", "🔍 篩選器 Screener", "ℹ️ 關於 About"
])

with tab_manual:
    render_manual_page()

with tab_backtest:
    render_backtest_page()

with tab_screener:
    render_screener_page()

with tab_about:
    st.subheader("ℹ️ 關於本系統 About")
    st.markdown("""
### 🎯 支援策略

| 策略 | 中文 | 結構 |
|---|---|---|
| **CC** | Covered Call 備兌賣權 | 持有 100 股 + 賣 OTM Call |
| **CSP** | Cash-Secured Put 現金擔保賣權 | 持有現金 + 賣 OTM Put |
| **Wheel** | 輪賣策略 | CSP ↔ CC 根據指派狀態自動切換 |
| **PMCC** | Poor Man's CC 窮人版 CC | 買 LEAPS 取代股票 + 賣短期 Call |

### 🧮 Premium 合成模型

由於不訂閱付費歷史選擇權資料，採用以下方法估計 historical premium：

1. **yfinance** 抓取股價歷史與股息
2. 計算 **30 天滾動 Realized Volatility**（已實現波動率）
3. 套用 **IV Risk Premium**（IV ≈ RV × 1.20）
4. **VIX / VXN / RVX** 校準
5. **Black-Scholes** 計算 historical premium

### 📊 Screener 即時資料

使用 **yfinance** 提供的選擇權鏈（免費）：
- ⚠️ 盤中可能延遲 15-20 分鐘
- Greeks（Delta 等）用 Black-Scholes 從 yfinance 的 IV 反算
- 流動性差的合約可能 bid/ask = 0

### 🔧 技術架構

- **後端**：Python + Black-Scholes + yfinance
- **前端**：Streamlit
- **部署**：Streamlit Community Cloud
- **回測引擎**：自行開發，支援 4 策略矩陣比較

### ⚠️ 重要免責聲明

- 本工具僅供分析參考，**不構成投資建議**
- 選擇權交易風險高，可能損失全部投入資金
- 回測結果是模型估算，**不代表未來真實表現**
- 實際交易要考慮稅務、傭金、滑價等本工具未模擬的因素
- 使用前請確認自己理解策略的風險

**詳細風險警告請看「📖 操作手冊」最後一節**

---

📧 有任何問題或建議，請透過 GitHub Issues 反映
""")
