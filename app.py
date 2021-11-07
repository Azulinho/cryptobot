import lz4.frame
import json
import math
import pickle
import re
import sys
import traceback
from datetime import datetime
from functools import wraps, lru_cache
from os.path import exists
from time import time, sleep
from typing import List, Set, Dict, Any, Tuple
from binance.client import Client
from binance.exceptions import BinanceAPIException
from binance.helpers import round_step_size
from neotermcolor import colored, cprint
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
    STRATEGY,
)


def timing(f):
    @wraps(f)
    def wrap(*args, **kw):
        ts = time()
        result = f(*args, **kw)
        te = time()
        print("func:%r args:[%r, %r] took: %2.4f sec" % (f.__name__, args, kw, te - ts))
        return result

    return wrap


def percent(part: float, whole: float) -> float:
    result = float(whole) / 100 * float(part)
    return result


class Coin:
    def __init__(
        self,
        client,
        symbol: str,
        date: str,
        market_price: float,
        buy_at: float,
        sell_at: float,
        stop_loss: float,
        trail_target_sell_percentage: float,
        trail_recovery_percentage: float,
    ) -> None:
        self.symbol = symbol
        self.volume: float = 0
        self.bought_at: float = 0
        self.min = market_price
        self.max = market_price
        self.date = date
        self.price = market_price
        self.holding_time = int(0)
        self.value = float(0)
        self.lot_size = float(0)
        self.cost = float(0)
        self.last = market_price
        self.buy_at_percentage = buy_at
        self.sell_at_percentage = sell_at
        self.stop_loss_at_percentage = stop_loss
        self.status = ''
        self.trail_recovery_percentage = trail_recovery_percentage
        self.trail_target_sell_percentage = trail_target_sell_percentage
        self.dip = market_price
        self.tip = market_price
        self.naughty_timeout = int(0)
        self.profit = float(0)

    def update(self, date: str, market_price: float) -> None:
        self.date = date
        self.last = self.price
        self.price = float(market_price)

        # don't age our coin, unless we're waiting to sell it.
        if self.status in ["TARGET_SELL", "HOLD"]:
            self.holding_time = self.holding_time + 1

        if self.naughty_timeout != 0:
            self.naughty_timeout = self.naughty_timeout - 1

        # do we have a new min price?
        if float(market_price) < float(self.min):
            self.min = float(market_price)

        # do we have a new max price?
        if float(market_price) > float(self.max):
            self.max = float(market_price)

        if self.volume:
            self.value = float(float(self.volume) * float(self.price))

        if self.status == "HOLD":
            if float(market_price) > percent(
                self.sell_at_percentage, self.bought_at
            ):
                self.status = "TARGET_SELL"

        if self.status == "TARGET_SELL":
            if float(market_price) > float(self.tip):
                self.tip = market_price

        if self.status == "TARGET_DIP":
            if float(market_price) < float(self.dip):
                self.dip = market_price


class Bot:
    def __init__(self, client) -> None:
        self.client = client
        self.initial_investment = float(INITIAL_INVESTMENT)
        self.investment = float(INITIAL_INVESTMENT)
        self.soft_limit_holding_time = int(SOFT_LIMIT_HOLDING_TIME)
        self.hard_limit_holding_time = int(HARD_LIMIT_HOLDING_TIME)
        self.excluded_coins = EXCLUDED_COINS
        self.buy_at_percentage = float(100 + float(BUY_AT_PERCENTAGE))
        self.sell_at_percentage = float(100 + float(SELL_AT_PERCENTAGE))
        self.stop_loss_at_percentage = float(100 + float(STOP_LOSS_AT_PERCENTAGE))
        self.pause = float(PAUSE_FOR)
        self.price_logs = PRICE_LOGS
        self.coins: Dict[str, Coin] = {}
        self.wins: int = 0
        self.losses: int = 0
        self.stales: int = 0
        self.profit: float = 0
        self.wallet: List = []  # store the coin we own
        self.tickers_file: str = TICKERS_FILE
        self.tickers: List  = [line.strip() for line in open(TICKERS_FILE)]
        self.mode: str = MODE
        self.trading_fee: float = TRADING_FEE
        self.debug: bool = DEBUG
        self.max_coins: int = MAX_COINS
        self.pairing: str = PAIRING
        self.fees: float = 0
        self.clear_coin_stats_at_boot: bool = CLEAR_COIN_STATS_AT_BOOT
        self.trail_target_sell_percentage: float = float(100) + float(
            TRAIL_TARGET_SELL_PERCENTAGE
        )
        self.trail_recovery_percentage: float = float(100) + float(TRAIL_RECOVERY_PERCENTAGE)
        self.naughty_timeout: int = NAUGHTY_TIMEOUT
        self.clean_coin_stats_at_sale: bool = CLEAR_COIN_STATS_AT_SALE
        self.strategy: str = STRATEGY

    def run_strategy(self, *args, **kwargs) -> None:
        if len(self.wallet) != self.max_coins:
            if self.strategy == "buy_drop_sell_recovery_strategy":
                self.buy_drop_sell_recovery_strategy(*args, **kwargs)
            if self.strategy == "buy_moon_sell_recovery_strategy":
                self.buy_moon_sell_recovery_strategy(*args, **kwargs)
        if len(self.wallet) != 0:
            self.check_for_sale_conditions(*args, **kwargs)

    def update_investment(self) -> None:
        # and finally re-invest our profit, we're aiming to compound
        # so on every sale we invest our profit as well.
        self.investment = self.initial_investment + self.profit

    def update_bot_profit(self, coin) -> None:
        bought_fees = percent(self.trading_fee, coin.cost)
        sell_fees = percent(self.trading_fee, coin.value)
        fees = float(bought_fees + sell_fees)

        self.profit = float(self.profit) + float(coin.profit) - float(fees)
        self.fees = self.fees + fees

    def buy_coin(self, coin) -> None:
        if coin.symbol in self.wallet:
            return

        if len(self.wallet) == self.max_coins:
            return

        if coin.naughty_timeout > 0:
            return

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
                return

            orders = self.client.get_all_orders(symbol=coin.symbol, limit=1)
            while orders == []:
                print(
                    "Binance is being slow in returning the order, "
                    + "calling the API again..."
                )

                orders = self.client.get_all_orders(symbol=coin.symbol, limit=1)
                sleep(1)

            coin.bought_at = self.extract_order_data(order_details, coin)["avgPrice"]
            coin.volume = self.extract_order_data(order_details, coin)["volume"]
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
            f"{coin.date}: [{coin.symbol}] {coin.status} "
            + f"U:{coin.volume} P:{coin.price} T:{coin.value:.3f} "
            + f"sell_at:{coin.price * coin.sell_at_percentage /100} "
            + f"({len(self.wallet)}/{self.max_coins})",
            "magenta",
        )


    def sell_coin(self, coin) -> None:
        if coin.symbol not in self.wallet:
            return

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
                return

            orders = self.client.get_all_orders(symbol=coin.symbol, limit=1)
            while orders == []:
                print(
                    "Binance is being slow in returning the order, "
                    + "calling the API again..."
                )

                orders = self.client.get_all_orders(symbol=coin.symbol, limit=1)
                sleep(1)

            coin.price = self.extract_order_data(order_details, coin)["avgPrice"]
            coin.date = datetime.now()

        coin.value = float(float(coin.volume) * float(coin.price))
        coin.profit = float(float(coin.value) - float(coin.cost))

        if coin.profit < 0:
            ink = "red"
            message = "loss"
        else:
            ink = "green"
            message = "profit"

        cprint(
            f"{coin.date}: [{coin.symbol}] {coin.status} U:{coin.volume} "
            + f"P:{coin.price} T:{coin.value:.3f} and "
            + f"{message}:{coin.profit:.3f} "
            + f"sell_at:{coin.sell_at_percentage:.3f} "
            + f"trail_sell:{coin.trail_target_sell_percentage:.3f}"
            + f" ({len(self.wallet)}/{self.max_coins})",
            ink,
        )
        coin.status = ""
        self.wallet.remove(coin.symbol)
        self.update_bot_profit(coin)
        self.update_investment()
        self.clear_coin_stats(coin)
        self.clear_all_coins_stats()

    def extract_order_data(self, order_details, coin) -> Dict[str, Any]:
        # TODO: review this whole mess
        transactionInfo = {}
        # Market orders are not always filled at one price,
        # we need to find the averages of all 'parts' (fills) of this order.
        fills_total: float = 0
        fills_qty: float = 0
        fills_fee: float = 0

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
    def get_symbol_precision(self, symbol: str) -> int:
        try:
            info = self.client.get_symbol_info(symbol)
        except Exception as e:
            print(e)
            return -1

        step_size = float(info["filters"][2]["stepSize"])
        precision = int(round(-math.log(step_size, 10), 0))

        return precision

    def calculate_volume_size(self, coin) -> float:
        precision = self.get_symbol_precision(coin.symbol)

        volume = float(
            round((self.investment / self.max_coins) / coin.price, precision)
        )

        if self.debug:
            print(
                f"[{coin.symbol}] investment:{self.investment}  vol:{volume} price:{coin.price} precision:{precision}"
            )
        return volume

    @retry(wait=wait_exponential(multiplier=1, max=90))
    def get_binance_prices(self) -> List[Dict[str, str]]:
        return self.client.get_all_tickers()

    def write_log(self, symbol: str) -> None:
        price_log = f"log/{datetime.now().strftime('%Y%m%d')}.log"
        with open(price_log, "a") as f:
            f.write(f"{datetime.now()} {symbol} {self.coins[symbol].price}\n")

    def init_or_update_coin(self, binance_data: Dict[str, Any]) -> None:
        symbol = binance_data["symbol"]

        market_price = binance_data["price"]
        if symbol not in self.coins:
            self.coins[symbol] = Coin(
                self.client,
                symbol,
                str(datetime.now()),
                market_price,
                buy_at=self.buy_at_percentage,
                sell_at=self.sell_at_percentage,
                stop_loss=self.stop_loss_at_percentage,
                trail_target_sell_percentage=self.trail_target_sell_percentage,
                trail_recovery_percentage=self.trail_recovery_percentage,
            )
        else:
            self.coins[symbol].update(str(datetime.now()), market_price)


    def process_coins(self) -> None:
        # look for coins that are ready for buying, or selling
        for binance_data in self.get_binance_prices():
            coin_symbol = binance_data["symbol"]
            self.init_or_update_coin(binance_data)

            if self.mode in ["live", "logmode"]:
                self.write_log(coin_symbol)

            if self.mode not in ["live", "backtesting", "testnet"]:
                continue

            if self.pairing in coin_symbol:
                if self.coins[coin_symbol].naughty_timeout < 1:
                    if not any(sub in coin_symbol for sub in self.excluded_coins):
                        if coin_symbol in self.tickers or coin_symbol in self.wallet:
                            self.run_strategy(self.coins[coin_symbol])
                        if coin_symbol in self.wallet:
                            self.log_debug_coin(self.coins[coin_symbol])

    def stop_loss(self, coin: Coin) -> bool:
        # oh we already own this one, lets check prices
        # deal with STOP_LOSS
        if float(coin.price) < percent(coin.stop_loss_at_percentage, coin.bought_at):
            coin.status = "STOP_LOSS"
            cprint(
                f"{coin.date} [{coin.symbol}] {coin.status} now: {coin.price} bought: {coin.bought_at}",
                "red",
            )
            self.sell_coin(coin)
            self.losses = self.losses + 1
            # and block this coin for a while
            coin.naughty_timeout = int(self.naughty_timeout)
            return True
        return False

    def coin_gone_up_and_dropped(self, coin) -> bool:
        if coin.status == "TARGET_SELL" and float(coin.price) < percent(
            self.sell_at_percentage, coin.bought_at
        ):
            coin.status = "DROP_IN_TARGET_SELL"
            self.sell_coin(coin)
            self.wins = self.wins + 1
            return True
        return False

    def possible_sale(self, coin: Coin) -> bool:
        if coin.status == "TARGET_SELL":
            # do some gimmicks, and don't sell the coin straight away
            # but only sell it when the price is now higher than the last
            # price recorded
            # TODO: incorrect date

            if float(coin.price) != float(coin.last):
                self.log_debug_coin(coin)
            # has price has gone down ?
            if float(coin.price) < float(coin.last):

                # and below our target sell percentage over the tip ?
                if float(coin.price) < percent(
                    float(coin.trail_target_sell_percentage), coin.tip
                ):
                    # let's sell it then
                    self.sell_coin(coin)
                    self.wins = self.wins + 1
                    return True
        return False

    # This is not being called anywhhere that matters
    def past_hard_limit(self, coin: Coin) -> bool:
        if coin.holding_time > self.hard_limit_holding_time:
            coin.status = "STALE"
            self.sell_coin(coin)
            self.stales = self.stales + 1

            # and block this coin for today:
            coin.naughty_timeout = int(self.naughty_timeout)
            return True
        return False

    # This is not being called anywhhere that matters
    def past_soft_limit(self, coin: Coin) -> bool:
        # This coin is past our soft limit
        # we apply a sliding window to the buy profit
        if (
            coin.holding_time > self.soft_limit_holding_time
        ):  # TODO: this is not a real time count
            profit_boundary = (
                float(self.sell_at_percentage) - 100
            ) - (2 * float(self.trading_fee))
            percentage_slice_per_holding_time_slice = (
                profit_boundary / self.hard_limit_holding_time
            )

            trail_target_slice_per_holding_time_slice = (
                100 - float(coin.trail_target_sell_percentage)
            ) / self.hard_limit_holding_time

            coin_life_left = self.hard_limit_holding_time - coin.holding_time
            new_sell_at_percentage = float(
                100 + (
                    coin_life_left * percentage_slice_per_holding_time_slice
                )
            )
            new_trail_target_sell_percentage = float(
                100 - (
                    coin_life_left * trail_target_slice_per_holding_time_slice
                )
            )

            coin.sell_at_percentage = new_sell_at_percentage
            coin.trail_target_sell_percentage = new_trail_target_sell_percentage

            self.log_debug_coin(coin)
            return True
        return False

    def log_debug_coin(self, coin: Coin) -> None:
        if self.debug:
            print(
                f"{coin.date} {coin.symbol} {coin.status} age:{coin.holding_time} now:{coin.price} bought:{coin.bought_at} sell:{coin.sell_at_percentage:.4f}% trail_target_sell:{coin.trail_target_sell_percentage:.4f}%"
            )


    def clear_all_coins_stats(self) -> None:
        for coin in self.coins:
            if coin not in self.wallet:
                self.clear_coin_stats(self.coins[coin])

    def clear_coin_stats(self, coin: Coin) -> None:
        coin.holding_time = 0
        coin.buy_at_percentage = self.buy_at_percentage
        coin.sell_at_percentage = self.sell_at_percentage
        coin.stop_loss_at_percentage = self.stop_loss_at_percentage
        coin.trail_target_sell_percentage = self.trail_target_sell_percentage
        coin.trail_recovery_percentage = self.trail_recovery_percentage
        coin.bought_at = float(0)
        coin.dip = float(0)
        coin.tip = float(0)
        coin.status = ""
        # TODO: should we just clear the stats on the coin we just sold?
        if self.clean_coin_stats_at_sale:
            coin.min = coin.price
            coin.max = coin.price

    def save_coins(self) -> None:
        with open(".coins.pickle", "wb") as f:
            pickle.dump(self.coins, f)
        with open(".wallet.pickle", "wb") as f:
            pickle.dump(self.wallet, f)

    def load_coins(self) -> None:
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

    # TODO: THIS function is not doing anything
    def check_for_sale_conditions(self, coin: Coin) -> Tuple[bool, str]:
        # return early if no work left to do
        if coin.symbol not in self.wallet:
            return (False, 'EMPTY_WALLET')

        # oh we already own this one, lets check prices
        # deal with STOP_LOSS first
        if self.stop_loss(coin):
            return (True, 'STOP_LOSS')

        # This coin is too old, sell it
        if self.past_hard_limit(coin):
            return (True, 'STALE')

        # coin was above sell_at_percentage and dropped below
        # lets' sell it ASAP
        if self.coin_gone_up_and_dropped(coin):
            return (True, 'GONE_UP_AND_DROPPED')

        # possible sale
        if self.possible_sale(coin):
            return (True, 'TARGET_SELL')

        # This coin is past our soft limit
        # we apply a sliding window to the buy profit
        if self.past_soft_limit(coin):
            return (False, 'PAST_SOFT_LIMIT')

        return (False, 'HOLD')

    # TODO: stale is not being consumed here
    def buy_drop_sell_recovery_strategy(self, coin: Coin) -> bool:
        # has the price gone down by x% on a coin we don't own?
        if (
            float(coin.price) < percent(coin.buy_at_percentage, coin.max)
        ) and coin.status == "":
            coin.dip = coin.price
            coin.status = "TARGET_DIP"

        if coin.status != "TARGET_DIP":
            return False

        # do some gimmicks, and don't buy the coin straight away
        # but only buy it when the price is now higher than the last
        # price recorded. This way we ensure that we got the dip
        self.log_debug_coin(coin)
        if float(coin.price) > float(coin.last):
            if float(coin.price) > percent(
                float(coin.trail_recovery_percentage), coin.dip
            ):
                self.buy_coin(coin)
                return True
        return False

    def buy_moon_sell_recovery_strategy(self, coin: Coin) -> bool:
        if float(coin.price) > percent(coin.buy_at_percentage, coin.last):
            self.buy_coin(coin)
            self.log_debug_coin(coin)
            return True
        return False

    def wait(self) -> None:
        sleep(self.pause)

    def run(self) -> None:
        self.load_coins()
        if self.clear_coin_stats_at_boot:
            cprint("WARNING: about the clear all coin stats...", "red")
            cprint("CTRL-C to cancel in the next 10 seconds", "red")
            sleep(10)
            self.clear_all_coins_stats()
        while True:
            self.process_coins()
            self.save_coins()
            self.wait()
            if exists(".stop"):
                print(".stop flag found. Stopping bot.")
                return

    def logmode(self) -> None:
        while True:
            self.process_coins()
            self.wait()

    def backtest_logfile(self, price_log: str) -> None:
        print(f"backtesting: {price_log}")
        print(f"wallet: {self.wallet}")
        read_counter = 0
        with lz4.frame.open(price_log, "rt") as f:
            while True:
                try:
                    line = f.readline()
                    if line == "":
                        break

                    if self.pairing not in line:
                        continue

                    parts = line.split(" ")
                    date = " ".join(parts[0:2])
                    symbol = parts[2]
                    market_price = float(parts[3])

                    if symbol not in self.tickers:
                        continue

                    # implements a PAUSE_FOR pause while reading from
                    # our price logs.
                    # we essentially skip a number of iterations between
                    # reads, causing a similar effect if we were only
                    # probing prices every PAUSE_FOR seconds
                    read_counter = read_counter + 1
                    if read_counter != PAUSE_FOR:
                        continue

                    read_counter = 0
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
                            self.trail_recovery_percentage,
                        )
                    else:
                        self.coins[symbol].update(date, market_price)
                    self.run_strategy(self.coins[symbol])
                except Exception as e:
                    print(traceback.format_exc())
                    if e == "KeyboardInterrupt":
                        print(f"BOOOM")
                        sys.exit(1)
                    pass

    def backtesting(self) -> None:
        for price_log in self.price_logs:
            self.backtest_logfile(price_log)

        with open("log/backtesting.log", "a") as f:
            log_entry = "|".join(
                [
                    f"profit:{self.profit:.3f}",
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
                ]
            )

            f.write(f"{log_entry}\n")


if __name__ == "__main__":
    try:
        client = Client(ACCESS_KEY, SECRET_KEY)
        bot = Bot(client)

        startup_msg = (
            f"buy_at:{BUY_AT_PERCENTAGE} "
            + f"sell_at:{SELL_AT_PERCENTAGE} "
            + f"stop_loss:{STOP_LOSS_AT_PERCENTAGE} "
            + f"max_coins:{MAX_COINS} "
            + f"soft_limit_holding_time:{SOFT_LIMIT_HOLDING_TIME} "
            + f"hard_limit_holding_time:{HARD_LIMIT_HOLDING_TIME} "
        )
        print(f"running in {bot.mode} mode with {startup_msg}")

        if bot.mode == "backtesting":
            bot.backtesting()

        if bot.mode == "logmode":
            bot.logmode()

        if bot.mode == "testnet":
            bot.client.API_URL = "https://testnet.binance.vision/api"
            bot.run()

        if bot.mode == "live":
            bot.run()

        for symbol in bot.wallet:
            cprint(f"still holding {symbol}", "red")
            holding = bot.coins[symbol]
            cprint(f" cost: {holding.volume * holding.bought_at}", "green")
            cprint(f" value: {holding.volume * holding.price}", "red")

        print(f"total profit: {bot.profit:.3f}")
        print(f"total fees: {bot.fees:.3f}")
        print(
            f"initial investment: {int(bot.initial_investment)} final investment: {int(bot.investment)}"
        )
        print(
            f"buy_at: {bot.buy_at_percentage} sell_at: {bot.sell_at_percentage} stop_loss: {bot.stop_loss_at_percentage}"
        )
        print(f"wins:{bot.wins} losses:{bot.losses} stales:{bot.stales}")
        print(f"list of excluded coins: {bot.excluded_coins}")

    except:
        print(traceback.format_exc())
        sys.exit(1)
