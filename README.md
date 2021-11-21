# CryptoBot - Binance Trading Bot

A python based trading bot for Binance, which relies heavily on backtesting.

1. [Overview](#overview)
2. [Riot/Matrix](#riot/matrix)
3. [Usage](#usage)
4. [Config settings](#config-settings)
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
   * [DOWNTREND_DAYS](#downtrend_days)
   * [CLEAR_COIN_STATS_AT_BOOT](#clear_coin_stats_at_boot)
   * [NAUGHTY_TIMEOUT](#naughty_timeout)
   * [CLEAR_COIN_STATS_AT_SALE](#clear_coin_stats_at_sale)
   * [SELL_AS_SOON_AS_IT_DROPS](#sell_as_soon_as_it_drops)
   * [DEBUG](#debug)
   * [MAX_COINS](#max_coins)
   * [TICKERS](#tickers)
   * [TRADING_FEE](#trading_fee)
   * [PRICE_LOGS](#price_logs)

## Overview

The bot while running saves the current market price for all coins available in
binance into *price.log* logfiles. These logfiles are used to simulate different
backtesting scenarios and manipulate how the bot buys/sells crypto.


This bot currently provides three strategies:

- *buy_drop_sell_recovery_strategy*
- *buy_moon_sell_recovery_strategy*
- *buy_on_recovery_after_n_days_downtrend_strategy*

The way these strategies work is described later in this README.

While the price for every available coin is recorded in the *price.log*
logfiles, the bot will only act to buy or sell coins for coins listed
specifically on its configuration.

Each coin is defined in the configuration which a set of values for when to
buy and sell. This allows us to tell the Bot how it handles different coins in
regards to their current state. For example, a high volatily coin that drops 10%
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

So for example for the *buy_drop_sell_recovery_strategy*:

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
on the coins the bot buys. we call this limit *HARD_LIMIT_HOLDING_TIME*.
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
      DOWNTREND_DAYS: 0 # unused on this strategy
```

In order to test the different 'profiles' for different coins, this bot is
designed to rely mainly on backtesting.

For backtesting, this bot provides two modes of operation:

* logmode
* backtesting

In the *logmode* it records price.logs for all available coins in binance and
store them in the log directory. These logs can then be consumed in
*backtesting* mode.

Just to get started, here is a
[logfile](https://www.dropbox.com/s/1kftndfctc67lje/MYCOINS.log.lz4?dl=0)
for testing containing a small set of coins

Don't bother decompressing these files, as the bot consumes them compressed
in the lz4 format.

Processing each daily logfile takes around 30 seconds, so for a large number of
price log files this can take a long time to run backtesting simulations.
A workaround is to test out each coin individually by generating a price.log
file containing just the coins we care about.

```
rm -f log/MYCOINS.log
docker run -it --user=`id -u` -v $PWD/log:/log --workdir /log azulinho/lz4 sh -c "ls *.log.lz4| xargs -i lz4cat {} |egrep -E 'BTCUSDT|ETHUSDT|BNBUSDT|DOTUSDT' >> MYCOINS.log"
docker run -it --user=`id -u` -v $PWD/log:/log --workdir /log azulinho/lz4 sh -c "lz4 MYCOINS.log"
```

Then we can use that *MYCOINS.log.lz4* in the *PRICE_LOGS* configuration setting.
This way each simulation takes just a few seconds.

```
PRICE_LOGS:
  - "log/MYCOINS.log.lz4"

```

So that we can review the different backtesting results according to their
applied configurations, all backtests are logged into a file called *log/backtesting.log*.


## Riot/Matrix

If you need help, bring snacks and pop over at:

Join on: https://matrix.to/#/#cryptobot:matrix.org


DO NOT USE github issues to ask for help. I have no time for you. You'll be told off.

Also: *NO TORIES or BREXITERS*, this is not negotiable.


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

5. Add your Binance credentials to */secrets/prod.yaml*.
   See the [example
   secrets.yaml](https://github.com/Azulinho/cryptobot/blob/master/examples/secrets.yaml) file


```
ACCESS_KEY: "ACCESS_KEY"
SECRET_KEY: "SECRET_KEY"

```

When running the bot for the first time, you'll need to generate some
   *price.log* files for backtesting.

You can use the sample [logfile](https://www.dropbox.com/s/1kftndfctc67lje/MYCOINS.log.lz4?dl=0)
for testing containing a small set of coins

6. Run the bot in *logmode* only, which will generate price logs while its
running. But not buy or sell anything.

```
U="$(id -u)" G="$(id -g)" docker-compose run cryptobot \
    -s /secrets/prod.yaml \
    -c /configs/config.yaml -m logmode
```

When there is enough data for backtesting in our price.log files, we can now
run a new instance of the bot in *backtesting* mode.

5. Compress all the logs, except for the current live logfile in *lz4* format.

```
docker run -it --user=`id -u` -v $PWD/log:/log --workdir /log azulinho/lz4 sh -c "ls *.log| xargs -i lz4 {}"
```

6. Update the config.yaml file and include the list of logfiles we are using for
our backtesting.

```
PRICE_LOGS:
  - "log/20210922.log.lz4"
  - "log/20210923.log.lz4"
```

7. run the bot in backtesting mode, which will perform simulated buys/sells on
all collected price logs based on the provided config.yaml.


```
U="$(id -u)" G="$(id -g)" docker-compose run cryptobot \
    -s /secrets/prod.yaml \
    -c /configs/config.yaml -m backtesting
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
U="$(id -u)" G="$(id -g)" docker-compose run cryptobot \
    -s /secrets/prod.yaml \
    -c /configs/config.yaml -m live
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
STRATEGY: "buy_drop_sell_recovery_strategy"
```
Describes which strategy to use when buying/selling coins, available options are
*buy_moon_sell_recovery_strategy*, *buy_drop_sell_recovery_strategy*,
*buy_on_recovery_after_n_days_downtrend_strategy*

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
      DOWNTREND_DAYS: 0 # unused in this strategy
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
      DOWNTREND_DAYS: 0 # unused in this strategy
```

The *buy_on_recovery_after_n_days_downtrend_strategy* relies on averaged prices
from the last *DOWNTREND_DAYS* days. It will look to buy a coin which price has
gone down for a certain number of days, and as now recovered in a percentage
higher than *TRAIL_RECOVERY_PERCENTAGE* over the average of the last day.

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
      BUY_AT_PERCENTAGE: -99999.0 # unused
      SELL_AT_PERCENTAGE: +6
      STOP_LOSS_AT_PERCENTAGE: -9
      TRAIL_TARGET_SELL_PERCENTAGE: -1.0
      TRAIL_RECOVERY_PERCENTAGE: +1.0
      NAUGHTY_TIMEOUT: 604800
      DOWNTREND_DAYS: 3
```

### BUY_AT_PERCENTAGE

```
BUY_AT_PERCENTAGE: -20
```
The percentage at which we look into start buying a coin.

In the *buy_drop_recovery_strategy* this is the percentage drop in price over
the maximum recorded.

In the *buy_moon_sell_recovery_strategy* this is the price percentage difference
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
*buy_drop_sell_recovery_strategy* the bot will buy a coin. This reflects the
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

### DOWNTREND_DAYS

Sets the number of days where the bot looks for a downtrend in prices, before
buying a coin.
This works together with the *TRAIL_RECOVERY_PERCENTAGE* option.

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
