from time import sleep
import re
import math
import sys
import traceback
import json
from os.path import exists

from datetime import datetime
from termcolor import colored, cprint

from functools import wraps, lru_cache
from time import time

from binance.client import Client
from binance.exceptions import BinanceAPIException
from binance.helpers import round_step_size
from requests.exceptions import ReadTimeout, ConnectionError

from config import (
    INITIAL_INVESTMENT,
    HOLDING_TIME,
    BUY_AT_PERCENTAGE,
    SELL_AT_PERCENTAGE,
    STOP_LOSS_AT_PERCENTAGE,
    EXCLUDED_COINS,
    PAUSE_FOR,
    PRICE_LOG,
    ACCESS_KEY,
    SECRET_KEY,
    TICKERS,
    MODE,
    TRADING_FEE,
    DEBUG
)


def timing(f):
    @wraps(f)
    def wrap(*args, **kw):
        ts = time()
        result = f(*args, **kw)
        te = time()
        print('func:%r args:[%r, %r] took: %2.4f sec' % \
          (f.__name__, args, kw, te-ts))
        return result
    return wrap


@lru_cache(maxsize=65535)
def truncate(self, number, decimals=0):
    """
    Returns a value truncated to a specific number of decimal places.
    Better than rounding
    """
    if not isinstance(decimals, int):
        raise TypeError("decimal places must be an integer.")
    elif decimals < 0:
        raise ValueError("decimal places has to be 0 or more.")
    elif decimals == 0:
        return math.trunc(number)

    factor = 10.0 ** decimals
    result = math.trunc(number * factor) / factor
    return result


@lru_cache(maxsize=65535)
def percent(part, whole):
    return float(whole) / 100 * float(part)


class Coin():
    def __init__(self, client, symbol, date, market_price):
        self.symbol = symbol
        self.volume = 0
        self.bought_at = None
        self.min = market_price
        self.max = market_price
        self.date = date
        self.price = market_price
        self.holding_time = None
        self.value = 0
        self.lot_size = 0
        self.cost = 0


    def update(self, date, market_price):
        self.date = date
        self.price = float(market_price)
        if self.holding_time:
            self.holding_time = self.holding_time +1

        # do we have a new min price?
        if float(market_price) < float(self.min):
            self.min = float(market_price)

        # do we have a new max price?
        if float(market_price) > float(self.max):
            self.max = float(market_price)

        #  if self.volume:
        #      self.profit = float(self.volume) * float(self.price) \
        #          - float(self.volume) * float(self.bought_at)

        if self.volume:
            self.value = float(float(self.volume) * float(self.price))

class Bot():

    def __init__(self, client):
        self.client = client
        self.initial_investment = INITIAL_INVESTMENT
        self.investment = INITIAL_INVESTMENT
        self.holding_time = HOLDING_TIME
        self.excluded_coins = EXCLUDED_COINS
        self.buy_at_percentage = BUY_AT_PERCENTAGE
        self.sell_at_percentage = SELL_AT_PERCENTAGE
        self.stop_loss_at_percentage = STOP_LOSS_AT_PERCENTAGE
        self.pause = PAUSE_FOR
        self.price_log = PRICE_LOG
        self.coins = {}
        self.wins = 0
        self.losses = 0
        self.profit = 0
        self.holding = False
        self.wallet = [] # store the coin we own
        self.tickers = TICKERS
        self.mode = MODE
        self.trading_fee = TRADING_FEE
        self.debug = DEBUG

    def update_investment(self):
        # TODO: we need to do something about fees
        # and finally re-invest our profit, we're aiming to compound
        # so on every sale we invest our profit as well.
        self.investment = self.initial_investment + self.profit

    def update_bot_profit(self, coin):
        # TODO: rename self.profit to bot_profit
        self.profit = float(float(self.profit) + float(coin.profit))


    def buy_coin(self, coin):
        if self.holding:
            return False

        if coin.symbol in self.wallet:
            return False

        volume = float(self.calculate_volume_size(coin))

        if self.mode in ["testnet", "live"]:
            try:
                order_details = self.client.create_order(
                    symbol=coin.symbol,
                    side="BUY",
                    type="MARKET",
                    quantity=volume,
                )

            # error handling here in case position cannot be placed
            except Exception as e:
                print(f"buy() exception: {e}")
                print(f"tried to buy: {volume} of {coin.symbol}")
                return False


            orders = self.client.get_all_orders(symbol=coin.symbol, limit=1)
            while orders == []:
                print(
                    "Binance is being slow in returning the order, " +
                    "calling the API again..."
                )

                orders = self.client.get_all_orders(symbol=coin.symbol, limit=1)
                sleep(1)

            coin.bought_at = self.extract_order_data(order_details, coin)['avgPrice']
            coin.volume = self.extract_order_data(order_details, coin)['volume']
            coin.value = float(coin.bought_at) * float(coin.volume)
            coin.cost = float(coin.bought_at) * float(coin.volume)


        if self.mode in ["analyse"]:
            coin.bought_at = float(coin.price)
            coin.volume = volume
            coin.value = float(coin.bought_at) * float(coin.volume)
            coin.cost = float(coin.bought_at) * float(coin.volume)

        coin.holding_time = 1
        self.holding = True
        self.wallet.append(coin.symbol)

        cprint(f"{coin.date}: bought {float(coin.volume)} of {coin.symbol} total: ${coin.value} with price of {coin.price}", "magenta")


    def sell_coin(self, coin):
        if not self.holding:
            return False

        if coin.symbol not in self.wallet:
            return False


        if self.mode in ["testnet", "live"]:
            try:
                order_details = self.client.create_order(
                    symbol=coin.symbol,
                    side="SELL",
                    type="MARKET",
                    quantity=coin.volume,
                )
            # error handling here in case position cannot be placed
            except Exception as e:
                print(f"sell() exception: {e}")
                print(f"tried to sell: {coin.volume} of {coin.symbol}")
                return False

            orders = self.client.get_all_orders(symbol=coin.symbol, limit=1)
            while orders == []:
                print(
                    "Binance is being slow in returning the order, " +
                    "calling the API again..."
                )

                orders = self.client.get_all_orders(symbol=coin.symbol, limit=1)
                sleep(1)

            coin.price = self.extract_order_data(order_details, coin)['avgPrice']
            coin.date = datetime.now()

        coin.value = float(float(coin.volume) * float(coin.price))
        coin.profit = float(float(coin.value) - float(coin.cost))

        if coin.profit <0:
            ink = "red"
            message = "loss"
        else:
            ink = "green"
            message = "profit"

        cprint(f"{coin.date}: sold {float(coin.volume)} of {coin.symbol} total: ${float(coin.value)} with price of {coin.price} and {message}: {coin.profit}", ink)
        self.holding = False
        self.wallet.remove(coin.symbol)


    def extract_order_data(self, order_details, coin):
        transactionInfo = {}
        # Market orders are not always filled at one price,
        # we need to find the averages of all 'parts' (fills) of this order.
        fills_total = 0
        fills_qty = 0
        fills_fee = 0

        # loop through each 'fill':
        for fills in order_details["fills"]:
            fill_price = float(fills["price"])
            fill_qty = float(fills["qty"])
            fills_fee += float(fills["commission"])

            # quantity of fills * price
            fills_total += fill_price * fill_qty
            # add to running total of fills quantity
            fills_qty += fill_qty
            # increase fills array index by 1

        # calculate average fill price:
        fill_avg = fills_total / fills_qty
        tradeFeeApprox = float(fill_avg) * (float(self.trading_fee) / 100)

        # the volume size is sometimes outside of precision, correct it
        volume = float(self.calculate_volume_size(coin))

        # create object with received data from Binance
        transactionInfo = {
            "symbol": order_details["symbol"],
            "orderId": order_details["orderId"],
            "timestamp": order_details["transactTime"],
            "avgPrice": float(fill_avg),
            "volume": float(volume),
            "tradeFeeBNB": float(fills_fee),
            "tradeFeeUnit": tradeFeeApprox,
        }
        return transactionInfo


    def calculate_volume_size(self, coin):
        try:
            info = self.client.get_symbol_info(coin.symbol)
            step_size = info['filters'][2]['stepSize']
            lot_size = step_size.index('1') - 1

            if lot_size < 0:
                lot_size = 0

            if self.debug:
                print(f"INFO {info}")
                print(f"STEP_SIE {step_size}")
                print(f"LOT_SIE {lot_size}")

        except:
            print(info)
            pass

        # if lot size has 0 decimal points, make the volume an integer
        if lot_size == 0:
            volume = int(float(self.investment / float(coin.price)))
            if self.debug:
                print(f"VOLUME1: {volume}")
        else:
            volume = truncate(
                float(self.investment) / float(coin.price), lot_size)
            if self.debug:
                print(f"VOLUME2: {volume}")

        if self.debug:
            print(f"investment: {self.investment} coin: {coin.symbol} vol: {volume} lot: {lot_size}")
        return volume



    def process_coins(self):
        # look for coins that are ready for buying, or selling
        binance_prices = self.client.get_all_tickers()

        for upstream in binance_prices:

            symbol = upstream['symbol']
            if symbol not in self.tickers:
                continue

            if symbol in self.excluded_coins:
                continue

            market_price = upstream['price']
            if symbol not in self.coins:
                self.coins[symbol] = Coin(
                    client,
                    symbol,
                    datetime.now(),
                    market_price
                )
            else:
                self.coins[symbol].update(datetime.now(), market_price)

            if self.mode in ["live"]:
                with open(self.price_log, "a+") as f:
                    f.write(f"{datetime.now()} {symbol} {self.coins[symbol].price}\n")

            self.buy_or_sell(self.coins[symbol])


    def buy_or_sell(self, coin):
        # TODO: too much repetition here:
        # has the price gone down by x% on a coin we don't own?
        if not self.holding and coin.symbol not in self.wallet:

            if float(coin.price) < percent(self.buy_at_percentage, coin.max):
                # do some gimmicks, and don't buy the coin straight away
                # but only buy it when the price is now higher than the minimum
                # price ever recorded. This way we ensure that we got the dip
                # TODO: incorrect date
                cprint(f"{coin.date}: possible buy: {coin.symbol}: current: {coin.price} min: {coin.min}", "blue")
                if float(coin.price) > float(coin.min):
                    self.buy_coin(coin)
                    return
            return

        # oh we already own this one, lets check prices
        if self.holding and coin.symbol in self.wallet:
            # This coin is too old, sell it
            if coin.holding_time > self.holding_time: # TODO: this is not a real time count
                cprint(f"{coin.date}: forcing sale of old coin: {coin.symbol}: sold: {coin.price} bought: {coin.bought_at}", "red")

                self.sell_coin(coin)
                self.update_bot_profit(coin)
                self.update_investment()

                # and block this coin for today:
                #self.excluded_coins.append(coin.symbol)

                self.losses = self.losses +1
                # clear all stats on coins, like in a new start.
                # we had a stale coin, so its likely the market has shifted
                # and our stats do not reflect the state of the market anymore
                self.coins = {}
                return

            # deal with STOP_LOSS
            if float(coin.price) < percent(
                    self.stop_loss_at_percentage,
                    coin.bought_at
            ):
                # TODO: incorrect date
                cprint(f"{coin.date}: stop loss: {coin.symbol}: selling: {coin.price} bought: {coin.bought_at}", "red")
                self.sell_coin(coin)

                self.update_bot_profit(coin)
                self.update_investment()

                # and block this coin for today:
                #self.excluded_coins.append(coin.symbol)

                self.losses = self.losses +1
                # clear all stats on coins, like in a new start.
                # we had a stop loss, so its likely the market has shifted
                # and our stats do not reflect the state of the market anymore
                self.coins = {}
                return

            # possible sale
            if float(coin.price) > percent(
                    self.sell_at_percentage,
                    coin.bought_at
            ):
                # do some gimmicks, and don't sell the coin straight away
                # but only buy it when the price is now lower than the minimum
                # price ever recorded
                # TODO: incorrect date
                cprint(f"{coin.date}: possible sell: {coin.symbol} current: {coin.price} max: {coin.max}", "blue")
                if float(coin.price) < float(coin.max):
                    self.sell_coin(coin)

                    self.update_bot_profit(coin)
                    self.update_investment()

                    self.wins = self.wins + 1
                    # clear all stats on coins, like in a new start.
                    # this mostly clears up the maximum price, to avoid us falling
                    # into a trap, where the price has gone down(crash) from an
                    # earlier time in the day, followed by a down slow slope
                    # which could trigger the -n% in price from earlier and get
                    # us stuck with a coin that will take a long time to recover
                    # as the market moved on since the max price earlier
                    self.coins = {}
                    return

    def wait(self):
        sleep(self.pause)

    def run(self):
        while True:
            self.process_coins()
            self.wait()
            if exists(".stop"):
                print(".stop flag found. Stopping bot.")
                return


    def analyse(self):
        pattern = '([0-9]{4}-[0-9]{2}-[0-9]{2}\s[0-9]{2}:[0-9]{2}:[0-9]{2}).*\s([0-9|A-Z].*USDT)\s(.*)'

        with open(self.price_log) as f:
            while True:
                line = f.readline()
                if not line:
                    break

                try:
                    date, symbol, market_price  = re.match(pattern,
                                                           line).groups()

                    if symbol in self.excluded_coins:
                        continue

                    if symbol not in self.tickers:
                        continue

                    # TODO: rework this
                    if symbol not in self.coins:
                        self.coins[symbol] = Coin(self.client, symbol, date, market_price)
                    else:
                        self.coins[symbol].update(date, market_price)

                    self.buy_or_sell(self.coins[symbol])
                except:
                    print(traceback.format_exc())
                    pass


if __name__ == '__main__':
    try:
        client = Client(ACCESS_KEY, SECRET_KEY)
        bot = Bot(client)

        if bot.mode == "analyse":
            print("running in analyse mode")
            bot.analyse()

        if bot.mode == "testnet":
            print("running in testnet mode")
            bot.client.API_URL = 'https://testnet.binance.vision/api'
            bot.run()

        if bot.mode == "live":
            print("running in LIVE mode")
            bot.run()

        if bot.holding:
            symbol = bot.wallet[0]
            coin = bot.coins[symbol]
            cprint(f"still holding {coin.symbol}", "red")
            # TODO: improve this, maybe add a coin.cost property?

            cprint(f" cost: {coin.volume * coin.bought_at}", "green")
            cprint(f" value: {coin.volume * coin.price}", "red")

        print(f"total profit: {int(bot.profit)}")
        print(f"initial investment: {int(bot.initial_investment)} final investment: {int(bot.investment)}")
        print(f"buy_at: {bot.buy_at_percentage} sell_at: {bot.sell_at_percentage}")
        print(f"wins: {bot.wins} losses: {bot.losses}")
        print(f"list of excluded coins: {bot.excluded_coins}")

    except:
        print(traceback.format_exc())
        sys.exit(1)
