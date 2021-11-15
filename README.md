jzRryptoBot - Binance Trading Bot

A python based trading bot for Binance, which relies heavily on backtesting.

Currently provides two strategies, *buy_drop_sell_recovery_strategy* and
*buy_moon_sell_recovery_strategy*. How these strategies work is described below.

This bot only buys coins specifically listed in its configuration,
the way this works is that each coin is giving its own set of settings,
lets call it a 'profile'.

These profiles is what the bot uses to buy and sell coins, for example when
using the *buy_drop_sell_recovery_strategy* I specify that I want the bot to
buy *BTCUSDT* when the price initially drops by at least 10%,
followed by a recovery of at least 1%. And that it then looks into selling that
coin at at a 6% profit upwards, and that the bot will sell the coin when the
price then drops by at least 1%.

To prevent loss, I set the STOP LOSS at -10% over the price paid for the coin.

To avoid periods of volatility, in case after a stop-loss I set that I don't
want to buy any more BTCUSDT for at least 86400 seconds. After than the bot will
start looking at buying this coin again.

Some coins might be slow recovering from the price we paid, and take sometime
for its price to raise all the way to the 6% profit we aim for.

To avoid having a bot coin slot locked forever, we set set a TimeToLive on the coins
the bot buys. we call this the *HARD_LIMIT_HOLDING_TIME*. The bot will
forcefully sell the coin regardless of its price when this period expires.

To improve the chances of selling a coin during a slow recovery, we decrease
the target profit percentage gradually until we reach that *HARD_LIMIT_HOLDING_TIME*.

This is done through the *SOFT_LIMIT_HOLDING_TIME*, with this setting we the
number of seconds to wait before the bot starts decreasing the profit target
percentage.


```
TICKERS:
  BTCUSDT:
      SOFT_LIMIT_HOLDING_TIME: 3600
      HARD_LIMIT_HOLDING_TIME: 7200
      BUY_AT_PERCENTAGE: -10.0
      SELL_AT_PERCENTAGE: +6
      STOP_LOSS_AT_PERCENTAGE: -10
      TRAIL_TARGET_SELL_PERCENTAGE: -1.0
      TRAIL_RECOVERY_PERCENTAGE: +1.0
      NAUGHTY_TIMEOUT: 604800
```

In order to test the different 'profiles' for different coins, this bot is
designed to rely mainly on backtesting. For backtesting, this bot provides two
modes for running.

In the *logmode* it records price.logs for all available coins in binance and
store them in the log directory. These logs can then be consumed in
*backtesting* mode.

Just to get started, here is a
[logfile](https://www.dropbox.com/s/1kftndfctc67lje/MYCOINS.log.lz4?dl=0)
for testing at containing a small set of coins

Don't decompress these files, as the bot consumes them compressed in the lz4
format.

Processing each daily logfile takes around 30 seconds, so for a large number of
price log files this can take a long time to run backtesting simulations.
A workaround is to test out each coin individually by generating a price.log
file containing just the coins we care about.

```
rm -f MYCOINS.log
for ta in logs/2021*.lz4
do
lz4cat ${ta} |  egrep -E 'BTCUSDT|ETHUSDT|BNBUSDT|DOTUSDT'>> MYCOINS.log
done
lz4 MYCOINS.log

```

and then use that *MYCOINS.log.lz4* in the PRICE_LOGS configuration setting.
This way each simulation takes just a few seconds.

All backtests are logged into log/backtesting.log.

## Riot/Matrix:

Join on: https://matrix.to/#/#cryptobot:matrix.org


## Usage:

Generate a *config.yaml*, see the example configs in *examples/*

And add your Binance credentials to *.secrets.yaml*.


To run the bot in logmode only, which will generate price logs while its
running.

```
docker run -it \
    -u `id -u` \
    -v $PWD/configs/:/cryptobot/configs/:ro  \
    -v $PWD/log:/cryptobot/log:rw  \
    -v $PWD/.secrets.yaml:/cryptobot/.secrets.yaml  \
    -v $PWD/tickers:/cryptobot/tickers  \
    ghcr.io/azulinho/cryptobot -s .secrets.yaml -c configs/config.yaml -m logmode

```
To run the bot in backtesting, which will perform backtesting on all collected
price logs based on the provided config.yaml.

All logs should be compressed in *lz4* format, prior to backtesting.

```
docker run -it \
    -u `id -u` \
    -v $PWD/configs/:/cryptobot/configs/:ro  \
    -v $PWD/log:/cryptobot/log:rw  \
    -v $PWD/.secrets.yaml:/cryptobot/.secrets.yaml  \
    -v $PWD/tickers:/cryptobot/tickers  \
    ghcr.io/azulinho/cryptobot -s .secrets.yaml -c configs/config.yaml -m backtesting

```

Finally, to run in live trading mode,

```
docker run -it \
    -u `id -u` \
    -v $PWD/configs/:/cryptobot/configs/:ro  \
    -v $PWD/log:/cryptobot/log:rw  \
    -v $PWD/.secrets.yaml:/cryptobot/.secrets.yaml  \
    -v $PWD/tickers:/cryptobot/tickers  \
    ghcr.io/azulinho/cryptobot -s .secrets.yaml -c configs/config.yaml -m live

```


## Secrets:


```
ACCESS_KEY: "ACCESS_KEY"
SECRET_KEY: "SECRET_KEY"

```

## Config settings:

If using TESTNET generate a set of keys at https://testnet.binance.vision/

Note that TESTNET is only suitable for bot development and nothing else.
Otherwise use your Binance production keys.


```
MODE: "live"
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
INITIAL_INVESTMENT: 100
```
This sets the initial investment to use to buy coin, this amount must be available in
the pairing set in *PAIRING*.


```
PAUSE_FOR: 1
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
BUY_AT_PERCENTAGE: -20
```
The percentage at which we look into start buying a coin.

In the *buy_drop_recovery_strategy* this is the percentage drop in price over
the maximum recorded.

In the *buy_moon_sell_recovery_strategy* this is the price percentage difference
between two periods (PAUSE_FOR). When a coin goes over, lets say +1 in a
PAUSE_FOR of 3600 seconds, then the bot will buy it.


```
SELL_AT_PERCENTAGE: +10
```
The profit percentage at which the bot will consider selling the coin. At this
point the bot will monitor the price until the price drops, at which it will
then sell.


```
STOP_LOSS_AT_PERCENTAGE: -25
```
The price at which the bot will sell a coin straight away to avoid further
losses.


```
TRAIL_TARGET_SELL_PERCENTAGE: -1.5
```
This is the percentage drop in price at which when a coin in profit is sold.

This allows to deal with flutuations in price and avoid selling a coin too soon.
When the price is likely to increase again.


```
TRAIL_RECOVERY_PERCENTAGE: +1.5
```
This is the percentage at which in the strategy
*buy_drop_sell_recovery_strategy* the bot will buy a coin. This reflects the
increase in price since the lowest price recorded for this coin. This setting
allows the bot to wait for a coin to drop over time before buying it, this
essentially is the *recovery* phase of a coin after a large drop in price.



```
HARD_LIMIT_HOLDING_TIME: 604800
```
This settings sets the maximum *age* in seconds that we will hold a coin. At the
end of this period the bot will sell a coin regardless of its value.


```
SOFT_LIMIT_HOLDING_TIME: 7200
```
The *SELL_AT_PERCENTAGE* sets the value at a coin is suitable to be sold at a
profit. If this profit percentage is too high the coin won't sell.

This setting deals with those scenarios by reducing both the
*TRAIL_RECOVERY_PERCENTAGE* and the *SELL_AT_PERCENTAGE* values slowly over
time, until it reaches the *HARD_LIMIT_HOLDING_TIME*.

Therefore increasing the chances of a possible sale at profit.

```
CLEAR_COIN_STATS_AT_BOOT: True
```
The bot saves a couple of files during execution, *.coins.pickle* and
*.wallet.pickle*. These files contain the list of coins the bot bought and
holds, and the different values for all those coins, things like maximum price,
minimum price, dips, and tips. This setting specifies if that data should be
discarded at boot time.

```
NAUGHTY_TIMEOUT: 28800
```
This setting tells the bot how long to ignore a coin after that coin sold at a
loss.


```
CLEAR_COIN_STATS_AT_SALE: True
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
SELL_AS_SOON_IT_DROPS: True
```

When the price drops just below the *SELL_AT_PERCENTAGE* if this flag is
enabled, the bot will sell the coin, instead of relying on the
*TRAIL_TARGET_SELL_PERCENTAGE*


```
DEBUG: False
```
Enables debug on the bot.


```
MAX_COINS: 3
```
The maximum number of coins the bot will hold at any time.


```
TICKERS: {}
```
Sets the list of coins the bot monitors for prices and trades.
This list must contain pairings as set in the *PAIRING* setting.


```
TRADING_FEE: 0.01
```
The trading fee in percentage that binance will charge on each buy or sell
operation.


```
PRICE_LOGS: [""]
```
The list of price logs to be used for backtesting.


```
EXCLUDED_COINS: [
    'DOWNUSDT',
    'UPUSDT',
]
```
List of coins that the bot will ignore.
