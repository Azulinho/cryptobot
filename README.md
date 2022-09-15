# CryptoBot - Binance Trading Bot

A python based trading bot for Binance, which relies heavily on backtesting.

 1. [Overview](#overview)
 2. [Discord](#discord)
 3. [Getting started](#getting-started)
 4. [Usage](#usage)
 5. [Config settings](#config-settings)
    * [PAIRING](#pairing)
    * [INITIAL_INVESTMENT](#initial_investment)
    * [PAUSE_FOR](#pause_for)
    * [STRATEGY](#strategy)
    * [BUY_AT_PERCENTAGE](#buy_at_percentage)
    * [SELL_AT_PERCENTAGE](#sell_at_percentage)
    * [STOP_LOSS_AT_PERCENTAGE](#stop_loss_at_percentage)
    * [TRAIL_TARGET_SELL_PERCENTAGE](#trail_target_sell_percentage)
    * [TRAIL_RECOVERY_PERCENTAGE](#trail_recovery_percentage)
    * [HARD_LIMIT_HOLDING_TIME](#hard_limit_holding_time)
    * [SOFT_LIMIT_HOLDING_TIME](#soft_limit_holding_time)
    * [KLINES_TREND_PERIOD](#klines_trend_period)
    * [KLINES_SLICE_PERCENTAGE_CHANGE](#klines_slice_percentage_change)
    * [CLEAR_COIN_STATS_AT_BOOT](#clear_coin_stats_at_boot)
    * [NAUGHTY_TIMEOUT](#naughty_timeout)
    * [CLEAR_COIN_STATS_AT_SALE](#clear_coin_stats_at_sale)
    * [SELL_AS_SOON_AS_IT_DROPS](#sell_as_soon_as_it_drops)
    * [DEBUG](#debug)
    * [MAX_COINS](#max_coins)
    * [TICKERS](#tickers)
    * [TRADING_FEE](#trading_fee)
    * [PRICE_LOGS](#price_logs)
    * [ENABLE_PUMP_AND_DUMP_CHECKS](#enable_pump_and_dump_checks)
    * [ENABLE_NEW_LISTING_CHECKS](#enable_new_listing_checks)
    * [ENABLE_NEW_LISTING_CHECKS_AGE_IN_DAYS](#enable_new_listing_checks_age_in_days)
    * [STOP_BOT_ON_LOSS](#stop_bot_on_loss)
    * [ORDER_TYPE](#order_type)
 6. [Bot command center](#bot-command-center)
 7. [Automated Backtesting](#automated-backtesting)
 8. [Prove automated-backtesting results](#prove-automated-backtesting-results)
 9. [Obtaining old price log files](#obtaining-old-price-log-files)
10. [Development/New features](#development/new-features)


## Overview

This bot looks to buy coins that at have gone down in price recently and are
now recovering from that downtrend. It relies on us specifying different
buy and sell points for each coin individually. For example, we can tell the
bot to buy BTCUSDT when the price drops by at least 6% and recovers by 1%. And
then set it to sell when the price increases by another 2%.
Or we may choose trade differently with another more volatile coin
where we buy the coin when the price drops by 25%, wait for it to recover by 2%
and then sell it at 5% profit.

In order to understand what are the best percentages on when to buy and sell for
each one of the coins available in binance, we use backtesting strategies
on a number of recorded price.logs.
These price.logs can be obtained while the bot is running in a special mode
called *logmode* where it records prices for all the available binance coins
every 1 second or other chosen interval. Or we can obtain 1min interval klines
from binance using a [tool available in this
repository](#obtaining-old-price-log-files).

Then using these price.log files we would run the bot in *backtesting* mode
which would run our buy strategy against those price.log files and simulate
what sort of returns we would get from a specify strategy and a time frame of the market.
In order to help us identify the best buy/sell percentages for each coin, there
is a helper tool in this repo which runs a kind of
[automated-backtesting](#automated-backtesting) against
all the coins in binance and a number of buy/sell percentages and strategies
and returns the best config for each one of those coins. Use it as a starting
point for your own strategy.

The way the bot chooses when to buy is based on a set of strategies which are
defined in the [strategies/](./strategies/) folder in this repo.
You can choose to build your own strategy and place it on the
[strategies/](./strategies) folder,
then either rebuild the bot docker image or just map the file as a volume mount
in the [docker-compose file](./docker-compose.yaml).

This bot currently provides different strategies:

- [*BuyDropSellRecoveryStrategy*](./strategies/BuyDropSellRecoveryStrategy.py)
- [*BuyDropSellRecoveryStrategyWhenBTCisDown*](./strategies/BuyDropSellRecoveryStrategyWhenBTCisDown.py)
- [*BuyDropSellRecoveryStrategyWhenBTCisUp*](./strategies/BuyDropSellRecoveryStrategyWhenBTCisUp.py)
- [*BuyMoonSellRecoveryStrategy*](./strategies/BuyMoonSellRecoveryStrategy.py)
- [*BuyOnGrowthTrendAfterDropStrategy*](./strategies/BuyOnGrowthTrendAfterDropStrategy.py)
- [*BuyOnRecoveryAfterDropDuringGrowthTrendStrategy*](./strategies/BuyOnRecoveryAfterDropDuringGrowthTrendStrategy.py)
- [*BuyOnRecoveryAfterDropFromAverageStrategy*](./strategies/BuyOnRecoveryAfterDropDuringGrowthTrendStrategy.py)

The way some of these strategies work is described later in this README. The
others can be found in the strategy files themselves.

While the price for every available coin is recorded in the *price.log*
logfiles, the bot will only act to buy or sell coins for coins listed
specifically on its configuration.

Each coin is defined in the configuration with a set of values for when to
buy and sell. This allows us to tell the Bot how it handles different coins in
regards to their current state. For example, a high volatile coin that drops 10%
in price is likely to continue dropping further, versus a coin like BTCUSDT that
is relatively stable in price.

With that in mind, we can for example tell the Bot to when this coin drops *x%*
buy it, and when that coin drops *y%* buy it.

We could also let the bot do the opposite, for coins that are going on through
an uptrend, we can tell the bot to as soon a coin increases in value by % over a
period of time, we tell the bot to buy them.

For these different settings we apply to each coin, lets call them profiles for
now. These profile is essentially how the bot makes decisions on which coins to
buy and sell.

So for example for the *BuyDropSellRecoveryStrategy*:

I specify that I want the bot to buy *BTCUSDT* when the price initially drops
by at least 10%, followed by a recovery of at least 1%.

It should then look into selling that coin at at a 6% profit upwards,
and that when it reaches 6% profit, the bot will sell the coin when the price
then drops by at least 1%.

To prevent loss, in case something goes wrong in the market.
I set the STOP LOSS at -10% over the price paid for the coin.

To avoid periods of volatility, in case after a stop-loss I set that I don't
want to buy any more BTCUSDT for at least 86400 seconds. After than the bot will
start looking at buying this coin again.

Some coins might be slow recovering from the price we paid, and take some time
for their price to raise all the way to the 6% profit we aim for.

To avoid having a bot coin slot locked forever, we set set a kind of TimeToLive
on the coins the bot buys. Let's call this limit *HARD_LIMIT_HOLDING_TIME*.
The bot will forcefully sell the coin regardless of its price when this period expires.

To improve the chances of selling a coin during a slow recovery, we decrease
the target profit percentage gradually until we reach that *HARD_LIMIT_HOLDING_TIME*.

This is done through a setting called *SOFT_LIMIT_HOLDING_TIME*, with this
setting we set the number of seconds to wait before the bot starts decreasing
the profit target percentage. Essentially we reduce the target profit until it
meets the current price of the coin.


Below in an example of a *profile* for BTCUSDT,

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
      KLINES_TREND_PERIOD: 0d # unused in this strategy
      KLINES_SLICE_PERCENTAGE_CHANGE: +0 # unused in this strategy
```

In order to test the different 'profiles' for different coins, this bot is
designed to rely mainly on backtesting.

For backtesting, this bot provides two modes of operation:

* logmode
* backtesting

In the *logmode* it records **the current price** for all available binance coins
in daily price.logs and stores them in the log directory.
These logs can then be consumed in *backtesting* mode.

The bot doesn't retrieve historic klines from binance, which are limited to a
minimum of 1min granularity. If you want to pull historic klines from binance,
use the [tool available in this repo](#obtaining-old-price-log-files)

Just to get started, here is a
[logfile](https://www.dropbox.com/s/dqpma82vc4ug7l9/MYCOINS.log.gz?dl=0)
for testing containing a small set of coins

Don't bother decompressing these files, as the bot consumes them compressed
in the .gz format.

Processing each daily logfile on a 1sec interval, takes around 30 seconds, so for a large number of
price log files this can take a long time to run backtesting simulations.
A workaround is to test out each coin individually by generating a price.log
file containing just the coins we care about.

```
rm -f log/MYCOINS.log
ls *.log.gz| xargs -i gzcat {} |egrep -E 'BTCUSDT|ETHUSDT|BNBUSDT|DOTUSDT' >> MYCOINS.log"
gzip MYCOINS.log
```

Then we can use that *MYCOINS.log.gz* in the *PRICE_LOGS* configuration setting.
This way each simulation takes just a few seconds.

```
PRICE_LOGS:
  - "log/MYCOINS.log.gz"

```

So that we can review the different backtesting results according to their
applied configurations, all backtests are logged into a file called *log/backtesting.log*.


## Discord

If you need help, bring snacks and pop over at:

Join on: https://discord.gg/MaMP3gVBdk


DO NOT USE github issues to ask for help. I have no time for you. You'll be told off.

Also: *NO TORIES, NO BREXITERS, NO WINDOWS USERS, NO TWATS*, this is not negotiable.


## Getting started

If you don't know Python you might be better using an
[Online Crypto Trading Bot](https://duckduckgo.com/?q=online+crypto+trading+bot&ia=web) instead.

1. Learn Python https://www.learnpython.org/

2. Learn Docker https://learndocker.online/

3. Learn Git https://www.w3schools.com/git/default.asp


## Usage

1. Install docker as per https://docs.docker.com/get-docker/

2. Install docker-compose as per: https://docs.docker.com/compose/install/

3. Clone this repository:

```
git clone https://github.com/Azulinho/cryptobot.git
```

4. generate a *config.yaml*, see the example configs in the
[examples](https://github.com/Azulinho/cryptobot/tree/master/examples) folder.

Place your new config.yaml file into the *configs/* folder.

5. Add your Binance credentials to */secrets/binance.prod.yaml*.
   See the [example
   secrets.yaml](https://github.com/Azulinho/cryptobot/blob/master/examples/secrets.yaml) file


```
ACCESS_KEY: "ACCESS_KEY"
SECRET_KEY: "SECRET_KEY"

```

When running the bot for the first time, you'll need to generate some
   *price.log* files for backtesting.

You can use the sample
[logfile](https://www.dropbox.com/s/dqpma82vc4ug7l9/MYCOINS.log.gz?dl=0)
for testing containing a small set of coins

6. Run the bot in *logmode* only, which will generate price logs while its
running. But not buy or sell anything.

```
make logmode CONFIG=config.yaml
```

You can also look into the [obtaining old price.log files
tool](#obtaining-old-price-log-files)

When there is enough data for backtesting in our price.log files, we can now
run a new instance of the bot in *backtesting* mode.

5. Compress all the logs, except for the current live logfile in *gz* format.

```
ls *.log| xargs -i gzip -3 {}"
```

6. Update the config.yaml file and include the list of logfiles we are using for
our backtesting.

```
PRICE_LOGS:
  - "log/20210922.log.gz"
  - "log/20210923.log.gz"
```

7. run the bot in backtesting mode, which will perform simulated buys/sells on
all collected price logs based on the provided config.yaml.


```
make backtesting CONFIG=config.yaml
```

8. Update your config.yaml until you are happy with the results and re-run the
   backtesting.

   Some pointers:

   if your coins hit *STOP LOSS*, adjust the following:

   * BUY_AT_PERCENTAGE
   * STOP_LOSS_AT_PERCENTAGE
   * TRAIL_RECOVERY_PERCENTAGE
   * SELL_AT_PERCENTAGE

   if your coins hit *STALE*, adjust the following:

   * SELL_AT_PERCENTAGE
   * HARD_LIMIT_HOLDING_TIME
   * SOFT_LIMIT_HOLDING_TIME

   if the bot buys coins too early, while a coin is still going down, adjust:

   * BUY_AT_PERCENTAGE
   * TRAIL_RECOVERY_PERCENTAGE

9. Finally, when happy run in live trading mode,

```
make live CONFIG=config.yaml
```


## Config settings

Full list of config settings and their use described below:

If using TESTNET generate a set of keys at https://testnet.binance.vision/

Note that TESTNET is only suitable for bot development and nothing else.
Otherwise use your Binance production keys.

### PAIRING

```
PAIRING: "USDT"
```
The pairing use use to buy crypto with. Available options in Binance are,
*USDT*, *BTC*, *ETH*, *BNB*, *TRX*, *XRP*, *DOGE*


### INITIAL_INVESTMENT

```
INITIAL_INVESTMENT: 100
```
This sets the initial investment to use to buy coin, this amount must be available in
the pairing set in *PAIRING*.


### PAUSE_FOR

```
PAUSE_FOR: 1
```
How long to pause in seconds before checking Binance prices again.


### STRATEGY

```
STRATEGY: "BuyDropSellRecoveryStrategy"
```
Describes which strategy to use when buying/selling coins, available options are
*BuyMoonSellRecoveryStrategy*, *BuyDropSellRecoveryStrategy*,
*BuyOnGrowthTrendAfterDropStrategy*

In the *moon_sell_recovery_strategy*, the bot monitors coin prices and will
buy coins that raised their price over a percentage since the last check.

```
PAUSE_FOR: 3600
TICKERS:
  BTCUSDT:
      SOFT_LIMIT_HOLDING_TIME: 4
      HARD_LIMIT_HOLDING_TIME: 96
      BUY_AT_PERCENTAGE: +1
      SELL_AT_PERCENTAGE: +6
      STOP_LOSS_AT_PERCENTAGE: -9
      TRAIL_TARGET_SELL_PERCENTAGE: -1.0
      TRAIL_RECOVERY_PERCENTAGE: +1.0
      NAUGHTY_TIMEOUT: 28800
      KLINES_TREND_PERIOD: 0d # unused in this strategy
      KLINES_SLICE_PERCENTAGE_CHANGE: +0 # unused in this strategy
```

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

Example:

```
TICKERS:
  BTCUSDT:
      SOFT_LIMIT_HOLDING_TIME: 3600
      HARD_LIMIT_HOLDING_TIME: 7200
      BUY_AT_PERCENTAGE: -9
      SELL_AT_PERCENTAGE: +6
      STOP_LOSS_AT_PERCENTAGE: -9
      TRAIL_TARGET_SELL_PERCENTAGE: -1.0
      TRAIL_RECOVERY_PERCENTAGE: +1.0
      NAUGHTY_TIMEOUT: 28800
      KLINES_TREND_PERIOD: 0d # unused in this strategy
      KLINES_SLICE_PERCENTAGE_CHANGE: +0 # unused in this strategy
```

The *BuyOnGrowthTrendAfterDropStrategy* relies on averaged prices
from the last *KLINES_TREND_PERIOD*. It will look to buy a coin which price has
gone down in price according to the *BUY_AT_PERCENTAGE*, and its price has
increased at least *KLINES_SLICE_PERCENTAGE_CHANGE* % in each slice of the
*KLINES_TREND_PERIOD*.

The bot currently records the last 60 seconds, 60 minutes, 24 hours, and
multiple days price averages for evvery coin. The bot requires some additional
development in order for the stored averages to work with *PAUSE_FOR* values
different than 1 second.

Example:

```
TICKERS:
  BTCUSDT:
      SOFT_LIMIT_HOLDING_TIME: 3600
      HARD_LIMIT_HOLDING_TIME: 600000
      BUY_AT_PERCENTAGE: -9.0
      SELL_AT_PERCENTAGE: +6
      STOP_LOSS_AT_PERCENTAGE: -9
      TRAIL_TARGET_SELL_PERCENTAGE: -1.0
      TRAIL_RECOVERY_PERCENTAGE: +0.0 # unused in this strategy
      NAUGHTY_TIMEOUT: 604800
      KLINES_TREND_PERIOD: 2d
      KLINES_SLICE_PERCENTAGE_CHANGE: +1
```

### BUY_AT_PERCENTAGE

```
BUY_AT_PERCENTAGE: -20
```
The percentage at which we look into start buying a coin.

In the *buy_drop_recovery_strategy* this is the percentage drop in price over
the maximum recorded.

In the *BuyMoonSellRecoveryStrategy* this is the price percentage difference
between two periods (PAUSE_FOR). When a coin goes over, lets say +1 in a
PAUSE_FOR of 3600 seconds, then the bot will buy it.


### SELL_AT_PERCENTAGE

```
SELL_AT_PERCENTAGE: +10
```
The profit percentage at which the bot will consider selling the coin. At this
point the bot will monitor the price until the price drops, at which it will
then sell.


### STOP_LOSS_AT_PERCENTAGE

```
STOP_LOSS_AT_PERCENTAGE: -25
```
The price at which the bot will sell a coin straight away to avoid further
losses.


### TRAIL_TARGET_SELL_PERCENTAGE

```
TRAIL_TARGET_SELL_PERCENTAGE: -1.5
```
This is the percentage drop in price at which when a coin in profit is sold.

This allows to deal with flutuations in price and avoid selling a coin too soon.
When the price is likely to increase again.


### TRAIL_RECOVERY_PERCENTAGE

```
TRAIL_RECOVERY_PERCENTAGE: +1.5
```
This is the percentage at which in the strategy
*BuyDropSellRecoveryStrategy* the bot will buy a coin. This reflects the
increase in price since the lowest price recorded for this coin. This setting
allows the bot to wait for a coin to drop over time before buying it, this
essentially is the *recovery* phase of a coin after a large drop in price.


### HARD_LIMIT_HOLDING_TIME

```
HARD_LIMIT_HOLDING_TIME: 604800
```
This settings sets the maximum *age* in seconds that we will hold a coin. At the
end of this period the bot will sell a coin regardless of its value.


### SOFT_LIMIT_HOLDING_TIME

```
SOFT_LIMIT_HOLDING_TIME: 7200
```
The *SELL_AT_PERCENTAGE* sets the value at a coin is suitable to be sold at a
profit. If this profit percentage is too high the coin won't sell.

This setting deals with those scenarios by reducing both the
*TRAIL_RECOVERY_PERCENTAGE* and the *SELL_AT_PERCENTAGE* values slowly over
time, until it reaches the *HARD_LIMIT_HOLDING_TIME*.

Therefore increasing the chances of a possible sale at profit.

### KLINES_TREND_PERIOD

Sets the number of seconds, minutes, hours or days where the bot looks for a
downtrend/uptrend in prices, before buying a coin.

### KLINES_SLICE_PERCENTAGE_CHANGE

Sets the expected percentage change in value of a coin between two slices of
a *KLINES_TREND_PERIOD*. For example if *KLINES_TREND_PERIOD* is 3d and this
parameter is set to +1, it would trigger when a coin has gone up +1% for 3
consecutive days.


### CLEAR_COIN_STATS_AT_BOOT

```
CLEAR_COIN_STATS_AT_BOOT: True
```
The bot saves a couple of files during execution, *.coins.pickle* and
*.wallet.pickle*. These files contain the list of coins the bot bought and
holds, and the different values for all those coins, things like maximum price,
minimum price, dips, and tips. This setting specifies if that data should be
discarded at boot time.

### NAUGHTY_TIMEOUT

```
NAUGHTY_TIMEOUT: 28800
```
This setting tells the bot how long to ignore a coin after that coin sold at a
loss.


### CLEAR_COIN_STATS_AT_SALE

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



### SELL_AS_SOON_AS_IT_DROPS

```
SELL_AS_SOON_IT_DROPS: True
```

When the price drops just below the *SELL_AT_PERCENTAGE* if this flag is
enabled, the bot will sell the coin, instead of relying on the
*TRAIL_TARGET_SELL_PERCENTAGE*


### DEBUG

```
DEBUG: False
```
Enables debug on the bot.


### MAX_COINS

```
MAX_COINS: 3
```
The maximum number of coins the bot will hold at any time.


### TICKERS

```
TICKERS: {}
```
Sets the list of coins the bot monitors for prices and trades.
This list must contain pairings as set in the *PAIRING* setting.


### TRADING_FEE

```
TRADING_FEE: 0.01
```
The trading fee in percentage that binance will charge on each buy or sell
operation.


### PRICE_LOGS

```
PRICE_LOGS: [""]
```
The list of price logs to be used for backtesting.


### ENABLE_PUMP_AND_DUMP_CHECKS

```
ENABLE_PUMP_AND_DUMP_CHECKS: True
```

defaults to True

Checks the price of a coin over the last 2 hours and prevents the bot from
buying if the price 2 hours ago was lower than 1 hour ago (pump) and the current
price is higher than 2 hours ago (dump pending).

### ENABLE_NEW_LISTING_CHECKS

```
ENABLE_NEW_LISTING_CHECKS: True
```

defaults to True

Enable checks for new coin listings.

### ENABLE_NEW_LISTING_CHECKS_AGE_IN_DAYS

```
ENABLE_NEW_LISTING_CHECKS_AGE_IN_DAYS: 31
```

defaults to 31

Checks that we have at least 31 days of price data on a coin, if we don't we
skip buying this coin.


### STOP_BOT_ON_LOSS

```
STOP_BOT_ON_LOSS: True
```

defaults to False

Stops the bot immediately after a STOP_LOSS

### ORDER_TYPE

```
ORDER_TYPE: "MARKET"
```

defaults to MARKET, available options are *MARKET* or *LIMIT*.

Tells the BOT if it should use MARKET order or a LIMIT [FOK](https://academy.binance.com/en/articles/understanding-the-different-order-types) order.


## Bot command center

The bot is running a *pdb* endpoint on container port 5555.

Run the bot as listed above and find the port mapped to 5555

```

 docker ps
 CONTAINER ID   IMAGE                        COMMAND                  CREATED          STATUS          PORTS                                                NAMES
 e6348c68072f   ghcr.io/azulinho/cryptobot   "python -u app.py -s…"   50 seconds ago   Up 49 seconds   0.0.0.0:49153->5555/tcp, :::49153->5555/tcp cryptobot_cryptobot_run_21cc0b86d73d
```

Then,

```
pip install epdb
python
>>> import epdb
>>> epdb.connect(host='127.0.0.1', port=5555)
>>> /cryptobot/app.py(39)control_center()
-> try:
(Epdb)
```

And type :

```
dir(bot)
```

to see all available methods

To exit the debugger, type

```close```

Do not Control-D as it will hang the debugger and you won't be able to
reconnect (To be fixed).


## Automated Backtesting

In the utils/ directory there's a python script to automate backtesting of the
different coins over a period of days. It works by parsing a price.log file
combining a number of days, and running a set of different defined strategies
(config.yamls) against each coin individually. Then gathering the best config
for each coin and combining them into a single tuned config for that particular
strategy. Before running a normal backtesting session using all the coins listed
in that new config.yaml.

Use it as:

1. First compress all non-active logs

```
make compress-logs
```

2. Generate a logfile for the last days we want to test

```
make lastfewdays DAYS=14 PAIR=USDT
mv lastfewdays.USDT.log.gz log/
```

3. Create a backtesting file in configs/automated-backtesting.yaml
   see the examples/automated-backtesting.yaml.


4. Run backtesting on all scenarios listed in automated-backtesting.yaml using
 the lastfewdays.USDT.log.gz created above, and only consume coins that returned
 at least 10% in profit.

This will generate a config.yaml with the coins sorted by which strategy
returned the highest profit for each coin.

```
make automated-backtesting LOGFILE=lastfewdays.USDT.log.gz CONFIG=automated-backtesting.yaml MIN=10 FILTER='' SORTBY='profit'
```

This will generate a config.yaml with the coins sorted by which strategy
returned the highest number of clean wins for each coin. We call clean wins as
bot runs that don't contain any losses, holds or stales, only wins.

```
make automated-backtesting LOGFILE=lastfewdays.USDT.log.gz CONFIG=automated-backtesting.yaml MIN=10 FILTER='' SORTBY='wins'
```

## Prove automated-backtesting results

Using the same config file provided to *automated-backtesting*, this will run
multiple iterations of the automated-testing from a start date to an end date.
It begins by grabbing a set of logfiles from the days prior to the start date,
and running automated-backtesting using those logfiles. Then using the newly
generated tuned config, runs backtesting for a number of days and logs following the
start date. It then repeats this process start the day after the last logfile
backtested through the tuned config, all the way until the end date provided.

```
 make prove-backtesting FROM=20220801 BACKTRACK=90 MIN=9 CONFIG=backtesting.yaml TO=20220831 FORWARD=7 SORTBY=wins
```

## Obtaining old price log files

In the utils/ directory there's a python script that pulls klines from binance
in the format used by this bot.

Use it as:

```
make download-price-logs FROM=20210101 TO=20211231
```

And wait, as this will take a while to run.
If it fails, you can restart it from the day that failed.

All logs will be downloaded to the logs/ directory.



## Development/New features

Want this bot to do something it doesn't do today?

Easy, fork it, make the changes you need, add tests, raise a PR.
