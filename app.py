""" CryptoBot for Binance """
import argparse
import logging
import json
import math
import pickle
import sys
import threading
import traceback
from collections import deque
from datetime import datetime
from functools import lru_cache
from itertools import islice
from os.path import exists
from time import sleep
from typing import Any, Dict, List, Tuple

import colorlog
import web_pdb
import yaml
from binance.client import Client
from binance.exceptions import BinanceAPIException
from tenacity import retry, wait_exponential
from xopen import xopen


c_handler = colorlog.StreamHandler(sys.stdout)
c_handler.setFormatter(
    colorlog.ColoredFormatter(
        '%(log_color)s[%(levelname)s] %(message)s',
        log_colors={
            'WARNING':  'yellow',
            'ERROR':    'red',
            'CRITICAL': 'red,bg_white',
        }
    )
)
c_handler.setLevel(logging.INFO)

f_handler = logging.FileHandler("log/debug.log")
f_handler.setLevel(logging.DEBUG)

logging.basicConfig(
    level=logging.DEBUG,
    format="[%(levelname)s] %(message)s",
    handlers=[ f_handler, c_handler ]
)


def mean(values: list) -> float:
    """returns the mean value of an array of integers"""
    return sum(values) / len(values)


def percent(part: float, whole: float) -> float:
    """returns the percentage value of a number"""
    result = float(whole) / 100 * float(part)
    return result


def add_100(number: float) -> float:
    """adds 100 to a number"""
    return float(100 + number)


class Coin: # pylint: disable=too-few-public-methods
    """ Coin Class"""
    def __init__(
        self,
        symbol: str,
        date: str,
        market_price: float,
        buy_at: float,
        sell_at: float,
        stop_loss: float,
        trail_target_sell_percentage: float,
        trail_recovery_percentage: float,
        soft_limit_holding_time: int,
        hard_limit_holding_time: int,
        downtrend_days: int,
    ) -> None:
        """Coin object"""
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
        self.buy_at_percentage: float = add_100(buy_at)
        self.sell_at_percentage: float = add_100(sell_at)
        self.stop_loss_at_percentage: float = add_100(stop_loss)
        self.status = ""
        self.trail_recovery_percentage: float = add_100(
            trail_recovery_percentage
        )
        self.trail_target_sell_percentage: float = add_100(
            trail_target_sell_percentage
        )
        self.dip = market_price
        self.tip = market_price
        self.naughty_timeout = int(0)
        self.profit = float(0)
        self.soft_limit_holding_time: int = int(soft_limit_holding_time)
        self.hard_limit_holding_time: int = int(hard_limit_holding_time)
        # TODO: this must support PAUSE_FOR values different than 1s
        self.averages: dict = {
            "counters": {
                "s": 0,
                "m": 0,
                "h": 0,
            },
            "s": deque([], maxlen=60),
            "m": deque([], maxlen=60),
            "h": deque([], maxlen=24),
            "d": [],
        }
        self.downtrend_days: int = int(downtrend_days)

    def update(self, date: str, market_price: float) -> None:
        """updates a coin object with latest market values"""
        self.date = date
        self.last = self.price
        self.price = float(market_price)

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
                s_value = percent(
                    self.trail_target_sell_percentage,
                    self.sell_at_percentage
                ) - 100
                logging.info(
                    f"{self.date}: {self.symbol} [HOLD] "
                    + f"-> [TARGET_SELL] ({self.price}) "
                    + f"A:{self.holding_time}s "
                    + f"U:{self.volume} P:{self.price} T:{self.value} "
                    + f"SP:{self.bought_at * self.sell_at_percentage /100} "
                    + f"S:+{s_value:.3f}% "
                    + f"TTS:-{(100 - self.trail_target_sell_percentage):.3f}% "
                    + f"LP:{(self.min):.3f} "
                )

        if self.status == "TARGET_SELL":
            if float(market_price) > float(self.tip):
                self.tip = market_price

        if self.status == "TARGET_DIP":
            if float(market_price) < float(self.dip):
                self.dip = market_price

        self.consolidate_averages(market_price)


    def consolidate_averages(self, market_price: float) -> None:
        """ consolidates all coin price averages over the different buckets """
        self.averages["s"].append(float(market_price))
        self.averages["counters"]["s"] += 1

        # TODO: this needs to work with PAUSE values
        if self.averages["counters"]["s"] == 60:
            last_s_avg = mean(self.averages["s"])
            self.averages["counters"]["s"] = 0
            self.averages["m"].append(last_s_avg)
            self.averages["counters"]["m"] += 1

        if self.averages["counters"]["m"] == 60:
            last_m_avg = mean(self.averages["m"])
            self.averages["counters"]["m"] = 0
            self.averages["h"].append(last_m_avg)
            self.averages["counters"]["h"] += 1

        if self.averages["counters"]["h"] == 24:
            last_h_avg = mean(self.averages["h"])
            self.averages["counters"]["h"] = 0
            self.averages["d"].append(last_h_avg)


class Bot:
    """ Bot Class """
    def __init__(self, conn, config) -> None:
        """Bot object"""
        self.client = conn
        self.initial_investment: float = float(config["INITIAL_INVESTMENT"])
        self.investment: float = float(config["INITIAL_INVESTMENT"])
        self.pause: float = float(config["PAUSE_FOR"])
        self.price_logs: List = config["PRICE_LOGS"]
        self.coins: Dict[str, Coin] = {}
        self.wins: int = 0
        self.losses: int = 0
        self.stales: int = 0
        self.profit: float = 0
        self.wallet: List = []  # store the coin we own
        self.tickers: dict = dict(config["TICKERS"])
        self.mode: str = config["MODE"]
        self.trading_fee: float = float(config["TRADING_FEE"])
        self.debug: bool = bool(config["DEBUG"])
        self.max_coins: int = int(config["MAX_COINS"])
        self.pairing: str = config["PAIRING"]
        self.fees: float = 0
        self.clear_coin_stats_at_boot: bool = bool(
            config["CLEAR_COIN_STATS_AT_BOOT"]
        )
        self.clean_coin_stats_at_sale: bool = bool(
            config["CLEAR_COIN_STATS_AT_SALE"]
        )
        self.strategy: str = config["STRATEGY"]
        self.sell_as_soon_it_drops: bool = bool(
            config["SELL_AS_SOON_IT_DROPS"]
        )

    def run_strategy(self, *argvs, **kwargs) -> None:
        """runs a specific strategy against a coin"""
        if len(self.wallet) != self.max_coins:
            if self.strategy == "buy_drop_sell_recovery_strategy":
                self.buy_drop_sell_recovery_strategy(*argvs, **kwargs)
            if self.strategy == "buy_moon_sell_recovery_strategy":
                self.buy_moon_sell_recovery_strategy(*argvs, **kwargs)
            if (
                self.strategy
                == "buy_on_recovery_after_n_days_downtrend_strategy"
            ):
                self.buy_on_recovery_after_n_days_downtrend_strategy(
                    *argvs, **kwargs
                )
        if len(self.wallet) != 0:
            self.check_for_sale_conditions(*argvs, **kwargs)

    def update_investment(self) -> None:
        """updates our investment or balance with our profits"""
        # and finally re-invest our profit, we're aiming to compound
        # so on every sale we invest our profit as well.
        self.investment = self.initial_investment + self.profit

    def update_bot_profit(self, coin) -> None:
        """updates the total bot profits"""
        bought_fees = percent(self.trading_fee, coin.cost)
        sell_fees = percent(self.trading_fee, coin.value)
        fees = float(bought_fees + sell_fees)

        self.profit = float(self.profit) + float(coin.profit) - float(fees)
        self.fees = self.fees + fees

    def buy_coin(self, coin) -> None:
        """calls Binance to buy a coin"""
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
            except BinanceAPIException as error_msg:
                logging.error(f"buy() exception: {error_msg}")
                logging.error(f"tried to buy: {volume} of {coin.symbol}")
                return

            orders = self.client.get_all_orders(symbol=coin.symbol, limit=1)
            while orders == []:
                logging.warning(
                    "Binance is being slow in returning the order, "
                    + "calling the API again..."
                )

                orders = self.client.get_all_orders(
                    symbol=coin.symbol, limit=1
                )
                sleep(1)

            coin.bought_at = self.extract_order_data(order_details, coin)[
                "avgPrice"
            ]
            coin.volume = self.extract_order_data(order_details, coin)[
                "volume"
            ]
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

        s_value = percent(
            coin.trail_target_sell_percentage,
            coin.sell_at_percentage
        ) - 100
        logging.info(
            f"{coin.date}: {coin.symbol} [{coin.status}] "
            + f"A:{coin.holding_time}s "
            + f"U:{coin.volume} P:{coin.price} T:{coin.value} "
            + f"SP:{coin.bought_at * coin.sell_at_percentage /100} "
            + f"SL:{coin.bought_at * coin.stop_loss_at_percentage / 100} "
            + f"S:+{s_value:.3f}% "
            + f"TTS:-{(100 - coin.trail_target_sell_percentage):.3f}% "
            + f"LP:{(coin.min):.3f} "
            + f"({len(self.wallet)}/{self.max_coins}) "
        )
        if self.debug:
            logging.debug(f"averages[d]: {coin.averages['d']}")
            logging.debug(f"averages[h]: {coin.averages['h']}")

    def sell_coin(self, coin) -> None:
        """calls Binance to sell a coin"""
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
            except BinanceAPIException as error_msg:
                logging.error(f"sell() exception: {error_msg}")
                logging.error(f"tried to sell: {coin.volume} of {coin.symbol}")
                return

            orders = self.client.get_all_orders(symbol=coin.symbol, limit=1)
            while orders == []:
                logging.warning(
                    "Binance is being slow in returning the order, "
                    + "calling the API again..."
                )

                orders = self.client.get_all_orders(
                    symbol=coin.symbol, limit=1
                )
                sleep(1)

            coin.price = self.extract_order_data(order_details, coin)[
                "avgPrice"
            ]
            coin.date = datetime.now()

        coin.value = float(float(coin.volume) * float(coin.price))
        coin.profit = float(float(coin.value) - float(coin.cost))

        if coin.profit < 0:
            message = "LS"
        else:
            message = "PRF"

        logging.info(
            f"{coin.date}: {coin.symbol} [{coin.status}] "
            + f"A:{coin.holding_time}s "
            + f"U:{coin.volume} P:{coin.price} T:{coin.value} "
            + f"{message}:{coin.profit:.3f} "
            + f"SP:{coin.bought_at * coin.sell_at_percentage /100} "
            + f"TP:{100 - (coin.bought_at / coin.price * 100):.2f}% "
            + f"SL:{coin.bought_at * coin.stop_loss_at_percentage/100} "
            + f"S:+{percent(coin.trail_target_sell_percentage,coin.sell_at_percentage) - 100:.3f}% "
            + f"TTS:-{(100 - coin.trail_target_sell_percentage):.3f}% "
            + f"LP:{(coin.min):.3f} "
            + f"({len(self.wallet)}/{self.max_coins}) "
        )
        coin.status = ""
        self.wallet.remove(coin.symbol)
        self.update_bot_profit(coin)
        self.update_investment()
        self.clear_coin_stats(coin)
        self.clear_all_coins_stats()

        logging.info(
            f"{coin.date}: INVESTMENT: {self.investment} "
            + f"PROFIT: {self.profit} WALLET: {self.wallet}"
        )

    def extract_order_data(self, order_details, coin) -> Dict[str, Any]:
        """calculate average price and volume for a buy order"""
        # TODO: review this whole mess

        total: float = 0
        qty: float = 0

        for k in order_details["fills"]:
            item_price = float(k["price"])
            item_qty = float(k["qty"])

            total += item_price * item_qty
            qty += item_qty

        avg = total / qty

        volume = float(self.calculate_volume_size(coin))

        return {
            "avgPrice": float(avg),
            "volume": float(volume),
        }

    @lru_cache()
    @retry(wait=wait_exponential(multiplier=1, max=10))
    def get_symbol_precision(self, symbol: str) -> int:
        """retrives and caches the decimal precision for a coin in binance"""
        try:
            info = self.client.get_symbol_info(symbol)
        except BinanceAPIException as error_msg:
            logging.error(error_msg)
            return -1

        step_size = float(info["filters"][2]["stepSize"])
        precision = int(round(-math.log(step_size, 10), 0))

        return precision

    def calculate_volume_size(self, coin) -> float:
        """calculates the amount of coin we are to buy"""
        precision = self.get_symbol_precision(coin.symbol)

        volume = float(
            round((self.investment / self.max_coins) / coin.price, precision)
        )

        if self.debug:
            logging.debug(
                f"[{coin.symbol}] investment:{self.investment} "
                + f"vol:{volume} price:{coin.price} precision:{precision}"
            )
        return volume

    @retry(wait=wait_exponential(multiplier=1, max=90))
    def get_binance_prices(self) -> List[Dict[str, str]]:
        """gets the list of all binance coin prices"""
        return self.client.get_all_tickers()

    def write_log(self, symbol: str, price: str) -> None:
        """updates the price.log file with latest prices"""
        if self.mode == "testnet":
            price_log = "log/testnet.log"
        else:
            price_log = f"log/{datetime.now().strftime('%Y%m%d')}.log"
        with open(price_log, "a", encoding='utf-8') as f:
            f.write(f"{datetime.now()} {symbol} {price}\n")

    def init_or_update_coin(self, binance_data: Dict[str, Any]) -> None:
        """creates a new coin or updates its price with latest binance data"""
        symbol = binance_data["symbol"]

        market_price = binance_data["price"]
        if symbol not in self.coins:
            self.coins[symbol] = Coin(
                symbol,
                str(datetime.now()),
                market_price,
                buy_at=self.tickers[symbol]["BUY_AT_PERCENTAGE"],
                sell_at=self.tickers[symbol]["SELL_AT_PERCENTAGE"],
                stop_loss=self.tickers[symbol]["STOP_LOSS_AT_PERCENTAGE"],
                trail_target_sell_percentage=self.tickers[symbol][
                    "TRAIL_TARGET_SELL_PERCENTAGE"
                ],
                trail_recovery_percentage=self.tickers[symbol][
                    "TRAIL_RECOVERY_PERCENTAGE"
                ],
                soft_limit_holding_time=self.tickers[symbol][
                    "SOFT_LIMIT_HOLDING_TIME"
                ],
                hard_limit_holding_time=self.tickers[symbol][
                    "HARD_LIMIT_HOLDING_TIME"
                ],
                downtrend_days=self.tickers[symbol]["DOWNTREND_DAYS"],
            )
        else:
            self.coins[symbol].update(str(datetime.now()), market_price)

    def process_coins(self) -> None:
        """processes all the prices returned by binance"""
        # look for coins that are ready for buying, or selling
        for binance_data in self.get_binance_prices():
            coin_symbol = binance_data["symbol"]
            price = binance_data["price"]

            if self.mode in ["live", "logmode", "testnet"]:
                self.write_log(coin_symbol, price)

            if self.mode not in ["live", "backtesting", "testnet"]:
                continue

            if coin_symbol not in self.tickers:
                continue

            self.init_or_update_coin(binance_data)
            if self.coins[coin_symbol].naughty_timeout > 0:
                continue

            if coin_symbol in self.tickers or coin_symbol in self.wallet:
                self.run_strategy(self.coins[coin_symbol])
            if coin_symbol in self.wallet:
                self.log_debug_coin(self.coins[coin_symbol])

    def stop_loss(self, coin: Coin) -> bool:
        """checks for possible loss on a coin"""
        # oh we already own this one, lets check prices
        # deal with STOP_LOSS
        if float(coin.price) < percent(
            coin.stop_loss_at_percentage, coin.bought_at
        ):
            coin.status = "STOP_LOSS"
            logging.warning(
                f"{coin.date} [{coin.symbol}] {coin.status} "
                + f"now: {coin.price} bought: {coin.bought_at}"
            )
            self.sell_coin(coin)
            self.losses = self.losses + 1
            # and block this coin for a while
            coin.naughty_timeout = int(
                self.tickers[coin.symbol]["NAUGHTY_TIMEOUT"]
            )
            return True
        return False

    def coin_gone_up_and_dropped(self, coin) -> bool:
        """checks for a possible drop in price in a coin we hold"""
        if coin.status == "TARGET_SELL" and float(coin.price) < percent(
            coin.sell_at_percentage, coin.bought_at
        ):
            coin.status = "GONE_UP_AND_DROPPED"
            logging.info(
                f"{coin.date} {coin.symbol} [TARGET_SELL] -> [GONE_UP_AND_DROPPED]"
            )
            self.sell_coin(coin)
            self.wins = self.wins + 1
            return True
        return False

    def possible_sale(self, coin: Coin) -> bool:
        """checks for a possible sale of a coin we hold"""
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

    def past_hard_limit(self, coin: Coin) -> bool:
        """checks for a possible stale coin we hold"""
        if coin.holding_time > coin.hard_limit_holding_time:
            coin.status = "STALE"
            self.sell_coin(coin)
            self.stales = self.stales + 1

            # and block this coin for today:
            coin.naughty_timeout = int(
                self.tickers[coin.symbol]["NAUGHTY_TIMEOUT"]
            )
            return True
        return False

    def past_soft_limit(self, coin: Coin) -> bool:
        """checks for if we should lower our sale percentages based on age"""
        # This coin is past our soft limit
        # we apply a sliding window to the buy profit
        if coin.holding_time > coin.soft_limit_holding_time:
            ttl = 100 * (
                1
                - float(
                    (coin.holding_time - coin.soft_limit_holding_time)
                    / (
                        coin.hard_limit_holding_time
                        - coin.soft_limit_holding_time
                    )
                )
            )  #

            coin.sell_at_percentage = add_100(
                percent(ttl, self.tickers[coin.symbol]["SELL_AT_PERCENTAGE"])
            )

            if coin.sell_at_percentage < add_100(2 * float(self.trading_fee)):
                coin.sell_at_percentage = add_100(2 * float(self.trading_fee))

            coin.trail_target_sell_percentage = (
                add_100(
                    percent(
                        ttl,
                        self.tickers[coin.symbol][
                            "TRAIL_TARGET_SELL_PERCENTAGE"
                        ],
                    )
                )
                - 0.001
            )

            self.log_debug_coin(coin)
            return True
        return False

    def log_debug_coin(self, coin: Coin) -> None:
        """logs debug coin prices"""
        if self.debug:
            logging.debug(
                f"{coin.date} {coin.symbol} "
                + f"{coin.status} "
                + f"age:{coin.holding_time} "
                + f"now:{coin.price} "
                + f"bought:{coin.bought_at} "
                + f"sell:{(coin.sell_at_percentage - 100):.4f}% "
                + f"trail_target_sell:{(coin.trail_target_sell_percentage - 100):.4f}% "
                + f"LP:{(coin.min):.3f} "
            )

    def clear_all_coins_stats(self) -> None:
        """clear important coin stats such as max, min price on all coins"""
        for coin in self.coins:
            if coin not in self.wallet:
                self.clear_coin_stats(self.coins[coin])

    def clear_coin_stats(self, coin: Coin) -> None:
        """clear important coin stats such as max, min price for a coin"""
        coin.holding_time = 1
        coin.buy_at_percentage = add_100(
            self.tickers[coin.symbol]["BUY_AT_PERCENTAGE"]
        )
        coin.sell_at_percentage = add_100(
            self.tickers[coin.symbol]["SELL_AT_PERCENTAGE"]
        )
        coin.stop_loss_at_percentage = add_100(
            self.tickers[coin.symbol]["STOP_LOSS_AT_PERCENTAGE"]
        )
        coin.trail_target_sell_percentage = add_100(
            self.tickers[coin.symbol]["TRAIL_TARGET_SELL_PERCENTAGE"]
        )
        coin.trail_recovery_percentage = add_100(
            self.tickers[coin.symbol]["TRAIL_RECOVERY_PERCENTAGE"]
        )
        coin.bought_at = float(0)
        coin.dip = float(0)
        coin.tip = float(0)
        coin.status = ""
        # TODO: should we just clear the stats on the coin we just sold?
        if self.clean_coin_stats_at_sale:
            coin.min = coin.price
            coin.max = coin.price

    def save_coins(self) -> None:
        """saves coins and wallet to a local pickle file"""
        with open("state/coins.pickle", "wb") as f:
            pickle.dump(self.coins, f)
        with open("state/wallet.pickle", "wb") as f:
            pickle.dump(self.wallet, f)

    def load_coins(self) -> None:
        """loads coins and wallet from a local pickle file"""
        if exists("state/coins.pickle"):
            logging.warning("found coins.pickle, loading coins")
            with open("state/coins.pickle", "rb") as f:
                self.coins = pickle.load(f)
        if exists("state/wallet.pickle"):
            logging.warning("found wallet.pickle, loading wallet")
            with open("state/wallet.pickle", "rb") as f:
                self.wallet = pickle.load(f)
            logging.warning(f"wallet contains {self.wallet}")

        # sync our coins state with the list of coins we want to use.
        # but keep using coins we currently have on our wallet
        coins_to_remove = []
        for coin in self.coins:
            if coin not in self.tickers and coin not in self.wallet:
                coins_to_remove.append(coin)

        for coin in coins_to_remove:
            self.coins.pop(coin)

        # finally apply the current settings in the config file

        symbols = ' '.join(self.coins.keys())
        logging.warning(f"overriding values from config for: {symbols}")
        for symbol in self.coins:
            self.coins[symbol].buy_at_percentage = add_100(
                self.tickers[symbol]["BUY_AT_PERCENTAGE"]
            )
            self.coins[symbol].sell_at_percentage = add_100(
                self.tickers[symbol]["SELL_AT_PERCENTAGE"]
            )
            self.coins[symbol].stop_loss_at_percentage = add_100(
                self.tickers[symbol]["STOP_LOSS_AT_PERCENTAGE"]
            )
            self.coins[symbol].soft_limit_holding_time = int(
                self.tickers[symbol]["SOFT_LIMIT_HOLDING_TIME"]
            )
            self.coins[symbol].hard_limit_holding_time = int(
                self.tickers[symbol]["HARD_LIMIT_HOLDING_TIME"]
            )
            self.coins[symbol].trail_target_sell_percentage = add_100(
                self.tickers[symbol]["TRAIL_TARGET_SELL_PERCENTAGE"]
            )
            self.coins[symbol].trail_recovery_percentage = add_100(
                self.tickers[symbol]["TRAIL_RECOVERY_PERCENTAGE"]
            )
            self.coins[symbol].downtrend_days = int(
                self.tickers[symbol]["DOWNTREND_DAYS"]
            )

    def check_for_sale_conditions(self, coin: Coin) -> Tuple[bool, str]:
        """checks for multiple sale conditions for a coin"""
        # return early if no work left to do
        if coin.symbol not in self.wallet:
            return (False, "EMPTY_WALLET")

        # oh we already own this one, lets check prices
        # deal with STOP_LOSS first
        if self.stop_loss(coin):
            return (True, "STOP_LOSS")

        # This coin is too old, sell it
        if self.past_hard_limit(coin):
            return (True, "STALE")

        # coin was above sell_at_percentage and dropped below
        # lets' sell it ASAP
        if self.sell_as_soon_it_drops:
            if self.coin_gone_up_and_dropped(coin):
                return (True, "GONE_UP_AND_DROPPED")

        # possible sale
        if self.possible_sale(coin):
            return (True, "TARGET_SELL")

        # This coin is past our soft limit
        # we apply a sliding window to the buy profit
        # TODO: make PAST_SOFT_LIMIT a full grown-up coin status
        if self.past_soft_limit(coin):
            return (False, "PAST_SOFT_LIMIT")

        return (False, "HOLD")

    def buy_drop_sell_recovery_strategy(self, coin: Coin) -> bool:
        """bot buy strategy"""
        # has the price gone down by x% on a coin we don't own?
        if (
            float(coin.price) < percent(coin.buy_at_percentage, coin.max)
        ) and coin.status == "":
            coin.dip = coin.price
            logging.info(
                f"{coin.date}: {coin.symbol} [{coin.status}] "
                + f"-> [TARGET_DIP] ({coin.price})"
            )
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

    # buy on recovery after long downtrend
    def buy_on_recovery_after_n_days_downtrend_strategy(
        self, coin: Coin
    ) -> bool:
        """bot buy strategy"""

        last_days = list(coin.averages["d"])[-coin.downtrend_days :]
        if len(last_days) < coin.downtrend_days:
            return False

        last_day = last_days[0]
        # if the price keeps going down, then buy
        for n in last_days:
            if n > last_day:
                return False
            last_day = n

        # has the price gone down by x% on a coin we don't own?
        if (
            float(coin.price) < percent(coin.buy_at_percentage, last_day)
        ) and coin.status == "":
            coin.dip = coin.price
            logging.info(
                f"{coin.date}: {coin.symbol} [{coin.status}] "
                + f"-> [TARGET_DIP] ({coin.price})"
            )
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
        """bot buy strategy"""
        if float(coin.price) > percent(coin.buy_at_percentage, coin.last):
            self.buy_coin(coin)
            self.log_debug_coin(coin)
            return True
        return False

    def wait(self) -> None:
        """implements a pause"""
        sleep(self.pause)

    def run(self) -> None:
        """the bot LIVE main loop"""
        self.load_coins()
        if self.clear_coin_stats_at_boot:
            logging.warning("About the clear all coin stats...")
            logging.warning("CTRL-C to cancel in the next 10 seconds")
            sleep(10)
            self.clear_all_coins_stats()
        while True:
            self.process_coins()
            self.save_coins()
            self.wait()
            if exists(".stop"):
                logging.warning(".stop flag found. Stopping bot.")
                return

    def logmode(self) -> None:
        """the bot LogMode main loop"""
        while True:
            self.process_coins()
            self.wait()

    def backtest_logfile(self, price_log: str) -> None:
        """processes one price.log file for backtesting"""
        logging.info(f"backtesting: {price_log}")
        logging.info(f"wallet: {self.wallet}")
        read_counter = 0
        with xopen(price_log, "rt") as f:
            while True:
                try:
                    next_n_lines = list(islice(f, 4 * 1024 * 1024))
                    if not next_n_lines:
                        break

                    for line in next_n_lines:
                        if self.pairing not in line:
                            continue

                        parts = line.split(" ")
                        symbol = parts[2]
                        if symbol not in self.tickers:
                            continue
                        date = " ".join(parts[0:2])
                        market_price = float(parts[3])

                        # implements a PAUSE_FOR pause while reading from
                        # our price logs.
                        # we essentially skip a number of iterations between
                        # reads, causing a similar effect if we were only
                        # probing prices every PAUSE_FOR seconds
                        read_counter = read_counter + 1
                        if read_counter != self.pause:
                            continue

                        read_counter = 0
                        # TODO: rework this
                        if symbol not in self.coins:
                            self.coins[symbol] = Coin(
                                symbol,
                                date,
                                market_price,
                                self.tickers[symbol]["BUY_AT_PERCENTAGE"],
                                self.tickers[symbol]["SELL_AT_PERCENTAGE"],
                                self.tickers[symbol]["STOP_LOSS_AT_PERCENTAGE"],
                                self.tickers[symbol][
                                    "TRAIL_TARGET_SELL_PERCENTAGE"
                                ],
                                self.tickers[symbol]["TRAIL_RECOVERY_PERCENTAGE"],
                                self.tickers[symbol]["SOFT_LIMIT_HOLDING_TIME"],
                                self.tickers[symbol]["HARD_LIMIT_HOLDING_TIME"],
                                self.tickers[symbol]["DOWNTREND_DAYS"],
                            )
                        else:
                            self.coins[symbol].update(date, market_price)
                        self.run_strategy(self.coins[symbol])
                except Exception as error_msg: # pylint: disable=broad-except
                    logging.error("Exception:")
                    logging.error(traceback.format_exc())
                    if error_msg == "KeyboardInterrupt":
                        sys.exit(1)

    def backtesting(self) -> None:
        """the bot Backtesting main loop"""
        logging.info(json.dumps(cfg, indent=4))
        for price_log in self.price_logs:
            self.backtest_logfile(price_log)

        with open("log/backtesting.log", "a", encoding='utf-8') as f:
            log_entry = "|".join(
                [
                    f"profit:{self.profit:.3f}",
                    f"investment:{self.initial_investment}",
                    f"days:{len(self.price_logs)}",
                    f"w{self.wins},l{self.losses},s{self.stales},h{len(self.wallet)}",
                    str(cfg),
                ]
            )

            f.write(f"{log_entry}\n")


def control_center():
    """ pdb web endpoint """
    web_pdb.set_trace()


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument("-c", "--config", help="config.yaml file")
        parser.add_argument("-s", "--secrets", help="secrets.yaml file")
        parser.add_argument(
            "-m", "--mode", help='bot mode ["live", "backtesting", "testnet"]'
        )
        args = parser.parse_args()

        with open(args.config, encoding='utf-8') as _f:
            cfg = yaml.safe_load(_f.read())
        with open(args.secrets, encoding='utf-8') as _f:
            secrets = yaml.safe_load(_f.read())
        cfg["MODE"] = args.mode

        client = Client(secrets["ACCESS_KEY"], secrets["SECRET_KEY"])
        bot = Bot(client, cfg)

        logging.info(
            f"running in {bot.mode} mode with "
            + f"{json.dumps(args.config, indent=4)}"
        )

        # start command-control-center (ipdb on port 5555)
        t = threading.Thread(target=control_center)
        t.daemon = True
        t.start()

        if bot.mode == "backtesting":
            bot.backtesting()

        if bot.mode == "logmode":
            bot.logmode()

        if bot.mode == "testnet":
            bot.client.API_URL = "https://testnet.binance.vision/api"
            bot.run()

        if bot.mode == "live":
            bot.run()

        for item in bot.wallet:
            holding = bot.coins[item]
            cost = holding.volume * holding.bought_at
            value = holding.volume * holding.price
            age = holding.holding_time

            logging.info(
                f"WALLET: {item} age:{age} cost:{cost} value:{value}"
            )

        logging.info(f"final profit: {bot.profit:.3f} fees: {bot.fees:.3f}")
        logging.info(
            f"investment: start: {int(bot.initial_investment)} "
            + f"end: {int(bot.investment)}"
        )
        logging.info(
            f"wins:{bot.wins} losses:{bot.losses} "
            + f"stales:{bot.stales} holds:{len(bot.wallet)}"
        )

    except Exception: # pylint: disable=broad-except
        logging.error(traceback.format_exc())
        sys.exit(1)
