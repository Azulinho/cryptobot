# PROD
ACCESS_KEY = "ACCESSKEY"
SECRET_KEY = "SECRETKEY"
MODE = "analyse"

PAUSE_FOR = 30
INITIAL_INVESTMENT = 100
HOLDING_TIME = 30 # 30 * 240 = 7200s

# this is neat, if the market is looking rubbish adjust the buy,sell,stop
# buy = +0.5, sell = -0.5, sl = -0.5
BUY_AT_PERCENTAGE = 94.0
SELL_AT_PERCENTAGE = 100.5
STOP_LOSS_AT_PERCENTAGE = 97  # this is related to the price we paid on the coin
DEBUG = False

TICKERS = [line.strip() for line in open("tickers.txt")]
TRADING_FEE = "0.01"

PRICE_LOG = "prices.log"

EXCLUDED_COINS = [
    'DOWNUSDT',
    'UPUSDT',
    'BTCUSDT',
    'ETHUSDT',
    'BNBUSDT',
]

# FOR TESTING using TESTNET:
#------------------------------------
# https://testnet.binance.vision/
#MODE = "testnet"  # NOTE: use testnet or analyse
#ACCESS_KEY = "TESTNETACCESSKEY"
#SECRET_KEY = "TESTNETSECRETKEY"
#INITIAL_INVESTMENT = 10000
#PAUSE_FOR = 10
#BUY_AT_PERCENTAGE = 99.999
#SELL_AT_PERCENTAGE = 100.00001
#STOP_LOSS_AT_PERCENTAGE = 99.99999
#EXCLUDED_COINS = [
#  'DOWNUSDT',
#  'UPUSDT',
#]
#PRICE_LOG = "testnet.log"
#TRADING_FEE = "0.01"

# this is low risk, we're likely to be free of coins at the end of the run
#BUY_AT_PERCENTAGE = 91
#SELL_AT_PERCENTAGE = 101  # <-- returns $27 on the 24th
#STOP_LOSS_AT_PERCENTAGE = 97  # this is related to the price we paid on the coin

# this is high risk, higher returns but coins will be left to sell
#BUY_AT_PERCENTAGE = 97
#SELL_AT_PERCENTAGE = 101 # <-- returns a loss of ~$20
#STOP_LOSS_AT_PERCENTAGE = 97  # this is related to the price we paid on the coin

# this might be safe, as it expects quite strong drops
#BUY_AT_PERCENTAGE = 80
#SELL_AT_PERCENTAGE = 110  # <-- returns $40 on the 24th, and another $40 on the 23rd
#STOP_LOSS_AT_PERCENTAGE = 85  # this is related to the price we paid on the coin
