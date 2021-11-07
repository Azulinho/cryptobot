ACCESS_KEY = "PROD_ACCESS_KEY"
SECRET_KEY = "PROD_SECRET_KEY"
MODE = "live"

PAUSE_FOR = 1
INITIAL_INVESTMENT = 100
MAX_COINS = 4
PAIRING="USDT"
SOFT_LIMIT_HOLDING_TIME = 86400
HARD_LIMIT_HOLDING_TIME = 604800
BUY_AT_PERCENTAGE = +1.0
SELL_AT_PERCENTAGE = +5
STOP_LOSS_AT_PERCENTAGE = -25
CLEAR_COIN_STATS_AT_BOOT = True
TRAIL_TARGET_SELL_PERCENTAGE = -0.5
TRAIL_RECOVERY_PERCENTAGE = +0
NAUGHTY_TIMEOUT = 28800
CLEAR_COIN_STATS_AT_SALE = True
DEBUG = False

STRATEGY="buy_moon_sell_recovery_strategy"
#STRATEGY="buy_drop_sell_recovery_strategy"

TICKERS_FILE = "tickers/all.txt"
TRADING_FEE = 0.1

PRICE_LOGS = [""]

EXCLUDED_COINS = [
    'DOWNUSDT',
    'UPUSDT',
]
