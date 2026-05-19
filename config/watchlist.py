"""
CC-friendly watchlist - 適合做 Covered Call 的標的清單
=====================================================
篩選標準：
  - 高流動性（每日成交量 > 1M）
  - 有活躍的選擇權市場
  - 大型/中型市值
  - 避免迷因股、垃圾股
"""

# 大型科技 (Mega Cap Tech)
MEGA_CAP_TECH = [
    "AAPL",   # Apple
    "MSFT",   # Microsoft
    "GOOGL",  # Alphabet
    "AMZN",   # Amazon
    "META",   # Meta
    "NVDA",   # Nvidia
    "TSLA",   # Tesla
    "NFLX",   # Netflix
]

# 大型股 (Large Cap)
LARGE_CAP = [
    "AMD",    # Advanced Micro Devices
    "INTC",   # Intel
    "CRM",    # Salesforce
    "ORCL",   # Oracle
    "ADBE",   # Adobe
    "PYPL",   # PayPal
    "DIS",    # Disney
    "BA",     # Boeing
    "JPM",    # JPMorgan
    "BAC",    # Bank of America
    "WFC",    # Wells Fargo
    "GS",     # Goldman Sachs
    "V",      # Visa
    "MA",     # Mastercard
    "WMT",    # Walmart
    "COST",   # Costco
    "HD",     # Home Depot
    "MCD",    # McDonald's
    "KO",     # Coca-Cola
    "PEP",    # Pepsi
    "PFE",    # Pfizer
    "MRK",    # Merck
    "JNJ",    # Johnson & Johnson
    "UNH",    # UnitedHealth
    "XOM",    # ExxonMobil
    "CVX",    # Chevron
    "T",      # AT&T
    "VZ",     # Verizon
    "F",      # Ford
    "GM",     # GM
]

# 主流 ETF (適合做 CC，IV 較低但很穩)
ETFS = [
    "SPY",    # S&P 500
    "VOO",    # Vanguard S&P 500
    "QQQ",    # Nasdaq 100
    "IWM",    # Russell 2000
    "DIA",    # Dow Jones
    "EEM",    # 新興市場
    "GLD",    # 黃金
    "TLT",    # 20+ 年國債
    "XLK",    # 科技 ETF
    "XLF",    # 金融 ETF
    "XLE",    # 能源 ETF
    "ARKK",   # ARK Innovation
]

# 完整熱門清單
DEFAULT_WATCHLIST = MEGA_CAP_TECH + LARGE_CAP + ETFS

# 預設清單分類（給 UI 顯示用）
WATCHLIST_CATEGORIES = {
    "🔥 大型科技 (8)": MEGA_CAP_TECH,
    "🏛️ 大型股 (30)": LARGE_CAP,
    "📊 主流 ETF (12)": ETFS,
    "🎯 全部 (50)": DEFAULT_WATCHLIST,
}
