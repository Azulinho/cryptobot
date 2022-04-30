""" CryptoBot for Binance """

import argparse
import json
import importlib
import math
import pickle
import sys
import threading
import traceback
from datetime import datetime
from functools import lru_cache
from hashlib import md5
from itertools import islice
from os import fsync
from os.path import exists, basename
from time import sleep
from typing import Any, Dict, List, Tuple

import yaml
import udatetime
import web_pdb
from binance.client import Client
from binance.exceptions import BinanceAPIException
from lz4.frame import open as lz4open
from tenacity import retry, wait_exponential
from xopen import xopen

from lib.helpers import (
    mean,
    percent,
    add_100,
    c_date_from,
    c_from_timestamp,
    requests_with_backoff,
    cached_binance_client,
    QLog
)

# initialize the Queue based logger
logger = QLog()


def control_center() -> None:
    """pdb web endpoint"""
    web_pdb.set_trace()


class Coin:  # pylint: disable=too-few-public-methods
    """Coin Class"""

    offset = {
        "s": 60,
        "m": 3600,
        "h": 86400
    }

    def __init__(
        self,
        symbol: str,
        date: float,
        market_price: float,
        buy_at: float,
        sell_at: float,
        stop_loss: float,
        trail_target_sell_percentage: float,
        trail_recovery_percentage: float,
        soft_limit_holding_time: int,
        hard_limit_holding_time: int,
        naughty_timeout: int,
        klines_trend_period: str,
        klines_slice_percentage_change: float
    ) -> None:
        """Coin object"""
        self.symbol = symbol
        self.volume: float = float(0)
        self.bought_at: float = float(0)
        self.min = float(market_price)
        self.max = float(market_price)
        self.date = date
        self.price = float(market_price)
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
        self.profit = float(0)
        self.soft_limit_holding_time: int = int(soft_limit_holding_time)
        self.hard_limit_holding_time: int = int(hard_limit_holding_time)
        self.naughty_timeout: int = int(naughty_timeout)
        self.lowest: dict = {
            "m": [],
            "h": [],
            "d": [],
        }
        self.averages: dict = {
            "s": [],
            "m": [],
            "h": [],
            "d": [],
        }
        self.highest: dict = {
            "m": [],
            "h": [],
            "d": [],
        }
        self.klines_trend_period: str = str(klines_trend_period)
        self.klines_slice_percentage_change: float = float(
            klines_slice_percentage_change
        )
        self.bought_date: float = None  # type: ignore
        self.naughty_date: float = None  # type: ignore
        self.naughty: bool = False
        self.last_read_date: float = date

    def update(self, date: float, market_price: float) -> None:
        """updates a coin object with latest market values"""
        self.date = date
        self.last = self.price
        self.price = market_price

        if self.status in ["TARGET_SELL", "HOLD"]:
            self.holding_time = int(self.date - self.bought_date)

        if self.naughty:
            if int(self.date - self.naughty_date) > self.naughty_timeout:
                self.naughty = False

        # do we have a new min price?
        if market_price < self.min:
            self.min = market_price

        # do we have a new max price?
        if market_price > self.max:
            self.max = market_price

        if self.volume:
            self.value = self.volume * self.price
            self.cost = self.bought_at * self.volume
            self.profit = self.value - self.cost

        if self.status == "HOLD":
            if market_price > percent(
                self.sell_at_percentage, self.bought_at
            ):
                self.status = "TARGET_SELL"
                s_value = (
                    percent(
                        self.trail_target_sell_percentage,
                        self.sell_at_percentage,
                    )
                    - 100
                )
                logger.send("info",
                    f"{c_from_timestamp(self.date)}: {self.symbol} [HOLD] "
                    + f"-> [TARGET_SELL] ({self.price}) "
                    + f"A:{self.holding_time}s "
                    + f"U:{self.volume} P:{self.price} T:{self.value} "
                    + f"SP:{self.bought_at * self.sell_at_percentage /100} "
                    + f"S:+{s_value:.3f}% "
                    + f"TTS:-{(100 - self.trail_target_sell_percentage):.3f}% "
                    + f"LP:{self.min:.3f} "
                )

        if self.status == "TARGET_SELL":
            if market_price > self.tip:
                self.tip = market_price

        if self.status == "TARGET_DIP":
            if market_price < self.dip:
                self.dip = market_price

        self.consolidate_averages(date, market_price)
        self.trim_averages(date)


    def consolidate_averages(self, date, market_price: float) -> None:
        """consolidates all coin price averages over the different buckets"""

        # append the latest 's' value, this could done more frequently than once
        # per second.
        self.averages["s"].append(
            (date, market_price)
        )

        # append the latest values,
        # but only if the old 'm' record, is older than 1 minute
        new_minute = False
        if not self.averages["m"] and self.averages['s']:
            if self.averages['s'][0][0] <= date - 60:
                new_minute = True

        if self.averages["m"] and not new_minute:
            record_date, _ = self.averages["m"][-1]
            if record_date <= date - 60:
                new_minute = True

        if new_minute:
            self.lowest['m'].append(
                (date, min([v for d,v in self.averages['s']]))
            )
            self.averages['m'].append(
                (date, mean([v for d,v in self.averages['s']]))
            )
            self.highest['m'].append(
                (date, max([v for d,v in self.averages['s']]))
            )
        else:
            return


        # append the latest values,
        # but only if the old 'h' record, is older than 1 hour
        new_hour = False
        if not self.averages["h"] and self.averages['m']:
            if self.averages['m'][0][0] <= date - 3600:
                new_hour = True

        if self.averages["h"] and not new_hour:
            record_date, _ = self.averages["h"][-1]
            if record_date <= date - 3600:
                new_hour = True

        if new_hour:
            self.lowest['h'].append(
                (date, min([v for d,v in self.lowest['m']]))
            )
            self.averages['h'].append(
                (date, mean([v for d,v in self.averages['m']]))
            )
            self.highest['h'].append(
                (date, max([v for d,v in self.highest['m']]))
            )
        else:
            return


        # append the latest values,
        # but only if the old 'd' record, is older than 1 day
        new_day = False
        if not self.averages["d"] and self.averages['h']:
            if self.averages['h'][0][0] <= date - 86400:
                new_day = True

        if self.averages["d"] and not new_day:
            record_date, _ = self.averages["d"][-1]
            if record_date <= date - 86400:
                new_day = True

        if new_day:
            self.lowest['d'].append(
                (date, min([v for d,v in self.lowest['h']]))
            )
            self.averages['d'].append(
                (date, mean([v for d,v in self.averages['h']]))
            )
            self.highest['d'].append(
                (date, max([v for d,v in self.highest['h']]))
            )


    def trim_averages(self, date: float) -> None:
        """trims all coin price older than ... """

        # clean up any old values older than 60s, 60m, 24h
        d,_ = self.averages['s'][0]
        if d < date - 60:
            del self.averages['s'][0]

            if self.averages['m']:
                d,_ = self.averages['m'][0]
                if d < date - 3600:
                    del self.lowest['m'][0]
                    del self.averages['m'][0]
                    del self.highest['m'][0]

                    if self.averages['h']:
                        d,_ = self.averages['h'][0]
                        if d < date - 86400:
                            del self.lowest['h'][0]
                            del self.averages['h'][0]
                            del self.highest['h'][0]


    def check_for_pump_and_dump(self):
        """ calculates current price vs 1 hour ago for pump/dump events """

        # if the strategy doesn't consume averages, we force an average setting
        # in here of 2hours so that we can use an anti-pump protection
        timeslice = int(''.join(self.klines_trend_period[:-1]))
        if timeslice == 0:
            self.klines_trend_period = "2h"
            self.klines_slice_percentage_change = float(1)

        # make the coin as a pump if we don't have enough data to validate if
        # this could possibly be a pump
        if len(self.averages["h"]) < 2:
            return True

        # on a pump, we would have a low price, followed by a pump(high price),
        # followed by a dump(low price)
        # so don't buy if we see this pattern over the last 2 hours.
        last2hours = self.averages["h"][-2:]

        two_hours_ago = last2hours[0][1]
        one_hour_ago = last2hours[1][1]

        if (
            two_hours_ago < one_hour_ago
        ) and (
            one_hour_ago > float(self.price)
        ) and (
            self.price > two_hours_ago
        ):
            return True

        return False

    def new_listing(self, mode):
        """ checks if coin is a new listing """
        # wait a few days before going to buy a new coin
        # since we list what coins we buy in TICKERS the bot would never
        # buy a coin as soon it is listed.
        # However in backtesting, the bot will buy that coin as its listed in
        # the TICKERS list and the price lines show up in the price logs.
        # we want to avoid buy these new listings as they will very volatile
        if mode == "backtesting" and len(self.averages['d']) < 31:
            return True
        return False

class Bot:
    """Bot Class"""

    def __init__(self, conn, config_file, config) -> None:
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
        self.config_file: str = config_file
        self.oldprice: Dict[str, float] = {}
        self.cfg = config
        self.enable_pump_and_dump_checks : bool = config.get(
            "ENABLE_PUMP_AND_DUMP_CHECKS", True
        )

    def run_strategy(self, coin) -> None:
        """runs a specific strategy against a coin"""
        if coin.symbol not in self.tickers:
            return

        if self.coins[coin.symbol].naughty:
            return

        if self.wallet:
            self.check_for_sale_conditions(coin)

        if len(self.wallet) == self.max_coins:
            return

        if coin.new_listing(self.mode):
            return

        if self.enable_pump_and_dump_checks:
            if coin.check_for_pump_and_dump():
                return

        self.buy_strategy(coin)


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

        if coin.naughty:
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
                logger.send("error", f"buy() exception: {error_msg}")
                logger.send("error", f"tried to buy: {volume} of {coin.symbol}")
                return

            orders = self.client.get_all_orders(symbol=coin.symbol, limit=1)
            while orders == []:
                logger.send("warning",
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
        coin.bought_date = coin.date

        s_value = (
            percent(coin.trail_target_sell_percentage, coin.sell_at_percentage)
            - 100
        )
        logger.send("info",
            f"{c_from_timestamp(coin.date)}: {coin.symbol} [{coin.status}] "
            + f"A:{coin.holding_time}s "
            + f"U:{coin.volume} P:{coin.price} T:{coin.value} "
            + f"SP:{coin.bought_at * coin.sell_at_percentage /100} "
            + f"SL:{coin.bought_at * coin.stop_loss_at_percentage / 100} "
            + f"S:+{s_value:.3f}% "
            + f"TTS:-{(100 - coin.trail_target_sell_percentage):.3f}% "
            + f"LP:{coin.min:.3f} "
            + f"({len(self.wallet)}/{self.max_coins}) "
        )
        if self.debug:
            logger.send("debug", f"lowest[m]: {coin.lowest['m']}")
            logger.send("debug",f"averages[m]: {coin.averages['m']}")
            logger.send("debug",f"highest[m]: {coin.highest['m']}")
            logger.send("debug",f"lowest[h]: {coin.lowest['h']}")
            logger.send("debug",f"averages[h]: {coin.averages['h']}")
            logger.send("debug",f"highest[h]: {coin.highest['h']}")
            logger.send("debug",f"lowest[d]: {coin.lowest['d']}")
            logger.send("debug",f"averages[d]: {coin.averages['d']}")
            logger.send("debug",f"highest[d]: {coin.highest['d']}")

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
                logger.send("error", f"sell() exception: {error_msg}")
                logger.send("error", f"tried to sell: {coin.volume} of {coin.symbol}")
                return

            orders = self.client.get_all_orders(symbol=coin.symbol, limit=1)
            while orders == []:
                logger.send("warning",
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
            coin.date = float(udatetime.now().timestamp())

        coin.value = float(float(coin.volume) * float(coin.price))
        coin.profit = float(float(coin.value) - float(coin.cost))

        if coin.profit < 0:
            word = "LS"
        else:
            word = "PRF"

        message = " ".join(
            [
                f"{c_from_timestamp(coin.date)}: {coin.symbol} [{coin.status}]",
                f"A:{coin.holding_time}s",
                f"U:{coin.volume} P:{coin.price} T:{coin.value}",
                f"{word}:{coin.profit:.3f}",
                f"SP:{coin.bought_at * coin.sell_at_percentage /100}",
                f"TP:{100 - (coin.bought_at / coin.price * 100):.2f}%",
                f"SL:{coin.bought_at * coin.stop_loss_at_percentage/100}",
                f"S:+{percent(coin.trail_target_sell_percentage,coin.sell_at_percentage) - 100:.3f}%", # pylint: disable=line-too-long
                f"TTS:-{(100 - coin.trail_target_sell_percentage):.3f}%",
                f"LP:{coin.min:.3f}",
                f"({len(self.wallet)}/{self.max_coins}) ",
            ]
        )

        if coin.profit < 0 or coin.holding_time > coin.hard_limit_holding_time:
            logger.send("warning", message)
        else:
            logger.send("info", message)

        self.wallet.remove(coin.symbol)
        self.update_bot_profit(coin)
        self.update_investment()
        coin.status = ""
        self.clear_coin_stats(coin)
        self.clear_all_coins_stats()

        logger.send("info",
            f"{c_from_timestamp(coin.date)}: INVESTMENT: {self.investment} "
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
        f_path = f"cache/{symbol}.precision"
        if self.mode == "backtesting" and exists(f_path):
            with open(f_path, "r") as f:
                info = json.load(f)
        else:
            try:
                info = self.client.get_symbol_info(symbol)
            except BinanceAPIException as error_msg:
                logger.send("error", error_msg)
                return -1

        step_size = float(info["filters"][2]["stepSize"])
        precision = int(round(-math.log(step_size, 10), 0))

        if self.mode == "backtesting" and not exists(f_path):
            with open(f_path, "w") as f:
                f.write(json.dumps(info))

        return precision

    def calculate_volume_size(self, coin) -> float:
        """calculates the amount of coin we are to buy"""
        precision = self.get_symbol_precision(coin.symbol)

        volume = float(
            round((self.investment / self.max_coins) / coin.price, precision)
        )

        if self.debug:
            logger.send("debug",
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
        # only write logs if price changed
        if not symbol in self.oldprice:
            self.oldprice[symbol] = float(0)

        if self.oldprice[symbol] == float(price):
            return

        self.oldprice[symbol] = float(price)

        if self.mode == "testnet":
            price_log = "log/testnet.log"
        else:
            price_log = f"log/{datetime.now().strftime('%Y%m%d')}.log"
        with open(price_log, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now()} {symbol} {price}\n")

    def init_or_update_coin(self, binance_data: Dict[str, Any]) -> None:
        """creates a new coin or updates its price with latest binance data"""
        symbol = binance_data["symbol"]

        market_price = float(binance_data["price"])
        if symbol not in self.coins:
            self.coins[symbol] = Coin(
                symbol,
                # TODO: update this to consume binance_data[]
                udatetime.now().timestamp(),
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
                naughty_timeout=self.tickers[symbol]["NAUGHTY_TIMEOUT"],
                klines_trend_period=self.tickers[symbol][
                    "KLINES_TREND_PERIOD"
                ],
                klines_slice_percentage_change=float(
                    self.tickers[symbol]["KLINES_SLICE_PERCENTAGE_CHANGE"]
                ),
            )
            self.load_klines_for_coin(self.coins[symbol])
        else:
            self.coins[symbol].update(
                udatetime.now().timestamp(),
                market_price
            )

    def process_coins(self) -> None:
        """processes all the prices returned by binance"""
        # look for coins that are ready for buying, or selling
        for binance_data in self.get_binance_prices():
            coin_symbol = binance_data["symbol"]
            price = binance_data["price"]

            if self.mode in ["logmode", "testnet"]:
                self.write_log(coin_symbol, price)

            if self.mode not in ["live", "backtesting", "testnet"]:
                continue

            if coin_symbol not in self.tickers:
                continue

            self.init_or_update_coin(binance_data)

            # if a coin has been blocked due to a stop_loss, we want to make
            # sure we reset the coin stats for the duration of the ban and
            # not just when the stop-loss event happened.
            # TODO: we are reseting the stats on every iteration while this
            # coin is in naughty state, look on how to avoid doing this.
            if self.coins[coin_symbol].naughty:
                self.clear_coin_stats(self.coins[coin_symbol])

            self.run_strategy(self.coins[coin_symbol])
            if coin_symbol in self.wallet:
                self.log_debug_coin(self.coins[coin_symbol])

    def stop_loss(self, coin: Coin) -> bool:
        """checks for possible loss on a coin"""
        # oh we already own this one, lets check prices
        # deal with STOP_LOSS
        if coin.price < percent(
            coin.stop_loss_at_percentage, coin.bought_at
        ) and coin.status != "STOP_LOSS":
            coin.status = "STOP_LOSS"
            self.sell_coin(coin)
            self.losses = self.losses + 1
            coin.naughty_date = coin.date  # pylint: disable=attribute-defined-outside-init
            self.clear_coin_stats(coin)
            coin.naughty = True  # pylint: disable=attribute-defined-outside-init
            return True
        return False

    def coin_gone_up_and_dropped(self, coin) -> bool:
        """checks for a possible drop in price in a coin we hold"""
        if coin.status == "TARGET_SELL" and coin.price < percent(
            coin.sell_at_percentage, coin.bought_at
        ):
            coin.status = "GONE_UP_AND_DROPPED"
            logger.send("info",
                f"{c_from_timestamp(coin.date)} {coin.symbol} " +
                "[TARGET_SELL] -> [GONE_UP_AND_DROPPED]"
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

            if coin.price != coin.last:
                self.log_debug_coin(coin)
            # has price has gone down ?
            if coin.price < coin.last:

                # and below our target sell percentage over the tip ?
                if coin.price < percent(
                    coin.trail_target_sell_percentage, coin.tip
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
            coin.naughty = True
            coin.naughty_date = coin.date
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
                - (
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

            if coin.sell_at_percentage < add_100(2 * self.trading_fee):
                coin.sell_at_percentage = add_100(2 * self.trading_fee)

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
            logger.send("debug",
                f"{c_from_timestamp(coin.date)} {coin.symbol} "
                + f"{coin.status} "
                + f"age:{coin.holding_time} "
                + f"now:{coin.price} "
                + f"bought:{coin.bought_at} "
                + f"sell:{(coin.sell_at_percentage - 100):.4f}% "
                + f"trail_target_sell:{(coin.trail_target_sell_percentage - 100):.4f}% "
                + f"LP:{coin.min:.3f} "
            )

    def clear_all_coins_stats(self) -> None:
        """clear important coin stats such as max, min price on all coins"""
        if self.clean_coin_stats_at_sale:
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
        if self.clean_coin_stats_at_sale:
            coin.min = coin.price
            coin.max = coin.price

    def save_coins(self) -> None:
        """saves coins and wallet to a local pickle file"""

        for statefile in ["state/coins.pickle", "state/wallet.pickle"]:
            if exists(statefile):
                with open(statefile, "rb") as f:
                    with open(f"{statefile}.backup", "wb") as b:
                        b.write(f.read())
                        b.flush()
                        fsync(b.fileno())

        with open("state/coins.pickle", "wb") as f:
            pickle.dump(self.coins, f)
            f.flush()
            fsync(f.fileno())
        with open("state/wallet.pickle", "wb") as f:
            pickle.dump(self.wallet, f)
            f.flush()
            fsync(f.fileno())

    def load_coins(self) -> None:
        """loads coins and wallet from a local pickle file"""
        if exists("state/coins.pickle"):
            logger.send("warning", "found coins.pickle, loading coins")
            with open("state/coins.pickle", "rb") as f:
                self.coins = pickle.load(f)
        if exists("state/wallet.pickle"):
            logger.send("warning", "found wallet.pickle, loading wallet")
            with open("state/wallet.pickle", "rb") as f:
                self.wallet = pickle.load(f)
            logger.send("warning", f"wallet contains {self.wallet}")

        # sync our coins state with the list of coins we want to use.
        # but keep using coins we currently have on our wallet
        coins_to_remove = []
        for coin in self.coins:
            if coin not in self.tickers and coin not in self.wallet:
                coins_to_remove.append(coin)

        for coin in coins_to_remove:
            self.coins.pop(coin)

        # finally apply the current settings in the config file

        symbols = " ".join(self.coins.keys())
        logger.send("warning", f"overriding values from config for: {symbols}")
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
            self.coins[symbol].klines_trend_period = str(
                self.tickers[symbol]["KLINES_TREND_PERIOD"]
            )
            self.coins[symbol].klines_slice_percentage_change = float(
                self.tickers[symbol]["KLINES_SLICE_PERCENTAGE_CHANGE"]
            )

            # deal with missing coin properties, types after a bot upgrade
            if isinstance(self.coins[symbol].date, str):
                self.coins[symbol].date = float(
                    datetime.fromisoformat(str(self.coins[symbol].date)
                    ).timestamp()
                )
            if "naughty" not in dir(self.coins[symbol]):
                if self.coins[symbol].naughty_timeout != 0:
                    self.coins[symbol].naughty = True
                    self.coins[symbol].naughty_date = self.coins[
                        symbol
                    ].naughty_date - self.coins[symbol].naughty_timeout
                else:
                    self.coins[symbol].naughty = False
                    self.coins[symbol].naughty_date = None  # type: ignore

            if "bought_date" not in dir(self.coins[symbol]):
                if symbol in self.wallet:
                    self.coins[symbol].bought_date = self.coins[
                        symbol
                    ].date - self.coins[symbol].holding_time
                else:
                    self.coins[symbol].bought_date = None  # type: ignore

            if "lowest" not in dir(self.coins[symbol]):
                self.coins[symbol].lowest = {'m': [], 'h': [], 'd': []}

            if "averages" not in dir(self.coins[symbol]):
                self.coins[symbol].averages = {
                    's': [],
                    'm': [],
                    'h': [],
                    'd': []
                }

            if "highest" not in dir(self.coins[symbol]):
                self.coins[symbol].highest = {'m': [], 'h': [], 'd': []}

            self.coins[symbol].naughty_timeout = int(
                self.tickers[symbol]["NAUGHTY_TIMEOUT"]
            )

        if self.wallet:
            logger.send("info", "Wallet contains:")
            for symbol in self.wallet:
                sell_price = (
                    float(
                        self.coins[symbol].bought_at
                        * self.coins[symbol].sell_at_percentage
                    )
                    / 100
                )
                s_value = (
                    percent(
                        self.coins[symbol].trail_target_sell_percentage,
                        self.coins[symbol].sell_at_percentage,
                    )
                    - 100
                )
                logger.send("info",
                    f"{self.coins[symbol].date}: {symbol} "
                    + f"{self.coins[symbol].status} "
                    + f"A:{self.coins[symbol].holding_time}s "
                    + f"U:{self.coins[symbol].volume} "
                    + f"P:{self.coins[symbol].price} "
                    + f"T:{self.coins[symbol].value} "
                    + f"SP:{sell_price} "
                    + f"S:+{s_value:.3f}% "
                    + f"TTS:-{(100 - self.coins[symbol].trail_target_sell_percentage):.3f}% "
                    + f"LP:{self.coins[symbol].min:.3f} "
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

    def buy_strategy(self, coin: Coin) -> bool:
        """buy strategy"""

    def wait(self) -> None:
        """implements a pause"""
        sleep(self.pause)

    def run(self) -> None:
        """the bot LIVE main loop"""
        self.load_coins()
        if self.clear_coin_stats_at_boot:
            logger.send("warning", "About the clear all coin stats...")
            logger.send("warning", "CTRL-C to cancel in the next 10 seconds")
            sleep(10)
            self.clear_all_coins_stats()

        while True:
            self.process_coins()
            self.save_coins()
            self.wait()
            if exists(".stop"):
                logger.send("warning", ".stop flag found. Stopping bot.")
                return

    def logmode(self) -> None:
        """the bot LogMode main loop"""
        while True:
            self.process_coins()
            self.wait()

    def process_line(self, line: str) -> None:
        """processes a backlog line"""
        if self.pairing not in line:
            return

        parts = line.split(" ", maxsplit=4)
        symbol = parts[2]
        if symbol not in self.tickers:
            return
        day = " ".join(parts[0:2])
        try:
            # datetime is very slow, discard the .microseconds and fetch a
            # cached pre-calculated unix epoch timestamp
            day = day.split('.', maxsplit=1)[0]
            date = c_date_from(day)
        except ValueError:
            date = c_date_from(day)

        try:
            # ocasionally binance returns incorrect prices
            # we just skip it
            market_price = float(parts[3])
        except ValueError:
            return

        # TODO: rework this, generate a binance_data blob to pass to
        # init_or_update_coin()
        if symbol not in self.coins:
            self.coins[symbol] = Coin(
                symbol,
                date,
                market_price,
                self.tickers[symbol]["BUY_AT_PERCENTAGE"],
                self.tickers[symbol]["SELL_AT_PERCENTAGE"],
                self.tickers[symbol]["STOP_LOSS_AT_PERCENTAGE"],
                self.tickers[symbol]["TRAIL_TARGET_SELL_PERCENTAGE"],
                self.tickers[symbol]["TRAIL_RECOVERY_PERCENTAGE"],
                self.tickers[symbol]["SOFT_LIMIT_HOLDING_TIME"],
                self.tickers[symbol]["HARD_LIMIT_HOLDING_TIME"],
                self.tickers[symbol]["NAUGHTY_TIMEOUT"],
                self.tickers[symbol]["KLINES_TREND_PERIOD"],
                self.tickers[symbol]["KLINES_SLICE_PERCENTAGE_CHANGE"],
            )
            self.load_klines_for_coin(self.coins[symbol])
        else:
            # implements a PAUSE_FOR pause while reading from
            # our price logs.
            # we essentially skip a number of iterations between
            # reads, causing a similar effect if we were only
            # probing prices every PAUSE_FOR seconds
            if self.coins[symbol].last_read_date + self.pause > date:
                return
            self.coins[symbol].last_read_date = date

            self.coins[symbol].update(date, market_price)

        self.run_strategy(self.coins[symbol])

    def backtest_logfile(self, price_log: str) -> None:
        """processes one price.log file for backtesting"""
        logger.send("info", f"backtesting: {price_log}")
        logger.send("info", f"wallet: {self.wallet}")
        try:
            if price_log.endswith(".lz4"):
                f = lz4open(price_log, mode="rt")
            else:
                f = xopen(price_log, "rt")
            while True:
                next_n_lines = list(islice(f, 4 * 1024 * 1024))
                if not next_n_lines:
                    break

                for line in next_n_lines:
                    self.process_line(line)
            f.close()
        except Exception as error_msg:  # pylint: disable=broad-except
            logger.send("error", "Exception:")
            logger.send("error", traceback.format_exc())
            if error_msg == "KeyboardInterrupt":
                sys.exit(1)

    def backtesting(self) -> None:
        """the bot Backtesting main loop"""
        logger.send("info", json.dumps(self.cfg, indent=4))

        self.clear_all_coins_stats()

        for price_log in self.price_logs:
            self.backtest_logfile(price_log)

        with open("log/backtesting.log", "a", encoding="utf-8") as f:
            current_exposure = float(0)
            for symbol in self.wallet:
                current_exposure = current_exposure + self.coins[symbol].profit

            log_entry = "|".join(
                [
                    f"profit:{self.profit + current_exposure:.3f}",
                    f"investment:{self.initial_investment}",
                    f"days:{len(self.price_logs)}",
                    f"w{self.wins},l{self.losses},s{self.stales},h{len(self.wallet)}",
                    f"cfg:{basename(self.config_file)}",
                    str(self.cfg),
                ]
            )

            f.write(f"{log_entry}\n")

    def load_klines_for_coin(self, coin) -> None:
        """fetches from binance or a local cache klines for a coin"""

        symbol = coin.symbol
        logger.send("info", f"{c_from_timestamp(coin.date)}: loading klines for: {symbol}")

        api_url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&"

        for unit in ["m", "h", "d"]:

            # lets find out the from what date we need to pull klines from while in
            # backtesting mode.
            coin.averages[unit] = []
            if unit == "m":
                timeslice = 60
                minutes_before_now = 1
            if unit == "h":
                timeslice = 24
                minutes_before_now = 60

            if unit == "d":
                timeslice = 1000  # retrieve 1000 days, binance API default
                minutes_before_now = 60 * 24

            backtest_end_time = coin.date
            end_unix_time = int(
                (
                    backtest_end_time - (60  * minutes_before_now)
                ) * 1000
            )

            query = f"{api_url}endTime={end_unix_time}&interval=1{unit}"
            md5_query = md5(query.encode()).hexdigest()
            f_path = f"cache/{symbol}.{md5_query}"

            if exists(f_path):
                with open(f_path, "r") as f:
                    results = json.load(f)
            else:
                results = requests_with_backoff(query).json()
                # this can be fairly API intensive for a large number of tickers
                if self.mode == "backtesting":
                    with open(f_path, "w") as f:
                        f.write(json.dumps(results))

            if self.debug:
                logger.send("debug", f"{symbol} : last_{unit}:{results[-1:]}")

            if timeslice != 0:
                lowest = []
                averages = []
                highest = []
                for _, _, high, low, _, _, closetime, _, _, _, _,_ in results:
                    date = float(
                        datetime.fromtimestamp(closetime / 1000).timestamp()
                    )
                    low = float(low)
                    high = float(high)
                    avg = (low  + high ) / 2

                    lowest.append((date, low ))
                    averages.append((date, avg ))
                    highest.append((date, high ))

                for d, v in lowest[-timeslice:]:
                    coin.lowest[unit].append((d, v))

                for d, v in averages[-timeslice:]:
                    coin.averages[unit].append((d, v))

                for d, v in highest[-timeslice:]:
                    coin.highest[unit].append((d, v))

        if self.debug:
            logger.send("debug", f"{symbol} : price:{coin.price}")
            logger.send("debug", f"{symbol} : min:{coin.min}")
            logger.send("debug", f"{symbol} : max:{coin.max}")
            logger.send("debug", f"{symbol} : lowest['m']:{coin.lowest['m']}")
            logger.send("debug", f"{symbol} : lowest['h']:{coin.lowest['h']}")
            logger.send("debug", f"{symbol} : lowest['d']:{coin.lowest['d']}")
            logger.send("debug", f"{symbol} : averages['m']:{coin.averages['m']}")
            logger.send("debug", f"{symbol} : averages['h']:{coin.averages['h']}")
            logger.send("debug", f"{symbol} : averages['d']:{coin.averages['d']}")
            logger.send("debug", f"{symbol} : highest['m']:{coin.highest['m']}")
            logger.send("debug", f"{symbol} : highest['h']:{coin.highest['h']}")
            logger.send("debug", f"{symbol} : highest['d']:{coin.highest['d']}")

    def print_final_balance_report(self):
        """ calculates and outputs final balance """

        current_exposure = float(0)
        for item in self.wallet:
            holding = self.coins[item]
            cost = holding.volume * holding.bought_at
            value = holding.volume * holding.price
            age = holding.holding_time
            current_exposure = current_exposure + self.coins[item].profit

            logger.send("info", f"WALLET: {item} age:{age} cost:{cost} value:{value}")

        logger.send("info", f"bot profit: {self.profit}")
        logger.send("info", f"current exposure: {current_exposure:.3f}")
        logger.send("info", f"total fees: {self.fees:.3f}")
        logger.send("info", f"final balance: {self.profit + current_exposure:.3f}")
        logger.send("info",
            f"investment: start: {int(self.initial_investment)} "
            + f"end: {int(self.investment)}"
        )
        logger.send("info",
            f"wins:{self.wins} losses:{self.losses} "
            + f"stales:{self.stales} holds:{len(self.wallet)}"
        )

if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument("-c", "--config", help="config.yaml file")
        parser.add_argument("-s", "--secrets", help="secrets.yaml file")
        parser.add_argument(
            "-m", "--mode", help='bot mode ["live", "backtesting", "testnet"]'
        )
        args = parser.parse_args()


        with open(args.config, encoding="utf-8") as _f:
            cfg = yaml.safe_load(_f.read())
        with open(args.secrets, encoding="utf-8") as _f:
            secrets = yaml.safe_load(_f.read())
        cfg["MODE"] = args.mode

        if args.mode == "backtesting":
            client = cached_binance_client(
                secrets["ACCESS_KEY"], secrets["SECRET_KEY"]
            )
        else:
            client = Client(secrets["ACCESS_KEY"], secrets["SECRET_KEY"])

        module = importlib.import_module(f"strategies.{cfg['STRATEGY']}")
        Strategy = getattr(module, 'Strategy')

        bot = Strategy(
            client, args.config, cfg
        )  # type: ignore

        logger.send("info",
            f"running in {bot.mode} mode with "
            + f"{json.dumps(args.config, indent=4)}"
        )

        if bot.mode in ["testnet", "live"]:
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

        bot.print_final_balance_report()
        logger.stop()

    except Exception:  # pylint: disable=broad-except
        logger.send("error", traceback.format_exc())
        sleep(1)
        sys.exit(1)
