"""Default configuration."""

# IBKR connection
IBKR_HOST = "127.0.0.1"
IBKR_PORT_PAPER = 7497
IBKR_PORT_LIVE = 7496
IBKR_CLIENT_ID = 1

# Default watchlist for screening (when no stock positions to scan)
DEFAULT_WATCHLIST = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA",
    "AMD", "INTC", "COIN", "PLTR", "SOFI", "F", "BAC", "T",
    "PFE", "KO", "VZ", "XOM", "CVX",
]

# Screening defaults
DEFAULT_CONFIG = {
    "min_delta": 0.15,
    "max_delta": 0.35,
    "min_premium_pct": 0.5,
    "min_annualized_return": 12.0,
    "min_iv_rank": 30.0,
    "min_dte": 21,
    "max_dte": 50,
    "min_volume": 10,
    "min_open_interest": 100,
    "max_bid_ask_spread_pct": 10.0,
    "min_otm_pct": 2.0,
}
