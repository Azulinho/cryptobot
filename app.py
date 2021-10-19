from time import sleep
import re
import math
import sys
import traceback
import pickle
import json
import gzip
from os.path import exists
from time import time
from datetime import datetime
from termcolor import colored, cprint
from functools import wraps, lru_cache


from binance.client import Client
from binance.exceptions import BinanceAPIException
from binance.helpers import round_step_size
from requests.exceptions import ReadTimeout, ConnectionError

from tenacity import retry, wait_exponential

from config import (
    INITIAL_INVESTMENT,
    SOFT_LIMIT_HOLDING_TIME,
    HARD_LIMIT_HOLDING_TIME,
    BUY_AT_PERCENTAGE,
    SELL_AT_PERCENTAGE,
    STOP_LOSS_AT_PERCENTAGE,
    EXCLUDED_COINS,
    PAUSE_FOR,
    PRICE_LOGS,
    ACCESS_KEY,
    SECRET_KEY,
    TICKERS_FILE,
    MODE,
    TRADING_FEE,
    DEBUG,
    MAX_COINS,
    PAIRING,
    CLEAR_COIN_STATS_AT_BOOT,
    CLEAR_COIN_STATS_AT_SALE,
    TRAIL_TARGET_SELL_PERCENTAGE,
    TRAIL_RECOVERY_PERCENTAGE,
    NAUGHTY_TIMEOUT,
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
    def __init__(
            self,
            client,
            symbol,
            date,
            market_price,
            buy_at,
            sell_at,
            stop_loss,
            trail_target_sell_percentage,
            trail_recovery_percentage,
    ):
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
        self.buy_at_percentage = buy_at
        self.sell_at_percentage = sell_at
        self.stop_loss_at_percentage = stop_loss
        self.status = None
        self.trail_recovery_percentage = trail_recovery_percentage
        self.trail_target_sell_percentage = trail_target_sell_percentage
        self.dip = market_price,
        self.tip = market_price
        self.naughty_timeout = 0


    def update(self, date, market_price):
        self.date = date
        self.last = self.price
        self.price = float(market_price)

        if self.holding_time:
            self.holding_time = self.holding_time +1

        if self.naughty_timeout != 0:
            self.naughty_timeout = self.naughty_timeout -1

        # do we have a new min price?
        if float(market_price) < float(self.min):
            self.min = float(market_price)

        # do we have a new max price?
        if float(market_price) > float(self.max):
            self.max = float(market_price)


        if self.volume:
            self.value = float(float(self.volume) * float(self.price))

class Bot():

    def __init__(self, client):
        self.client = client
        self.initial_investment = INITIAL_INVESTMENT
        self.investment = INITIAL_INVESTMENT
        self.soft_limit_holding_time = SOFT_LIMIT_HOLDING_TIME
        self.hard_limit_holding_time = HARD_LIMIT_HOLDING_TIME
        self.excluded_coins = EXCLUDED_COINS
        self.buy_at_percentage = float(100 + float(BUY_AT_PERCENTAGE))
        self.sell_at_percentage = float(100 + float(SELL_AT_PERCENTAGE))
        self.stop_loss_at_percentage = float(100 +float(STOP_LOSS_AT_PERCENTAGE))
        self.pause = PAUSE_FOR
        self.price_logs = PRICE_LOGS
        self.coins = {}
        self.wins = 0
        self.losses = 0
        self.stales = 0
        self.profit = 0
        self.wallet = [] # store the coin we own
        self.tickers_file = TICKERS_FILE
        self.tickers = [line.strip() for line in open(TICKERS_FILE)]
        self.mode = MODE
        self.trading_fee = float(TRADING_FEE)
        self.debug = DEBUG
        self.max_coins = MAX_COINS
        self.pairing = PAIRING
        self.fees = 0
        self.clear_coin_stats_at_boot = CLEAR_COIN_STATS_AT_BOOT
        self.trail_target_sell_percentage = float(100) + float(TRAIL_TARGET_SELL_PERCENTAGE)
        self.trail_recovery_percentage = float(100) + float(TRAIL_RECOVERY_PERCENTAGE)
        self.naughty_timeout = NAUGHTY_TIMEOUT
        self.clean_coin_stats_at_sale = CLEAR_COIN_STATS_AT_SALE

    def update_investment(self):
        # and finally re-invest our profit, we're aiming to compound
        # so on every sale we invest our profit as well.
        self.investment = self.initial_investment + self.profit

    def update_bot_profit(self, coin):
        bought_fees = percent(self.trading_fee, coin.cost)
        sell_fees = percent(self.trading_fee, coin.value)
        fees = float( bought_fees + sell_fees)

        self.profit = float(self.profit) + float(coin.profit )- float(fees)
        self.fees = self.fees + fees


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


        if self.mode in ["backtesting"]:
            coin.bought_at = float(coin.price)
            coin.volume = volume
            coin.value = float(coin.bought_at) * float(coin.volume)
            coin.cost = float(coin.bought_at) * float(coin.volume)

        coin.holding_time = 1
        self.wallet.append(coin.symbol)
        coin.status = "HOLD"
        coin.tip = coin.price

        cprint(
            f"{coin.date}: [{coin.symbol}] (bought) " +
            f"U:{coin.volume} P:{coin.price} T:${coin.value:.3f} " +
            f"sell_at:${coin.price * coin.sell_at_percentage /100} "+
            f"({len(self.wallet)}/{self.max_coins})", "magenta")


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

        coin.status = None
        self.wallet.remove(coin.symbol)
        cprint(
            f"{coin.date}: [{coin.symbol}] (sold) U:{coin.volume} "+
            f"P:{coin.price} T:${coin.value:.3f} and "+
            f"{message}:{coin.profit:.3f} "+
            f"sell_at:{coin.sell_at_percentage:.3f} "+
            f"trail_sell:{coin.trail_target_sell_percentage:.3f}" +
            f" ({len(self.wallet)}/{self.max_coins})", ink
        )


    def extract_order_data(self, order_details, coin):
        # TODO: review this whole mess
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

    @lru_cache()
    @retry(wait=wait_exponential(multiplier=1, max=10))
    def get_symbol_precision(self, symbol):
        try:
            info = self.client.get_symbol_info(symbol)
        except Exception as e:
            print(e)
            return -1

        step_size = float(info['filters'][2]['stepSize'])
        precision = int(round(-math.log(step_size, 10), 0))

        return precision



    def calculate_volume_size(self, coin):
        precision = self.get_symbol_precision(coin.symbol)

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
                market_price,
                buy_at = self.buy_at_percentage,
                sell_at = self.sell_at_percentage,
                stop_loss = self.stop_loss_at_percentage,
                trail_target_sell_percentage = self.trail_target_sell_percentage,
                trail_recovery_percentage = self.trail_recovery_percentage
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

            if self.mode in ["live", "backtesting", 'testnet']:
                if not any(sub in symbol for sub in self.excluded_coins):
                    if self.pairing in symbol:
                        self.buy_drop_sell_recovery_strategy(self.coins[symbol])


    def clear_all_coins_stats(self):
        if self.clean_coin_stats_at_sale:
            for coin in self.coins:
                self.clear_coin_stats(self.coins[coin])

    def clear_coin_stats(self, coin):
        coin.min = coin.price
        coin.max = coin.price
        coin.buy_at_percentage = self.buy_at_percentage
        coin.sell_at_percentage = self.sell_at_percentage
        coin.stop_loss_at_percentage = self.stop_loss_at_percentage

    def save_coins(self):
        with open(".coins.pickle", "wb") as f:
            pickle.dump(self.coins, f)
        with open(".wallet.pickle", "wb") as f:
            pickle.dump(self.wallet, f)


    def load_coins(self):
        if exists(".coins.pickle"):
            print("found .coins.pickle, loading coins")
            with open(".coins.pickle", "rb") as f:
                self.coins = pickle.load(f)
        if exists(".wallet.pickle"):
            print("found .wallet.pickle, loading wallet")
            with open(".wallet.pickle", "rb") as f:
                self.wallet = pickle.load(f)
            print(f"wallet contains {self.wallet}")

        # sync our coins state with the list of coins we want to use.
        # but keep using coins we currently have on our wallet
        coins_to_remove = []
        for coin in self.coins:
            if coin not in self.tickers and coin not in self.wallet:
                coins_to_remove.append(coin)

        for coin in coins_to_remove:
            self.coins.pop(coin)

        # finally apply the current settings in the config file
        for symbol in self.coins:
            self.coins[symbol].buy_at_percentage = self.buy_at_percentage
            self.coins[symbol].sell_at_percentage = self.sell_at_percentage
            self.coins[symbol].stop_loss_at_percentage = self.stop_loss_at_percentage

    def buy_drop_sell_recovery_strategy(self, coin):
        # TODO: too much repetition here:
        # split these actions into their own functions

        if any(sub in coin.symbol for sub in self.excluded_coins):
            return

        if coin.symbol not in self.tickers and coin not in self.wallet:
            return

        if coin.naughty_timeout != 0:
            return

        # has the price gone down by x% on a coin we don't own?
        if coin.symbol not in self.wallet:
            if len(self.wallet) != self.max_coins:
                if float(coin.price) < percent(coin.buy_at_percentage, coin.max):
                    if coin.status == None:
                        coin.dip = coin.price
                        coin.status = "TARGET_DIP"

                    if coin.status == "TARGET_DIP":
                        if float(coin.price) < float(coin.dip):
                            coin.dip = coin.price
                    # do some gimmicks, and don't buy the coin straight away
                    # but only buy it when the price is now higher than the last
                    # price recorded. This way we ensure that we got the dip
                    # TODO: incorrect date
                    if self.debug:
                        print(f"{coin.date}: [{coin.symbol}] (buying) {self.investment} now: {coin.price} min: {coin.min} max: {coin.max}")
                    if float(coin.price) > float(coin.last):
                        if float(coin.price) > percent(float(coin.trail_recovery_percentage), coin.dip):
                            self.buy_coin(coin)
                            self.clear_all_coins_stats()
                            return
            return

        # return early if no work left to do
        if coin.symbol not in self.wallet:
            return
        # oh we already own this one, lets check prices

        # deal with STOP_LOSS
        if float(coin.price) < percent(
                coin.stop_loss_at_percentage,
                coin.bought_at
        ):
            coin.status = "STOP_LOSS"
            cprint(f"{coin.date}: [{coin.symbol}] (stop loss) now: {coin.price} bought: {coin.bought_at}", "red")
            self.sell_coin(coin)

            self.update_bot_profit(coin)
            self.update_investment()


            self.losses = self.losses +1
            self.clear_all_coins_stats()
            # and block this coin for a while
            coin.naughty_timeout = int(self.naughty_timeout)
            return

        # coin was above sell_at_percentage and dropped below
        # lets' sell it ASAP
        if coin.status == "TARGET_SELL" and float(coin.price) < percent(
                self.sell_at_percentage,
                coin.bought_at
        ):
            self.sell_coin(coin)

            self.update_bot_profit(coin)
            self.update_investment()

            self.wins = self.wins + 1
            self.clear_all_coins_stats()
            return

        # possible sale
        if float(coin.price) > percent(
                self.sell_at_percentage,
                coin.bought_at
        ):
            coin.status = "TARGET_SELL"
            # do some gimmicks, and don't sell the coin straight away
            # but only sell it when the price is now higher than the last
            # price recorded
            # TODO: incorrect date

            if float(coin.price) != float(coin.last):
                if self.debug:
                    print(f"{coin.date}: [{coin.symbol}] (selling) now: {coin.price} max: {coin.max}")
            if float(coin.price) > float(coin.tip):
                coin.tip = coin.price

            if float(coin.price) < float(coin.last):
                coin.status = "TARGET_SELL"

                if float(coin.price) < percent(float(coin.trail_target_sell_percentage), coin.tip):
                    self.sell_coin(coin)

                    self.update_bot_profit(coin)
                    self.update_investment()

                    self.wins = self.wins + 1
                    self.clear_all_coins_stats()
                    return

        # This coin is too old, sell it
        if (coin.holding_time > self.hard_limit_holding_time) and (
            coin.status != "TARGET_SELL"
        ):
            coin.status = "STALE"
            cprint(
                f"{coin.date}: [{coin.symbol}] (stale) : now: " +
                f"{coin.price} bought: {coin.bought_at}", "red"
            )

            self.sell_coin(coin)
            self.update_bot_profit(coin)
            self.update_investment()

            # and block this coin for today:
            #self.excluded_coins.append(coin.symbol)

            self.stales = self.stales +1
            self.clear_all_coins_stats()

            # and block this coin for today:
            coin.naughty_timeout = int(self.naughty_timeout)
            return


        # This coin is past our soft limit
        # we apply a sliding window to the buy profit
        if coin.holding_time > self.soft_limit_holding_time and coin.status != "TARGET_SELL": # TODO: this is not a real time count
            coin.status = "STALE"
            profit_boundary = (self.sell_at_percentage - 100) - (2 * self.trading_fee)
            percentage_slice_per_holding_time_slice =  profit_boundary / self.hard_limit_holding_time

            trail_target_slice_per_holding_time_slice = (
                (100 - coin.trail_target_sell_percentage) / self.hard_limit_holding_time
            )

            coin_life_left = self.hard_limit_holding_time - coin.holding_time
            new_sell_at_percentage = 100 + (coin_life_left * percentage_slice_per_holding_time_slice)
            new_trail_target_sell_percentage = 100 - (coin_life_left * trail_target_slice_per_holding_time_slice)

            coin.sell_at_percentage = new_sell_at_percentage
            coin.trail_target_sell_percentage = new_trail_target_sell_percentage

            if self.debug:
                print(f"holding: {coin.holding_time} {coin.sell_at_percentage:.4f} {coin.trail_target_sell_percentage:.4f}")

            return


    def wait(self):
        sleep(self.pause)

    def run(self):
        self.load_coins()
        if self.clear_coin_stats_at_boot:
            self.clear_all_coins_stats()
        while True:
            self.process_coins()
            self.save_coins()
            self.wait()
            if exists(".stop"):
                print(".stop flag found. Stopping bot.")
                return

    def logmode(self):
        while True:
            self.process_coins()
            self.wait()

    def backtest_logfile(self, price_log):
        # reset our exclude coins every day.
        # this mimics us stopping/starting the bot once a day
        self.excluded_coins = EXCLUDED_COINS
        # clear up profit, fees, and reset investment
        # this will gives us our strategy results per day
        # instead of compounded results
        self.profit = 0
        self.fees = 0
        self.investment = self.initial_investment
        self.wins = 0
        self.losses = 0
        self.stales = 0
        _coins = {}
        for symbol in self.wallet:
            _coins[symbol] = self.coins[symbol]
        self.coins = _coins

        read_counter = 0
        with gzip.open(price_log,'rt') as f:
            while True:
                try:
                    line = f.readline()
                    if line == '':
                        break

                    if self.pairing not in line:
                        continue

                    parts = line.split(' ')
                    date = ' '.join(parts[0:2])
                    symbol = parts[2]
                    market_price = parts[3]

                    if symbol not in self.tickers:
                        continue

                    # implements a PAUSE_FOR pause while reading from
                    # our price logs.
                    # we essentially skip a number of iterations between
                    # reads, causing a similar effect if we were only
                    # probing prices every PAUSE_FOR seconds
                    if read_counter == PAUSE_FOR:
                        read_counter = 0
                    else:
                        read_counter = read_counter +1
                        continue
                    # TODO: rework this
                    if symbol not in self.coins:
                        self.coins[symbol] = Coin(
                            self.client,
                            symbol,
                            date,
                            market_price,
                            self.buy_at_percentage,
                            self.sell_at_percentage,
                            self.stop_loss_at_percentage,
                            self.trail_target_sell_percentage,
                            self.trail_recovery_percentage
                        )
                    else:
                        self.coins[symbol].update(date, market_price)

                    self.buy_drop_sell_recovery_strategy(self.coins[symbol])
                except Exception as e:
                    print(traceback.format_exc())
                    if e == "KeyboardInterrupt":
                        sys.exit(1)
                    pass


    def backtesting(self):
        results = []
        last_profit = 0
        last_fees = 0
        last_investment = 0
        last_wins = 0
        last_losses = 0
        last_stales = 0

        for price_log in self.price_logs:
            self.backtest_logfile(price_log)

            # gather results from this day run
            this_run = " ".join([
                f"{price_log}",
                f"profit:{self.profit}",
                f"fees:{self.fees}",
                f"[w{self.wins},l{self.losses},s{self.stales}]"
            ])

            results.append(this_run)

            # and add up the moneys, wins,losses and others
            last_profit = last_profit + self.profit
            last_fees = last_fees + self.fees
            last_wins = last_wins + self.wins
            last_losses = last_losses + self.losses
            last_stales = last_stales + self.stales
            last_investment = last_investment + self.profit


        for result in results:
            cprint(result,  attrs=['bold'])

        self.profit = last_profit
        self.fees = last_fees
        self.wins = last_wins
        self.losses = last_losses
        self.stales = last_stales
        self.investment = self.initial_investment + last_investment

        with open("backtesting.log", "a") as f:
            log_entry = '|'.join([
                f"profit:{self.profit:.2f}",
                f"investment:{self.initial_investment}",
                f"n_tickers:{len(self.tickers)}",
                f"tickers_file:{self.tickers_file}",
                f"w{self.wins},l{self.losses},s{self.stales},h{len(self.wallet)}",
                f"max_coins:{self.max_coins}",
                f"days:{len(self.price_logs)}",
                f"buy_at:{self.buy_at_percentage}",
                f"sell_at:{self.sell_at_percentage}",
                f"stop_loss_at:{self.stop_loss_at_percentage}",
                f"trail_target_sell_percentage:{self.trail_target_sell_percentage}",
                f"trail_recovery_percentage:{self.trail_recovery_percentage}",
                f"soft_limit_holding_time:{self.soft_limit_holding_time}",
                f"hard_limit_holding_time:{self.hard_limit_holding_time}",
                f"naughty_timeout:{self.naughty_timeout}",
                f"clear_coin_stats_at_sale:{self.clean_coin_stats_at_sale}",
                f"trading_fee:{self.trading_fee}",
                f"pause:{self.pause}",
                f"pairing:{self.pairing}",
                f"holding:{self.wallet}",
                f"results:{results}",
            ])

            f.write(f"{log_entry}\n")


if __name__ == '__main__':
    try:
        client = Client(ACCESS_KEY, SECRET_KEY)
        bot = Bot(client)

        startup_msg = (
           f"buy_at:{BUY_AT_PERCENTAGE} " +
           f"sell_at:{SELL_AT_PERCENTAGE} " +
           f"stop_loss:{STOP_LOSS_AT_PERCENTAGE} " +
           f"max_coins:{MAX_COINS} " +
           f"soft_limit_holding_time:{SOFT_LIMIT_HOLDING_TIME} " +
           f"hard_limit_holding_time:{HARD_LIMIT_HOLDING_TIME} "
        )
        print(f"running in {bot.mode} mode with {startup_msg}")

        if bot.mode == "backtesting":
            bot.backtesting()

        if bot.mode == "logmode":
            bot.logmode()

        if bot.mode == "testnet":
            bot.client.API_URL = 'https://testnet.binance.vision/api'
            bot.run()

        if bot.mode == "live":
            bot.run()

        for symbol in bot.wallet:
            cprint(f"still holding {symbol}", "red")
            coin = bot.coins[symbol]
            cprint(f" cost: {coin.volume * coin.bought_at}", "green")
            cprint(f" value: {coin.volume * coin.price}", "red")

        print(f"total profit: {int(bot.profit)}")
        print(f"total fees: {int(bot.fees)}")
        print(f"initial investment: {int(bot.initial_investment)} final investment: {int(bot.investment)}")
        print(f"buy_at: {bot.buy_at_percentage} sell_at: {bot.sell_at_percentage} stop_loss: {bot.stop_loss_at_percentage}")
        print(f"wins:{bot.wins} losses:{bot.losses} stales:{bot.stales}")
        print(f"list of excluded coins: {bot.excluded_coins}")

    except:
        print(traceback.format_exc())
        sys.exit(1)
