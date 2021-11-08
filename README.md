# cryptobot

## Usage:

Generate a *config.py*, see the example configs in *examples/*

then,

```
BOT_CONFIG_PY=configs/my-config.py \
  DOCKER_USER="$(id -u):$(id -g)" docker-compose up
```

## Config settings:


```
ACCESS_KEY = "ACCESS_KEY"
SECRET_KEY = "SECRET_KEY"
```
If using TESTNET generate a set of keys at https://testnet.binance.vision/
Note that TESTNET is only suitable for bot development and nothing else.
Otherwise use your Binance production keys.


```
MODE = "live"
```
Set the mode where this bot is running,
Options are: *live*, *backtesting*, *testnet*

*live* is the production mode, where the bot will buy and sell with real money.
*backtesting* uses a set of price.log files to simulate buy, sell trades.
*logmode* simply logs all prices into *price.log* files, that can then be used
for backtesting.


```
PAIRING="USDT"
```
The pairing use use to buy crypto with. Available options in Binance are,
*USDT*, *BTC*, *ETH*, *BNB*, *TRX*, *XRP*, *DOGE*


```
INITIAL_INVESTMENT = 100
```
This sets the initial investment to use to buy coin, this amount must be available in
the pairing set in *PAIRING*.


```
PAUSE_FOR = 1
```
How long to pause in seconds before checking Binance prices again.



```
STRATEGY="buy_drop_sell_recovery_strategy"
```
Describes which strategy to use when buying/selling coins, available options are
*buy_moon_sell_recovery_strategy*, *buy_drop_sell_recovery_strategy*.

In the *moon_sell_recovery_strategy*, the bot monitors coin prices and will
buy coins that raised their price over a percentage since the last check.

In the *buy_drop_recovery_strategy*, the bot monitors coin prices and will
buy coins that dropped their price over a percentage against their maximum price.
In this mode, the bot won't buy a coin as soon the price drops, but will keep
monitoring its price allowing the price to go further down and only buy when the
price raises again by a certain percentage amount.
This works so that we are buying the coin after a downhill period as finished
and the coin started its recovery.

In both strategies, the bot when holding a coin that achieved its target price,
won't sell the coin straight away but let it go up in price. And only when the
price has decreased by a certain percentange, it will then sell the coin.
This allows for ignoring small drops in a coin whose price is slowly going
uphill.


```
BUY_AT_PERCENTAGE = -20
```
The percentage at which we look into start buying a coin.
In the *buy_drop_recovery_strategy* this is the percentage drop in price over
the maximum recorded.
In the *buy_moon_sell_recovery_strategy* this is the price percentage difference
between two periods (PAUSE_FOR). When a coin goes over, lets say +1 in a
PAUSE_FOR of 3600 seconds, then the bot will buy it.


```
SELL_AT_PERCENTAGE = +10
```
The profit percentage at which the bot will consider selling the coin. At this
point the bot will monitor the price until the price drops, at which it will
then sell.


```
STOP_LOSS_AT_PERCENTAGE = -25
```
The price at which the bot will sell a coin straight away to avoid further
losses.


```
TRAIL_TARGET_SELL_PERCENTAGE = -1.5
```
This is the percentage drop in price at which when a coin in profit is sold.
This allows to deal with flutuations in price and avoid selling a coin too soon.
When the price is likely to increase again.


```
TRAIL_RECOVERY_PERCENTAGE = +1.5
```
This is the percentage at which in the strategy
*buy_drop_sell_recovery_strategy* the bot will buy a coin. This reflects the
increase in price since the lowest price recorded for this coin. This setting
allows the bot to wait for a coin to drop over time before buying it, this
essentially is the *recovery* phase of a coin after a large drop in price.



```
HARD_LIMIT_HOLDING_TIME = 604800
```
This settings sets the maximum *age* in seconds that we will hold a coin. At the
end of this period the bot will sell a coin regardless of its value.


```
SOFT_LIMIT_HOLDING_TIME = 7200
```
The *SELL_AT_PERCENTAGE* sets the value at a coin is suitable to be sold at a
profit. If this profit percentage is too high the coin won't sell.
This setting deals with those scenarios by reducing both the
*TRAIL_RECOVERY_PERCENTAGE* and the *SELL_AT_PERCENTAGE* values slowly over
time, until it reaches the *HARD_LIMIT_HOLDING_TIME*.
Therefore increasing the chances of a possible sale at profit.

```
CLEAR_COIN_STATS_AT_BOOT = True
```
The bot saves a couple of files during execution, *.coins.pickle* and
*.wallet.pickle*. These files contain the list of coins the bot bought and
holds, and the different values for all those coins, things like maximum price,
minimum price, dips, and tips. This setting specifies if that data should be
discarded at boot time.

```
NAUGHTY_TIMEOUT = 28800
```
This setting tells the bot how long to ignore a coin after that coin sold at a
loss.


```
CLEAR_COIN_STATS_AT_SALE = True
```
The bot continuously records the minimum and maximum price of all coins.
This option resets the maximum and minimum price of all coins after a sale.
This creates a new candle window starting at the moment of the last coin sold,
avoiding a situation where a coin that had a large increase in price in the past
and dropped won't be continuously bought by the bot as its price is below the
*BUY_AT_PERCENTAGE* quite often.
Essentially, we start with a clean state after a sale, and monitor coin prices
waiting for another drop.



```
SELL_AS_SOON_IT_DROPS = True
```

When the price drops just below the *SELL_AT_PERCENTAGE* if this flag is
enabled, the bot will sell the coin, instead of relying on the
*TRAIL_TARGET_SELL_PERCENTAGE*


```
DEBUG = False
```
Enables debug on the bot.


```
MAX_COINS = 3
```
The maximum number of coins the bot will hold at any time.


```
TICKERS_FILE = "tickers/all.txt"
```
Sets the list of coins the bot monitors for prices and trades.
This list must contain pairings as set in the *PAIRING* setting.


```
TRADING_FEE = 0.01
```
The trading fee in percentage that binance will charge on each buy or sell
operation.


```
PRICE_LOGS = [""]
```
The list of price logs to be used for backtesting.


```
EXCLUDED_COINS = [
    'DOWNUSDT',
    'UPUSDT',
]
```
List of coins that the bot will ignore.
