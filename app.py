from time import sleep
import re
import math
import sys
import traceback
import json
from os.path import exists
from time import time
from datetime import datetime
from termcolor import colored, cprint
from functools import wraps


from binance.client import Client
from binance.exceptions import BinanceAPIException
from binance.helpers import round_step_size
from requests.exceptions import ReadTimeout, ConnectionError

from tenacity import retry, wait_exponential

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
    DEBUG,
    MAX_COINS,
    PAIRING,
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
        self.holding_time = 0
        self.value = 0
        self.lot_size = 0
        self.cost = 0
        self.last = market_price


    def update(self, date, market_price):
        self.date = date
        self.last = self.price
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
        self.stales = 0
        self.profit = 0
        self.wallet = [] # store the coin we own
        self.tickers = TICKERS
        self.mode = MODE
        self.trading_fee = TRADING_FEE
        self.debug = DEBUG
        self.max_coins = MAX_COINS
        self.pairing = PAIRING

    def update_investment(self):
        # TODO: we need to do something about fees
        # and finally re-invest our profit, we're aiming to compound
        # so on every sale we invest our profit as well.
        self.investment = self.initial_investment + self.profit

    def update_bot_profit(self, coin):
        # TODO: rename self.profit to bot_profit
        fees = (1 - (2 * float(self.trading_fee)))
        self.profit = (float(self.profit) + float(coin.profit * fees))


    def buy_coin(self, coin):
        if coin.symbol in self.wallet:
            return False

        if len(self.wallet) == self.max_coins:
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
        self.wallet.append(coin.symbol)

        cprint(f"{coin.date}: [{coin.symbol}] (bought) {coin.volume} now: {coin.price} total: ${coin.value}", "magenta")


    def sell_coin(self, coin):
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

        cprint(f"{coin.date}: [{coin.symbol}] (sold) {coin.volume}  now: {coin.price} total: ${coin.value} and {message}: {coin.profit}", ink)
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
            info = coin.client.get_symbol_info(coin)
            step_size = info['filters'][2]['stepSize']
            precision = int(round(-math.log(step_size, 10), 0))
        except:
            precision = 0

        #decimal_count = len(str(coin.price).split(".")[1])
        volume = float(
            round(
                (self.investment/ self.max_coins) / coin.price, precision
            )
        )

        if self.debug:
            print(f"[{coin.symbol}] investment:{self.investment}  vol:{volume} price:{coin.price} precision:{precision}")
        return volume


    @retry(wait=wait_exponential(multiplier=1, max=90))
    def get_binance_prices(self):
        return self.client.get_all_tickers()

    def write_log(self, symbol):
        price_log = f"log/{datetime.now().strftime('%Y%m%d')}.log"
        with open(price_log, "a+") as f:
            f.write(f"{datetime.now()} {symbol} {self.coins[symbol].price}\n")


    def init_or_update_coin(self, binance_data):
        symbol = binance_data['symbol']

        market_price = binance_data['price']
        if symbol not in self.coins:
            self.coins[symbol] = Coin(
                client,
                symbol,
                datetime.now(),
                market_price
            )
        else:
            self.coins[symbol].update(datetime.now(), market_price)


    def process_coins(self):
        # look for coins that are ready for buying, or selling
        for binance_data in self.get_binance_prices():
            symbol = binance_data['symbol']
            self.init_or_update_coin(binance_data)

            if self.mode in ["live", "logmode"]:
                self.write_log(symbol)

            if self.mode in ["live", "analyse"]:
                if symbol not in self.excluded_coins:
                    if self.pairing in symbol:
                        self.buy_or_sell(self.coins[symbol])


    def clear_coin_stats(self, coin):
        coin.min = coin.price
        coin.max = coin.price


    def buy_or_sell(self, coin):
        # TODO: too much repetition here:
        # has the price gone down by x% on a coin we don't own?

        if coin.symbol in self.excluded_coins:
            return

        if coin.symbol not in self.wallet:
            if len(self.wallet) != self.max_coins:
                if float(coin.price) < percent(self.buy_at_percentage, coin.max):
                    # do some gimmicks, and don't buy the coin straight away
                    # but only buy it when the price is now higher than the minimum
                    # price ever recorded. This way we ensure that we got the dip
                    # TODO: incorrect date
                    print(f"{coin.date}: [{coin.symbol}] (buying) {self.investment} now: {coin.price} min: {coin.min}")
                    if float(coin.price) > float(coin.min):
                        self.buy_coin(coin)
                        self.clear_coin_stats(coin)
                        return
            return

        if coin.symbol not in self.wallet:
            return
        # oh we already own this one, lets check prices

        # This coin is too old, sell it
        if coin.holding_time > self.holding_time: # TODO: this is not a real time count
            cprint(f"{coin.date}: [{coin.symbol}] (sale of old coin) : now: {coin.price} bought: {coin.bought_at}", "red")

            self.sell_coin(coin)
            self.update_bot_profit(coin)
            self.update_investment()

            # and block this coin for today:
            #self.excluded_coins.append(coin.symbol)

            self.stales = self.stales +1
            self.clear_coin_stats(coin)
            return

            # deal with STOP_LOSS
        if float(coin.price) < percent(
                self.stop_loss_at_percentage,
                coin.bought_at
        ):
            # TODO: incorrect date
            cprint(f"{coin.date}: [{coin.symbol}] (stop loss) now: {coin.price} bought: {coin.bought_at}", "red")
            self.sell_coin(coin)

            self.update_bot_profit(coin)
            self.update_investment()

            # and block this coin for today:
            #self.excluded_coins.append(coin.symbol)

            self.losses = self.losses +1
            self.clear_coin_stats(coin)
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
            # TODO: we need a state, where a coin has gone over the profit the profit margin
            # and crashed, taking it below the profit boundary, but stopping the TSL to kick in
            # as the coin is too low to be sold, and it will be sold likely by GC or SL

            if float(coin.price) != float(coin.last):
                print(f"{coin.date}: [{coin.symbol}] (selling) now: {coin.price} max: {coin.max}")
            if float(coin.price) < float(coin.max):
                self.sell_coin(coin)

                self.update_bot_profit(coin)
                self.update_investment()

                self.wins = self.wins + 1
                self.clear_coin_stats(coin)
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

    def logmode(self):
        while True:
            self.process_coins()
            self.wait()

    def analyse(self):
        pattern = '([0-9]{4}-[0-9]{2}-[0-9]{2}\s[0-9]{2}:[0-9]{2}:[0-9]{2}).*\s([0-9|A-Z].*' + \
            f'{self.pairing}' + ')\s(.*)'

        with open(self.price_log) as f:
            while True:
                try:
                    line = f.readline()
                    if line == '':
                        return

                    match_found = re.match(pattern, line)
                    if not match_found:
                        continue

                    date, symbol, market_price  = match_found.groups()

                    if symbol not in self.tickers:
                        continue

                    # TODO: rework this
                    if symbol not in self.coins:
                        self.coins[symbol] = Coin(self.client, symbol, date, market_price)
                    else:
                        self.coins[symbol].update(date, market_price)

                    self.buy_or_sell(self.coins[symbol])
                except Exception as e:
                    print(line)
                    print(traceback.format_exc())
                    if e == "KeyboardInterrupt":
                        sys.exit(1)
                    pass



if __name__ == '__main__':
    try:
        client = Client(ACCESS_KEY, SECRET_KEY)
        bot = Bot(client)

        if bot.mode == "analyse":
            print("running in analyse mode")
            bot.analyse()

        if bot.mode == "logmode":
            print("running in log mode")
            bot.logmode()

        if bot.mode == "testnet":
            print("running in testnet mode")
            bot.client.API_URL = 'https://testnet.binance.vision/api'
            bot.run()

        if bot.mode == "live":
            print("running in LIVE mode")
            bot.run()

        for symbol in bot.wallet:
            cprint(f"still holding {symbol}", "red")
            coin = bot.coins[symbol]
            cprint(f" cost: {coin.volume * coin.bought_at}", "green")
            cprint(f" value: {coin.volume * coin.price}", "red")

        print(f"total profit: {int(bot.profit)}")
        print(f"initial investment: {int(bot.initial_investment)} final investment: {int(bot.investment)}")
        print(f"buy_at: {bot.buy_at_percentage} sell_at: {bot.sell_at_percentage}")
        print(f"wins: {bot.wins} losses: {bot.losses} stales: {bot.stales}")
        print(f"list of excluded coins: {bot.excluded_coins}")

    except:
        print(traceback.format_exc())
        sys.exit(1)
