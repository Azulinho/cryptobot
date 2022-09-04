""" CryptoBot for Binance """

import argparse
import gzip
import importlib
import json
import logging
import pickle  # nosec
import sys
import threading
import traceback
from datetime import datetime
from functools import lru_cache
from hashlib import md5
from itertools import islice
from os import fsync, getpid
from os.path import basename, exists
from time import sleep
from typing import Any, Dict, List, Tuple

import colorlog
import epdb
import udatetime
import yaml
from binance.client import Client
from binance.exceptions import BinanceAPIException
from filelock import FileLock
from lz4.frame import open as lz4open
from tenacity import retry, wait_exponential

from lib.helpers import (add_100, c_date_from, c_from_timestamp,
                         cached_binance_client, floor_value, mean, percent,
                         requests_with_backoff)


def control_center() -> None:
    """pdb remote endpoint"""
    while True:
        try:
            epdb.serve(port=5555)
        except Exception:  # pylint: disable=broad-except
            pass


class Coin:  # pylint: disable=too-few-public-methods
    """Coin Class"""

    offset = {"s": 60, "m": 3600, "h": 86400}

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
        klines_slice_percentage_change: float,
    ) -> None:
        """Coin object"""
        self.symbol = symbol
        # number of units of a coin held
        self.volume: float = float(0)
        # what price we bought the coin
        self.bought_at: float = float(0)
        # minimum coin price recorded since reset
        self.min = float(market_price)
        # maximum coin price recorded since reset
        self.max = float(market_price)
        #  date of latest price info available for this coin
        self.date = date
        # current price for the coin
        self.price = float(market_price)
        # how long in secs we have been holding this coin
        self.holding_time = int(0)
        # current value, as number of units vs current price
        self.value = float(0)
        # total cost for all units at time ot buy
        self.cost = float(0)
        # coin price recorded in the previous iteration
        self.last = market_price
        # percentage to mark coin as TARGET_DIP
        self.buy_at_percentage: float = add_100(buy_at)
        # percentage to mark coin as TARGET_SELL
        self.sell_at_percentage: float = add_100(sell_at)
        # percentage to trigger a stop loss
        self.stop_loss_at_percentage: float = add_100(stop_loss)
        # current status of coins ['', 'HOLD', 'TARGET_DIP', ...]
        self.status = ""
        # percentage to recover after a drop that triggers a buy
        self.trail_recovery_percentage: float = add_100(
            trail_recovery_percentage
        )
        # trailling stop loss
        self.trail_target_sell_percentage: float = add_100(
            trail_target_sell_percentage
        )
        # lowest price while the coin is in TARGET_DIP
        self.dip = market_price
        # highest price while the coin in TARGET_SELL
        self.tip = market_price
        # total profit for this coin
        self.profit = float(0)
        # how to long to keep a coin before shrinking SELL_AT_PERCENTAGE
        self.soft_limit_holding_time: int = int(soft_limit_holding_time)
        # How long to hold a coin before forcing a sale
        self.hard_limit_holding_time: int = int(hard_limit_holding_time)
        # how long to block the bot from buying a coin after a STOP_LOSS
        self.naughty_timeout: int = int(naughty_timeout)
        # dicts storing price data, on different buckets
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
        # How long to look for trend changes in a coin price
        self.klines_trend_period: str = str(klines_trend_period)
        # percentage of coin price change in a trend_period slice
        self.klines_slice_percentage_change: float = float(
            klines_slice_percentage_change
        )
        # what date we bought the coin
        self.bought_date: float = None  # type: ignore
        # what date we had the last STOP_LOSS
        self.naughty_date: float = None  # type: ignore
        # if we're currently not buying this coin
        self.naughty: bool = False
        # used in backtesting, the last read date, as the date in the price.log
        self.last_read_date: float = date

    def update(self, date: float, market_price: float) -> None:
        """updates a coin object with latest market values"""
        self.date = date
        self.last = self.price
        self.price = market_price

        # update any coin we HOLD with the number seconds since we bought it
        if self.status in ["TARGET_SELL", "HOLD"]:
            self.holding_time = int(self.date - self.bought_date)

        # if we had a STOP_LOSS event, and we've expired the NAUGHTY_TIMEOUT
        # then set the coin free again, and allow the bot to buy it.
        if self.naughty:
            if int(self.date - self.naughty_date) > self.naughty_timeout:
                self.naughty = False

        # do we have a new min price?
        if market_price < self.min:
            self.min = market_price

        # do we have a new max price?
        if market_price > self.max:
            self.max = market_price

        # self.volume is only set when we hold this coin in our wallet
        if self.volume:
            self.value = self.volume * self.price
            self.cost = self.bought_at * self.volume
            self.profit = self.value - self.cost

        # Check for a coin we HOLD if we reached the SELL_AT_PERCENTAGE
        # and mark that coin as TARGET_SELL if we have.
        if self.status == "HOLD":
            if market_price > percent(self.sell_at_percentage, self.bought_at):
                self.status = "TARGET_SELL"
                s_value = (
                    percent(
                        self.trail_target_sell_percentage,
                        self.sell_at_percentage,
                    )
                    - 100
                )
                logging.info(
                    f"{c_from_timestamp(self.date)}: {self.symbol} [HOLD] "
                    + f"-> [TARGET_SELL] ({self.price}) "
                    + f"A:{self.holding_time}s "
                    + f"U:{self.volume} P:{self.price} T:{self.value} "
                    + f"BP:{self.bought_at} "
                    + f"SP:{self.bought_at * self.sell_at_percentage /100} "
                    + f"S:+{s_value:.3f}% "
                    + f"TTS:-{(100 - self.trail_target_sell_percentage):.2f}% "
                    + f"LP:{self.min}(-{100 - ((self.min/self.max) * 100):.3f}%) "
                )

        # monitors for the highest price recorded for a coin we are looking
        # to sell soon.
        if self.status == "TARGET_SELL":
            if market_price > self.tip:
                self.tip = market_price

        # monitors for the lowest price recorded for a coin we are looking
        # to buy soon.
        if self.status == "TARGET_DIP":
            if market_price < self.dip:
                logging.debug(f"{self.symbol}: new dip: {self.dip}")
                self.dip = market_price

        # updates the different price buckets data for this coint and
        # removes any old data from those buckets.
        self.consolidate_averages(date, market_price)
        self.trim_averages(date)

    def consolidate_on_new_slot(self, date, unit):
        """consolidates on a new min/hour/day"""

        previous = {"d": "h", "h": "m", "m": "s"}[unit]

        if unit != "m":
            self.lowest[unit].append(
                (date, min([v for _, v in self.lowest[previous]]))
            )
            self.averages[unit].append(
                (date, mean([v for _, v in self.averages[previous]]))
            )
            self.highest[unit].append(
                (date, max([v for _, v in self.highest[previous]]))
            )
        else:
            self.lowest["m"].append(
                (date, min([v for _, v in self.averages["s"]]))
            )
            self.averages["m"].append(
                (date, mean([v for _, v in self.averages["s"]]))
            )
            self.highest["m"].append(
                (date, max([v for _, v in self.averages["s"]]))
            )

    def consolidate_averages(self, date, market_price: float) -> None:
        """consolidates all coin price averages over the different buckets"""

        # append the latest 's' value, this could done more frequently than
        # once per second.
        self.averages["s"].append((date, market_price))

        # append the latest values,
        # but only if the old 'm' record, is older than 1 minute
        new_minute = self.is_a_new_slot_of(date, "m")
        # on a new minute window, we need to find the lowest, average, and max
        # prices across all the last 60 seconds of data we have available in
        # our 'seconds' buckets.
        # note that for seconds, we only store 'averages' as it doesn't make
        # sense, to record lows/highs within a second window
        if new_minute:
            self.consolidate_on_new_slot(date, "m")
        else:
            # finally if we're not reached a new minute, then jump out early
            # as we won't have any additional data to process in the following
            # buckets of hours, or days
            return

        # deals with the scenario where we have minutes data but no hourly
        # data in our buckets yet.
        # if we find the oldest record in our 'minutes' bucket is older than
        # 1 hour, then we have entered a new hour window.
        new_hour = self.is_a_new_slot_of(date, "h")

        # on a new hour, we need to record the min, average, max prices for
        # this coin, based on the data we have from the last 60 minutes.
        if new_hour:
            self.consolidate_on_new_slot(date, "h")
        else:
            # if we're not in a new hour, then skip further processing as
            # there won't be any new day changes to be managed.
            return

        # deal with the scenario where we have hourly data but no daily data
        # yet if the older record for hourly data is older than 1 day, then
        # we've entered a new day window
        new_day = self.is_a_new_slot_of(date, "d")

        # on a new day window, we need to update the min, averages, max prices
        # recorded for this coin, based on the history available from the last
        # 24 hours as recorded in our hourly buckets.
        if new_day:
            self.consolidate_on_new_slot(date, "d")

    def is_a_new_slot_of(self, date, unit):
        """finds out if we entered a new unit time slot"""
        table = {
            "m": ("s", 60),
            "h": ("m", 3600),
            "d": ("h", 86400),
        }
        previous, period = table[unit]

        new_slot = False
        # deals with the scenario, where we don't yet have 'units' data
        #  available yet
        if not self.averages[unit] and self.averages[previous]:
            if self.averages[previous][0][0] <= date - period:
                new_slot = True

        # checks if our latest 'unit' record is older than 'period'
        # then we've entered a new 'unit' window
        if self.averages[unit] and not new_slot:
            record_date, _ = self.averages[unit][-1]
            if record_date <= date - period:
                new_slot = True
        return new_slot

    def trim_averages(self, date: float) -> None:
        """trims all coin price older than ..."""

        # checks the older record for each bucket and cleans up any data
        # older than 60secs, 60min, 24hours
        d, _ = self.averages["s"][0]
        if d < date - 60:
            del self.averages["s"][0]

            if self.averages["m"]:
                d, _ = self.averages["m"][0]
                if d < date - 3600:
                    del self.lowest["m"][0]
                    del self.averages["m"][0]
                    del self.highest["m"][0]

                    if self.averages["h"]:
                        d, _ = self.averages["h"][0]
                        if d < date - 86400:
                            del self.lowest["h"][0]
                            del self.averages["h"][0]
                            del self.highest["h"][0]

    def check_for_pump_and_dump(self):
        """calculates current price vs 1 hour ago for pump/dump events"""

        # disclaimer: this might need some work, as it only avoids very sharp
        # pump and dump short peaks.

        # if the strategy doesn't consume averages, we force an average setting
        # in here of 2hours so that we can use an anti-pump protection
        timeslice = int("".join(self.klines_trend_period[:-1]))
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
            (two_hours_ago < one_hour_ago)
            and (one_hour_ago > float(self.price))
            and (self.price > two_hours_ago)
        ):
            return True

        return False

    def new_listing(self, days):
        """checks if coin is a new listing"""
        # wait a few days before going to buy a new coin
        # since we list what coins we buy in TICKERS the bot would never
        # buy a coin as soon it is listed.
        # However in backtesting, the bot will buy that coin as its listed in
        # the TICKERS list and the price lines show up in the price logs.
        # we want to avoid buy these new listings as they are very volatile
        # and the bot won't have enough history to properly backtest a coin
        # looking for a profit pattern to use.
        if len(self.averages["d"]) < days:
            return True
        return False


class Bot:
    """Bot Class"""

    def __init__(self, conn, config_file, config) -> None:
        """Bot object"""

        # Binance API handler
        self.client = conn
        # amount available to the bot to invest as set in the config file
        self.initial_investment: float = float(config["INITIAL_INVESTMENT"])
        # current investment amount
        self.investment: float = float(config["INITIAL_INVESTMENT"])
        # number of seconds to pause between price checks
        self.pause: float = float(config["PAUSE_FOR"])
        # list of price.logs to use during backtesting
        self.price_logs: List = config["PRICE_LOGS"]
        # dictionary for all coin data
        self.coins: Dict[str, Coin] = {}
        # number of wins record by this bot run
        self.wins: int = 0
        # number of losses record by this bot run
        self.losses: int = 0
        # number of stale coins (which didn't sell before their
        # HARD_LIMIT_HOLDING_TIME) record by this bot run
        self.stales: int = 0
        # total profit for this bot run
        self.profit: float = 0
        # a wallet is for the coins we hold
        self.wallet: List = []
        # the list of tickers and the config for each one, in terms of
        # BUY_AT_PERCENTAGE, SELL_AT_PERCENTAGE, etc...
        self.tickers: dict = dict(config["TICKERS"])
        # running mode for the bot [BACKTESTING, LIVE, TESTNET]
        self.mode: str = config["MODE"]
        # Binance trading fee for each buy/sell trade, in percentage points
        self.trading_fee: float = float(config["TRADING_FEE"])
        # Enable/Disable debug, debug information gets logged in debug.log
        self.debug: bool = bool(config["DEBUG"])
        # maximum number of coins that the bot will hold in its wallet.
        self.max_coins: int = int(config["MAX_COINS"])
        # which pair to use [USDT|BUSD|BNB|BTC|ETH...]
        self.pairing: str = config["PAIRING"]
        # total amount of fees paid during this bot run
        self.fees: float = 0
        # wether to clean coin stats at boot, if our tickers config doesn't
        # chane for example a reload, we might want to keep the history we have
        # related to the max, min prices recorded for our coins as those will
        # influence our next buy.
        self.clear_coin_stats_at_boot: bool = bool(
            config["CLEAR_COIN_STATS_AT_BOOT"]
        )
        # as above but after each buy
        self.clean_coin_stats_at_sale: bool = bool(
            config["CLEAR_COIN_STATS_AT_SALE"]
        )
        # which bot strategy to use as set in the config file
        self.strategy: str = config["STRATEGY"]
        # if a coin drops in price shortly after reaching its target sale
        # percentage, we force a quick sale and ignore the
        # TRAIL_TARGET_SELL_PERCENTAGE values
        self.sell_as_soon_it_drops: bool = bool(
            config["SELL_AS_SOON_IT_DROPS"]
        )
        # the config filename
        self.config_file: str = config_file
        # a dictionary to old the previous prices available from binance for
        # our coins. Used in logmode to prevent the bot from writing a new
        # price.log line if the price hasn't changed. Common with low volume
        # coins. This reduces our logfiles size and our backtesting times.
        self.oldprice: Dict[str, float] = {}
        # the full config as a dict
        self.cfg = config
        # whether to enable pump and dump checks while the bot is evaluating
        # buy conditions for a coin
        self.enable_pump_and_dump_checks: bool = config.get(
            "ENABLE_PUMP_AND_DUMP_CHECKS", True
        )
        # check if we are looking at a new coin
        self.enable_new_listing_checks: bool = config.get(
            "ENABLE_NEW_LISTING_CHECKS", True
        )
        # disable buying a new coin if this coin is newer than 31 days
        self.enable_new_listing_checks_age_in_days: int = config.get(
            "ENABLE_NEW_LISTING_CHECKS_AGE_IN_DAYS", 31
        )
        # stops the bot as soon we hit a STOP_LOSS. If we are still holding
        # coins, those remain in our wallet.
        # Typically used when MAX_COINS = 1
        self.stop_bot_on_loss: bool = config.get("STOP_BOT_ON_LOSS", False)
        # stops the bot as soon we hit a STALE. If we are still holding
        # coins, those remain in our wallet.
        # Mostly used for quitting a backtesting session early
        self.stop_bot_on_stale: bool = config.get("STOP_BOT_ON_STALE", False)
        # indicates where we found a .stop flag file
        self.stop_flag: bool = False
        # set by the bot so to quit safely as soon as possible.
        # used by STOP_BOT_ON_LOSS checks
        self.quit: bool = False
        # define if we want to use MARKET or LIMIT orders
        self.order_type: str = config.get("ORDER_TYPE", "MARKET")

    def extract_order_data(self, order_details, coin) -> Dict[str, Any]:
        """calculate average price and volume for a buy order"""

        # Each order will be fullfilled by different traders, and made of
        # different amounts and prices. Here we calculate the average over all
        # those different lines in our order.

        total: float = 0
        qty: float = 0

        logging.debug(f"{coin.symbol} -> order_dtails:{order_details}")

        for k in order_details["fills"]:
            item_price = float(k["price"])
            item_qty = float(k["qty"])

            total += item_price * item_qty
            qty += item_qty

        avg = total / qty

        volume = float(self.calculate_volume_size(coin))
        logging.debug(f"{coin.symbol} -> volume:{volume} avgPrice:{avg}")

        return {
            "avgPrice": float(avg),
            "volume": float(volume),
        }

    def run_strategy(self, coin) -> None:
        """runs a specific strategy against a coin"""

        # runs our choosen strategy, here we aim to quit as soon as possible
        # reducing processing time. So we stop validating conditions as soon
        # they are not possible to occur in the chain that follows.

        # the bot won't act on coins not listed on its config.
        if coin.symbol not in self.tickers:
            return

        # skip any coins that were involved in a recent STOP_LOSS.
        if self.coins[coin.symbol].naughty:
            return

        # first attempt to sell the coin, in order to free the wallet for the
        # next coin run_strategy run.
        if self.wallet:
            self.check_for_sale_conditions(coin)

        # is this a new coin?
        if self.enable_new_listing_checks:
            if coin.new_listing(self.enable_new_listing_checks_age_in_days):
                return

        # our wallet is already full
        if len(self.wallet) == self.max_coins:
            return

        # has the current price been influenced by a pump and dump?
        if self.enable_pump_and_dump_checks:
            if coin.check_for_pump_and_dump():
                return

        # all our pre-conditions played out, now run the buy_strategy
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

    def place_sell_order(self, coin):
        """places a limit/market sell order"""
        try:
            now = udatetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
            if self.order_type == "LIMIT":
                order_book = self.client.get_order_book(symbol=coin.symbol)
                logging.debug(f"order_book: {order_book}")
                try:
                    bid, _ = order_book["bids"][0]
                except IndexError as error:
                    # if the order_book is empty we'll get an exception here
                    logging.debug(f"{coin.symbol} {error}")
                    return False
                logging.debug(f"bid: {bid}")
                logging.info(
                    f"{now}: {coin.symbol} [SELLING] {coin.volume} of "
                    + f"{coin.symbol} at LIMIT {bid}"
                )
                order_details = self.client.create_order(
                    symbol=coin.symbol,
                    side="SELL",
                    type="LIMIT",
                    quantity=coin.volume,
                    timeInForce="FOK",
                    price=bid,
                )
            else:
                logging.info(
                    f"{now}: {coin.symbol} [SELLING] {coin.volume} of "
                    + f"{coin.symbol} at MARKET {coin.price}"
                )
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
            return False

        while True:
            try:
                order_status = self.client.get_order(
                    symbol=coin.symbol, orderId=order_details["orderId"]
                )
                logging.debug(order_status)
                if order_status["status"] == "FILLED":
                    break

                if order_status["status"] == "EXPIRED":
                    now = udatetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
                    logging.info(
                        f"{now}: {coin.symbol} [EXPIRED_LIMIT_SELL] "
                        + f"order for {coin.volume} of {coin.symbol} "
                        + f"at {bid}"
                    )
                    return False
                sleep(0.1)
            except BinanceAPIException as error_msg:
                logging.warning(error_msg)

        logging.debug(order_status)

        if self.order_type == "LIMIT":
            # calculate how much we got based on the total lines in our order
            coin.price = float(order_status["price"])
            coin.volume = float(order_status["executedQty"])
        else:
            orders = self.client.get_all_orders(symbol=coin.symbol, limit=1)
            logging.debug(orders)
            # calculate how much we got based on the total lines in our order
            coin.price = self.extract_order_data(order_details, coin)[
                "avgPrice"
            ]
            # retrieve the total number of units for this coin
            coin.volume = self.extract_order_data(order_details, coin)[
                "volume"
            ]

        # and give this coin a new fresh date based on our recent actions
        coin.date = float(udatetime.now().timestamp())
        return True

    def place_buy_order(self, coin, volume):
        """places a limit/market buy order"""
        try:
            now = udatetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
            # TODO: add the ability to place a order from a specific position
            # within the order book.
            if self.order_type == "LIMIT":
                order_book = self.client.get_order_book(symbol=coin.symbol)
                logging.debug(f"order_book: {order_book}")
                try:
                    ask, _ = order_book["asks"][0]
                except IndexError as error:
                    # if the order_book is empty we'll get an exception here
                    logging.debug(f"{coin.symbol} {error}")
                    return False
                logging.debug(f"ask: {ask}")
                logging.info(
                    f"{now}: {coin.symbol} [BUYING] {volume} of "
                    + f"{coin.symbol} at LIMIT {ask}"
                )
                order_details = self.client.create_order(
                    symbol=coin.symbol,
                    side="BUY",
                    type="LIMIT",
                    quantity=volume,
                    timeInForce="FOK",
                    price=ask,
                )
            else:
                logging.info(
                    f"{now}: {coin.symbol} [BUYING] {volume} of "
                    + f"{coin.symbol} at MARKET {coin.price}"
                )
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
            return False
        logging.debug(order_details)

        while True:
            try:
                order_status = self.client.get_order(
                    symbol=coin.symbol, orderId=order_details["orderId"]
                )
                logging.debug(order_status)
                if order_status["status"] == "FILLED":
                    break

                now = udatetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")

                if order_status["status"] == "EXPIRED":
                    if self.order_type == "LIMIT":
                        price = ask
                    else:
                        price = coin.price
                    logging.info(
                        " ".join(
                            [
                                f"{now}: {coin.symbol}",
                                f"[EXPIRED_{self.order_type}_BUY] order",
                                f" for {volume} of {coin.symbol} ",
                                f"at {price}",
                            ]
                        )
                    )
                    return False
                sleep(0.1)

            except BinanceAPIException as error_msg:
                logging.warning(error_msg)
        logging.debug(order_status)

        if self.order_type == "LIMIT":
            # our order will have been fullfilled by different traders,
            # find out the average price we paid accross all these sales.
            coin.bought_at = float(order_status["price"])
            # retrieve the total number of units for this coin
            coin.volume = float(order_status["executedQty"])
        else:
            orders = self.client.get_all_orders(symbol=coin.symbol, limit=1)
            logging.debug(orders)
            # our order will have been fullfilled by different traders,
            # find out the average price we paid accross all these sales.
            coin.bought_at = self.extract_order_data(order_details, coin)[
                "avgPrice"
            ]
            # retrieve the total number of units for this coin
            coin.volume = self.extract_order_data(order_details, coin)[
                "volume"
            ]
        return True

    def buy_coin(self, coin) -> bool:
        """calls Binance to buy a coin"""

        # quit early if we already hold this coin in our wallet
        if coin.symbol in self.wallet:
            return False

        # quit early if our wallet is full
        if len(self.wallet) == self.max_coins:
            return False

        # quit early if this coin was involved in a recent STOP_LOSS
        if coin.naughty:
            return False

        # calculate how many units of this coin we can afford based on our
        # investment share.
        volume = float(self.calculate_volume_size(coin))

        # we never place binance orders in backtesting mode.
        if self.mode in ["testnet", "live"]:
            if not self.place_buy_order(coin, volume):
                return False

            # calculate the current value
            coin.value = float(coin.bought_at) * float(coin.volume)
            # and the total cost which will match the value at this moment
            coin.cost = coin.value

        # in backtesting we tipically assume the price paid is the price listed
        # in our price.log file.
        if self.mode in ["backtesting"]:
            coin.bought_at = float(coin.price)
            coin.volume = volume
            coin.value = float(coin.bought_at) * float(coin.volume)
            coin.cost = float(coin.bought_at) * float(coin.volume)

        # initialize the 'age' counter for the coin
        coin.holding_time = 1
        # and append this coin to our wallet
        self.wallet.append(coin.symbol)
        # mark it as HOLD, so that the bot know we own it
        coin.status = "HOLD"
        # and record the highest price recorded since buying this coin
        coin.tip = coin.price
        # as well as when we bought it
        coin.bought_date = coin.date

        # TODO: our logging message could use some love below
        s_value = (
            percent(coin.trail_target_sell_percentage, coin.sell_at_percentage)
            - 100
        )
        logging.info(
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

        # this gets noisy quickly
        self.log_debug_coin(coin)
        return True

    def sell_coin(self, coin) -> bool:
        """calls Binance to sell a coin"""

        # if we don't own this coin, then there's nothing more to do here
        if coin.symbol not in self.wallet:
            return False

        # in backtesting mode, we never place sell orders on binance
        if self.mode in ["testnet", "live"]:
            if not self.place_sell_order(coin):
                return False

        # finally calculate the value at sale and the total profit
        coin.value = float(float(coin.volume) * float(coin.price))
        coin.profit = float(float(coin.value) - float(coin.cost))

        if coin.profit < 0:
            word = "LS"
        else:
            word = "PRF"

        message = " ".join(
            [
                f"{c_from_timestamp(coin.date)}: {coin.symbol} "
                f"[SOLD_BY_{coin.status}]",
                f"A:{coin.holding_time}s",
                f"U:{coin.volume} P:{coin.price} T:{coin.value}",
                f"{word}:{coin.profit:.3f}",
                f"BP:{coin.bought_at}",
                f"SP:{coin.bought_at * coin.sell_at_percentage /100}",
                f"TP:{100 - (coin.bought_at / coin.price * 100):.2f}%",
                f"SL:{coin.bought_at * coin.stop_loss_at_percentage/100}",
                f"S:+{percent(coin.trail_target_sell_percentage,coin.sell_at_percentage) - 100:.3f}%",  # pylint: disable=line-too-long
                f"TTS:-{(100 - coin.trail_target_sell_percentage):.3f}%",
                f"LP:{coin.min}",
                f"LP:{coin.min}(-{100 - ((coin.min/coin.max) * 100):.2f}%)",
                f"({len(self.wallet)}/{self.max_coins}) ",
            ]
        )

        # raise an warning if we happen to have made a LOSS on our trade
        if coin.profit < 0 or coin.holding_time > coin.hard_limit_holding_time:
            logging.warning(message)
        else:
            logging.info(message)

        # drop the coin from our wallet, we've sold it
        self.wallet.remove(coin.symbol)
        # update the total profit for this bot run
        self.update_bot_profit(coin)
        # and the total amount we now have available to invest.
        # this could have gone up, or down, depending on wether we made a
        # profit or a loss.
        self.update_investment()
        # and clear the status for this coin
        coin.status = ""
        # as well the data for this and all coins, if applicable.
        # this forces the bot to reset when checking for buy conditions from now
        # on, preventing it from acting on coins that have been marked as
        # TARGET_DIP while we holding this coin, and could now be automatically
        # triggered to buy in the next buy check run.
        # we may not want to do this, as the price might have moved further than
        # we wanted and no longer be a suitable buy.
        self.clear_coin_stats(coin)
        self.clear_all_coins_stats()

        exposure = self.calculates_exposure()
        logging.info(
            f"{c_from_timestamp(coin.date)}: INVESTMENT: {self.investment} "
            + f"PROFIT: {self.profit} EXPOSURE: {exposure} WALLET: "
            + f"({len(self.wallet)}/{self.max_coins}) {self.wallet}"
        )
        return True

    @lru_cache()
    @retry(wait=wait_exponential(multiplier=1, max=10))
    def get_step_size(self, symbol: str) -> str:
        """retrieves and caches the decimal step size for a coin in binance"""

        # each coin in binance uses a number of decimal points, these can vary
        # greatly between them. We need this information when placing and order
        # on a coin. However this requires us to query binance to retrieve this
        # information. This is fine while in LIVE or TESTNET mode as the bot
        # doesn't perform that many buys. But in backtesting mode we can issue
        # a very large number of API calls and be quickly blacklisted.
        # We avoid having to poke the binance api twice for the same information
        # by saving it locally on disk. This way it will became available for
        # future backtestin runs.
        f_path = f"cache/{symbol}.precision"
        if self.mode == "backtesting" and exists(f_path):
            with open(f_path, "r") as f:
                info = json.load(f)
        else:
            try:
                info = self.client.get_symbol_info(symbol)
            except BinanceAPIException as error_msg:
                logging.error(error_msg)
                return str(-1)

        step_size = info["filters"][2]["stepSize"]

        if self.mode == "backtesting" and not exists(f_path):
            with open(f_path, "w") as f:
                f.write(json.dumps(info))

        return step_size

    def calculate_volume_size(self, coin) -> float:
        """calculates the amount of coin we are to buy"""

        # calculates the number of units we are about to buy based on the number
        # of decimal points used, the share of the investment and the price
        step_size = self.get_step_size(coin.symbol)

        volume = float(
            floor_value(
                (self.investment / self.max_coins) / coin.price, step_size
            )
        )
        if self.debug:
            logging.debug(
                f"[{coin.symbol}] investment:{self.investment}{self.pairing} "
                + f"vol:{volume} price:{coin.price} step_size:{step_size}"
            )
        return volume

    @retry(wait=wait_exponential(multiplier=1, max=90))
    def get_binance_prices(self) -> List[Dict[str, str]]:
        """gets the list of all binance coin prices"""
        return self.client.get_all_tickers()

    def write_log(self, symbol: str, price: str) -> None:
        """updates the price.log file with latest prices"""

        # only write logs if price changed, for coins which price doesn't
        # change often such as low volume coins, we keep track of the old price
        # and check it against the latest value. If the price hasn't changed,
        # we don't record it in the price.log file. This greatly reduces the
        # size of the log, and the backtesting time to process these.
        if symbol not in self.oldprice:
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

        if symbol not in self.coins:
            market_price = float(binance_data["price"])
        else:
            if self.coins[symbol].status == "TARGET_DIP":
                # when looking for a buy/sell position, we can look  at a
                # position within the order book and not retrive the first one
                order_book = self.client.get_order_book(symbol=symbol)
                try:
                    market_price = float(order_book["asks"][0][0])
                except IndexError as error:
                    # if the order_book is empty we'll get an exception here
                    logging.debug(f"{symbol} {error}")
                    return

                logging.debug(
                    f"{symbol} in TARGET_DIP using order_book price:"
                    + f" {market_price}"
                )
            else:
                market_price = float(binance_data["price"])

        # add every single coin to our coins dict, even if they're coins not
        # listed in our tickers file as the bot will use this info to record
        # the price.logs as well as cache/ data.
        #
        # init this coin if we are coming across it for the first time
        if symbol not in self.coins:
            self.coins[symbol] = Coin(
                symbol,
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
            # fetch all the available klines for this coin, for the last
            # 60min, 24h, and 1000 days
            self.load_klines_for_coin(self.coins[symbol])
        else:
            # or simply update the coin with the latest price data
            self.coins[symbol].update(
                udatetime.now().timestamp(), market_price
            )

    def process_coins(self) -> None:
        """processes all the prices returned by binance"""
        # look for coins that are ready for buying, or selling
        for binance_data in self.get_binance_prices():
            coin_symbol = binance_data["symbol"]
            price = binance_data["price"]

            # we write the price.logs in TESTNET mode as we want to be able
            # to debug for issues while developing the bot.
            if self.mode in ["logmode", "testnet"]:
                self.write_log(coin_symbol, price)

            if self.mode not in ["live", "backtesting", "testnet"]:
                continue

            # TODO: revisit this, as this function is only called in
            # live, testnet and logmode. And the within this function, we
            # expect to process all the coins.
            # don't process any coins which we don't have in our config
            if coin_symbol not in self.tickers:
                continue

            # TODO: revisit this as the function below expects to process all
            # the coins
            self.init_or_update_coin(binance_data)

            # if a coin has been blocked due to a stop_loss, we want to make
            # sure we reset the coin stats for the duration of the ban and
            # not just when the stop-loss event happened.
            # TODO: we are reseting the stats on every iteration while this
            # coin is in naughty state, look on how to avoid doing this.
            if self.coins[coin_symbol].naughty:
                self.clear_coin_stats(self.coins[coin_symbol])

            # and run the strategy
            self.run_strategy(self.coins[coin_symbol])

            if coin_symbol in self.wallet:
                self.log_debug_coin(self.coins[coin_symbol])

    def stop_loss(self, coin: Coin) -> bool:
        """checks for possible loss on a coin"""
        # oh we already own this one, lets check prices
        # deal with STOP_LOSS
        if coin.price < percent(coin.stop_loss_at_percentage, coin.bought_at):
            if coin.status != "STOP_LOSS":
                logging.info(
                    f"{c_from_timestamp(coin.date)}: {coin.symbol} "
                    + f"[{coin.status}] -> [STOP_LOSS]"
                )
            coin.status = "STOP_LOSS"
            if not self.sell_coin(coin):
                return False

            self.losses = self.losses + 1
            # places the coin in the naughty corner by setting the naughty_date
            # NAUGHTY_TIMEOUT will kick in from now on
            coin.naughty_date = (
                coin.date
            )  # pylint: disable=attribute-defined-outside-init
            self.clear_coin_stats(coin)

            # and marks it as NAUGHTY
            coin.naughty = (
                True  # pylint: disable=attribute-defined-outside-init
            )
            if self.stop_bot_on_loss:
                # STOP_BOT_ON_LOSS is set, set a STOP flag to stop the bot
                self.quit = True
            return True
        return False

    def coin_gone_up_and_dropped(self, coin) -> bool:
        """checks for a possible drop in price in a coin we hold"""
        # when we have reached the TARGET_SELL and a coin drops in price
        # below the SELL_AT_PERCENTAGE price we sell the coin immediately
        # if SELL_AS_SOON_IT_DROPS is set
        if (
            coin.status
            in [
                "TARGET_SELL",
                "GONE_UP_AND_DROPPED",
            ]
            and coin.price < percent(coin.sell_at_percentage, coin.bought_at)
        ):
            coin.status = "GONE_UP_AND_DROPPED"
            logging.info(
                f"{c_from_timestamp(coin.date)}: {coin.symbol} "
                + "[TARGET_SELL] -> [GONE_UP_AND_DROPPED]"
            )
            if not self.sell_coin(coin):
                return False
            self.wins = self.wins + 1
            return True
        return False

    def possible_sale(self, coin: Coin) -> bool:
        """checks for a possible sale of a coin we hold"""

        # we let a coin enter the TARGET_SELL status, and then we monitor
        # its price recording the maximum value as the 'tip'.
        # when we go below that 'tip' value by our TRAIL_TARGET_SELL_PERCENTAGE
        # we sell our coin.

        # bail out early if we shouldn't be here
        if coin.status != "TARGET_SELL":
            return False

        # while in debug mode, it is useful to read the latest price on a coin
        # that we're looking to sell
        if coin.price != coin.last:
            self.log_debug_coin(coin)

        # has price has gone down since last time we checked?
        if coin.price < coin.last:

            # and has it gone the below the 'tip' more than our
            # TRAIL_TARGET_SELL_PERCENTAGE ?
            if coin.price < percent(
                coin.trail_target_sell_percentage, coin.tip
            ):
                # let's sell it then
                if not self.sell_coin(coin):
                    return False
                self.wins = self.wins + 1
                return True
        return False

    def past_hard_limit(self, coin: Coin) -> bool:
        """checks for a possible stale coin we hold"""
        # for every coin we hold, we give it a lifespan, this is set as the
        # HARD_LIMIT_HOLDING_TIME in seconds. if we have been holding a coin
        # for longer than that amount of time, we force a sale, regardless of
        # its current value.

        # allow a TARGET_SELL to run
        if coin.status == "TARGET_SELL":
            return False

        if coin.holding_time > coin.hard_limit_holding_time:
            coin.status = "STALE"
            if not self.sell_coin(coin):
                return False
            self.stales = self.stales + 1

            # any coins that enter a STOP_LOSS or a STALE get added to the
            # naughty list, so that we prevent the bot from buying this coin
            # again for a specified period of time. AKA NAUGHTY_TIMEOUT
            coin.naughty = True
            coin.naughty_date = coin.date
            # and set the chill-out period as we've defined in our config.
            coin.naughty_timeout = int(
                self.tickers[coin.symbol]["NAUGHTY_TIMEOUT"]
            )
            if self.stop_bot_on_stale:
                # STOP_BOT_ON_STALE is set, set a STOP flag to stop the bot
                self.quit = True
            return True
        return False

    def past_soft_limit(self, coin: Coin) -> bool:
        """checks for if we should lower our sale percentages based on age"""

        # For any coins the bot holds, we start by looking to sell them past
        # the SELL_AT_PERCENTAGE profit, but to avoid being stuck forever with
        # a coin that doesn't move in price, we have a hard limit in time
        # defined in HARD_LIMIT_HOLDING_TIME where we force the sale of the coin
        # Between the the time we buy and our hard limit, we have another
        # parameter that we can use called SOFT_LIMIT_HOLDING_TIME.
        # This sets the number in seconds since we bought our coin, for when
        # the bot start reducing the value in SELL_AT_PERCENTAGE every second
        # until it reaches the HARD_LIMIT_HOLDING_TIME.
        # This improves ours chances of selling a coin for which our
        # SELL_AT_PERCENTAGE was just a bit too high, and the bot downgrades
        # its expectactions by meeting half-way.

        # allow a TARGET_SELL to run
        if coin.status == "TARGET_SELL":
            return False

        # This coin is past our soft limit
        # we apply a sliding window to the buy profit
        # we essentially calculate the the time left until we get to the
        # HARD_LIMIT_HOLDING_TIME as a percentage and use it that value as
        # a percentage of the total SELL_AT_PERCENTAGE value.
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
            )

            coin.sell_at_percentage = add_100(
                percent(ttl, self.tickers[coin.symbol]["SELL_AT_PERCENTAGE"])
            )

            # make sure we never set the SELL_AT_PERCENTAGE below what we've
            # had to pay in fees. It's quite likely however that if we didn't
            # sell our coin by now, we are likely to hit HARD_LIMIT_HOLDING_TIME
            if coin.sell_at_percentage < add_100(2 * self.trading_fee):
                coin.sell_at_percentage = add_100(2 * self.trading_fee)

            # and also reduce the TRAIL_TARGET_SELL_PERCENTAGE in the same
            # way we reduced our SELL_AT_PERCENTAGE.
            # We're fine with this one going close to 0.
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
                f"{c_from_timestamp(coin.date)} {coin.symbol} "
                + f"{coin.status} "
                + f"age:{coin.holding_time} "
                + f"now:{coin.price} "
                + f"bought:{coin.bought_at} "
                + f"sell:{(coin.sell_at_percentage - 100):.4f}% "
                + "trail_target_sell:"
                + f"{(coin.trail_target_sell_percentage - 100):.4f}% "
                + f"LP:{coin.min:.3f} "
            )
            logging.debug(f"{coin.symbol} : price:{coin.price}")
            logging.debug(f"{coin.symbol} : min:{coin.min}")
            logging.debug(f"{coin.symbol} : max:{coin.max}")
            logging.debug(f"{coin.symbol} : lowest['m']:{coin.lowest['m']}")
            logging.debug(f"{coin.symbol} : lowest['h']:{coin.lowest['h']}")
            logging.debug(f"{coin.symbol} : lowest['d']:{coin.lowest['d']}")
            logging.debug(
                f"{coin.symbol} : averages['m']:{coin.averages['m']}"
            )
            logging.debug(
                f"{coin.symbol} : averages['h']:{coin.averages['h']}"
            )
            logging.debug(
                f"{coin.symbol} : averages['d']:{coin.averages['d']}"
            )
            logging.debug(f"{coin.symbol} : highest['m']:{coin.highest['m']}")
            logging.debug(f"{coin.symbol} : highest['h']:{coin.highest['h']}")
            logging.debug(f"{coin.symbol} : highest['d']:{coin.highest['d']}")

    def clear_all_coins_stats(self) -> None:
        """clear important coin stats such as max, min price on all coins"""

        # after each SALE we reset all the stats we have on the data the
        # bot holds for prices, such as the max, min values for each coin.
        # This essentially forces the bot to monitor for changes in price since
        # the last sale, instead of for example an all time high value.
        # if for example, we were to say buy BTC at -10% and sell at +2%
        # and we last sold BTC at 20K.
        # when CLEAR_COIN_STATS_AT_SALE is set, the bot will look to only buy
        # BTC when the price is below 18K.
        # if this flag is not set, and the all time high while the bot was running
        # was considerably higher like 40K, the bot would keep on buying BTC
        # for as long BTC was below 36K.
        if self.clean_coin_stats_at_sale:
            for coin in self.coins:
                if coin not in self.wallet:
                    self.clear_coin_stats(self.coins[coin])

    def clear_coin_stats(self, coin: Coin) -> None:
        """clear important coin stats such as max, min price for a coin"""

        # This where we reset all coin prices when CLEAR_COIN_STATS_AT_SALE
        # is set.
        # We reset the values for :
        # BUY, SELL, STOP_LOSS, TRAIL_TARGET_SELL_PERCENTAGE, TRAIL_RECOVERY_PERCENTAGE
        # as well as the dip, tip and min, max prices.
        # The bot manipulates some of these values when the coin has gone
        # past the SOFT_LIMIT_HOLDING_TIME. So we reset them back to the config
        # values here.

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
        coin.volume = float(0)
        coin.value = float(0)

        # reset the min, max prices so that the bot won't look at all time high
        # and instead use the values since the last sale.
        if self.clean_coin_stats_at_sale:
            coin.min = coin.price
            coin.max = coin.price

    def save_coins(self) -> None:
        """saves coins and wallet to a local pickle file"""

        # in LIVE and TESTNET mode we save our local self.coins and self.wallet
        # objects to a local file on disk, so that we can pick from where we
        # left next time we start the bot.

        for statefile in ["state/coins.pickle", "state/wallet.pickle"]:
            if exists(statefile):
                with open(statefile, "rb") as f:
                    # as these files are important to the bot, we keep a
                    # backup file in case there is a failure that could
                    # corrupt the live .pickle files.
                    # in case or corruption, simply copy the .backup files over
                    # the .pickle files.
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

        # in save_coins() we save the current state of our wallet and coins
        # to pickle file on disk. Here we soak up those files after a boot
        # and update our bot dictionaries with the data on them.
        # Overriding and deleting any data we might not want to keep.

        # TODO: look into a fallback mechanism to the .backup files if
        # the .pickle are corrupted.

        if exists("state/coins.pickle"):
            logging.warning("found coins.pickle, loading coins")
            with open("state/coins.pickle", "rb") as f:
                self.coins = pickle.load(f)  # nosec
        if exists("state/wallet.pickle"):
            logging.warning("found wallet.pickle, loading wallet")
            with open("state/wallet.pickle", "rb") as f:
                self.wallet = pickle.load(f)  # nosec
            logging.warning(f"wallet contains {self.wallet}")

        # sync our coins state with the list of coins we want to use.
        # but keep using coins we currently have on our wallet
        coins_to_remove = []
        # TODO: do we want to remove these coins, or should we just let the bot
        # keep on updating their stats, even if we don't buy them ?
        # there are places in the codebase where this is expected.
        for coin in self.coins:
            if coin not in self.tickers and coin not in self.wallet:
                coins_to_remove.append(coin)

        for coin in coins_to_remove:
            self.coins.pop(coin)

        # finally apply the current settings in the config file
        symbols = " ".join(self.coins.keys())
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
            self.coins[symbol].klines_trend_period = str(
                self.tickers[symbol]["KLINES_TREND_PERIOD"]
            )
            self.coins[symbol].klines_slice_percentage_change = float(
                self.tickers[symbol]["KLINES_SLICE_PERCENTAGE_CHANGE"]
            )

            # deal with missing coin properties, types after a bot upgrade
            # the earlier versions of this bot didn't contain or used all the
            # existing properties used today, the bot would fail as attempting
            # to consume them. Here we make sure we can safely upgrade from
            # a version missing those properties by initializing them if they
            # don't exist.
            #
            # TODO: consider deprecating this as for this to happen today,
            # someone would be jumping bot versions considerably
            if isinstance(self.coins[symbol].date, str):
                self.coins[symbol].date = float(
                    datetime.fromisoformat(
                        str(self.coins[symbol].date)
                    ).timestamp()
                )
            if "naughty" not in dir(self.coins[symbol]):
                if self.coins[symbol].naughty_timeout != 0:
                    self.coins[symbol].naughty = True
                    self.coins[symbol].naughty_date = (
                        self.coins[symbol].naughty_date
                        - self.coins[symbol].naughty_timeout
                    )
                else:
                    self.coins[symbol].naughty = False
                    self.coins[symbol].naughty_date = None  # type: ignore

            if "bought_date" not in dir(self.coins[symbol]):
                if symbol in self.wallet:
                    self.coins[symbol].bought_date = (
                        self.coins[symbol].date
                        - self.coins[symbol].holding_time
                    )
                else:
                    self.coins[symbol].bought_date = None  # type: ignore

            if "lowest" not in dir(self.coins[symbol]):
                self.coins[symbol].lowest = {"m": [], "h": [], "d": []}

            if "averages" not in dir(self.coins[symbol]):
                self.coins[symbol].averages = {
                    "s": [],
                    "m": [],
                    "h": [],
                    "d": [],
                }

            if "highest" not in dir(self.coins[symbol]):
                self.coins[symbol].highest = {"m": [], "h": [], "d": []}

            self.coins[symbol].naughty_timeout = int(
                self.tickers[symbol]["NAUGHTY_TIMEOUT"]
            )

        # log some info on the coins in our wallet at boot
        if self.wallet:
            logging.info("Wallet contains:")
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
                logging.info(
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
            # make sure we unset .quit if its set from a previous run
            self.quit = False

    def check_for_sale_conditions(self, coin: Coin) -> Tuple[bool, str]:
        """checks for multiple sale conditions for a coin"""

        # return early if no work left to do
        if coin.symbol not in self.wallet:
            return (False, "NOT_IN_WALLET")

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

        # when running in LIVE or TESTNET mode we end up here.
        #
        # first load all our state from disk
        self.load_coins()
        # reset all coin price stats if CLEAR_COIN_STATS_AT_BOOT is set.
        # this forces the bot to treat boot as a new time window to monitor
        # for prices.
        if self.clear_coin_stats_at_boot:
            logging.warning("About the clear all coin stats...")
            logging.warning("CTRL-C to cancel in the next 30 seconds")
            sleep(30)
            self.clear_all_coins_stats()

        while True:
            self.process_coins()
            # saves all coin and wallet data to disk
            self.save_coins()
            self.wait()
            if exists(".stop") or self.quit:
                logging.warning(".stop flag found. Stopping bot.")
                return

    def logmode(self) -> None:
        """the bot LogMode main loop"""
        while True:
            # TODO: should we extract write_log from process_coins()?
            self.process_coins()
            self.wait()

    def split_logline(self, line: str) -> Tuple:
        """splits a log line into symbol, date, price"""

        parts = line.split(" ", maxsplit=4)
        symbol = parts[2]
        # skip processing the line if we don't care about this coin
        if symbol not in self.tickers:
            return (False, False, False)

        # skip processing the line we hold max coins and this coins is not in
        # our wallet. Only process lines containing the coin in our wallets
        # until we sell or drop those.
        if len(self.wallet) >= self.max_coins:
            if symbol not in self.wallet:
                return (False, False, False)
        day = " ".join(parts[0:2])
        try:
            # datetime is very slow, discard the .microseconds and fetch a
            # cached pre-calculated unix epoch timestamp
            day = day.split(".", maxsplit=1)[0]
            date = c_date_from(day)
        except ValueError:
            date = c_date_from(day)

        try:
            # ocasionally binance returns rubbish
            # we just skip it
            market_price = float(parts[3])
        except ValueError:
            return (False, False, False)

        return (symbol, date, market_price)

    def check_for_delisted_coin(self, symbol: str) -> bool:
        """checks if a coin has been delisted"""

        # when we process old logfiles, we might encounter symbols that are
        # no longer available on binance, these will not return any klines
        # data from the API. For those we are better to remove them from our
        # tickers list as we don't want to process them.

        if not self.load_klines_for_coin(self.coins[symbol]):
            # got no klines data on this coin, probably delisted
            # will remove this coin from our ticker list
            if symbol not in self.wallet:
                logging.warning(f"removing {symbol} from tickers")
                del self.coins[symbol]
                del self.tickers[symbol]
                return True
        return False

    def process_line(self, line: str) -> None:
        """processes a backlog line"""

        if self.quit:  # when told to quit, just go nicely
            return

        # skip processing the line if it doesn't not match our PAIRING settings
        if self.pairing not in line:
            return

        symbol, date, market_price = self.split_logline(line)
        # symbol will be False if we fail to process the line fields
        if not symbol:
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
            if self.check_for_delisted_coin(symbol):
                return
        else:
            # implements a PAUSE_FOR pause while reading from
            # our price logs.
            # we essentially skip a number of iterations between
            # reads, causing a similar effect if we were only
            # probing prices every PAUSE_FOR seconds
            # last_read_date contains the timestamp of the last time we read
            # a price record for this particular coin.
            if self.coins[symbol].last_read_date + self.pause > date:
                return
            self.coins[symbol].last_read_date = date

            self.coins[symbol].update(date, market_price)

        # and finally run through the strategy for our coin.
        self.run_strategy(self.coins[symbol])

    def backtest_logfile(self, price_log: str) -> None:
        """processes one price.log file for backtesting"""

        # when told to quit, do it nicely
        if self.quit:
            return

        logging.info(f"backtesting: {price_log}")
        logging.info(f"wallet: {self.wallet}")
        logging.info(f"exposure: {self.calculates_exposure()}")
        try:
            # we support .lz4 and .gz for our price.log files.
            # gzip -3 files provide the fastest decompression times we were able
            # to measure.
            if price_log.endswith(".lz4"):
                f = lz4open(price_log, mode="rt")
            else:
                f = gzip.open(price_log, "rt")
            while True:
                # reading a chunk of lines like this speeds up backtesting
                # by a large amount.
                if self.quit:
                    break
                next_n_lines = list(islice(f, 4 * 1024 * 1024))
                if not next_n_lines:
                    break

                # now process each of the lines from our chunk
                for line in next_n_lines:
                    self.process_line(str(line))
            f.close()
        except Exception as error_msg:  # pylint: disable=broad-except
            logging.error("Exception:")
            logging.error(traceback.format_exc())
            # look into better ways to trapping a KeyboardInterrupt
            # and then maybe setting self.quit = True
            if error_msg == "KeyboardInterrupt":
                sys.exit(1)

    def backtesting(self) -> None:
        """the bot Backtesting main loop"""
        logging.info(json.dumps(self.cfg, indent=4))

        self.clear_all_coins_stats()

        # main backtesting block
        for price_log in self.price_logs:
            self.backtest_logfile(price_log)
            if exists(".stop") or self.quit:
                logging.warning(".stop flag found. Stopping bot.")
                break

        # now that we are done, lets record our results
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

    def load_klines_for_coin(self, coin) -> bool:
        """fetches from binance or a local cache klines for a coin"""

        # when we initialise a coin, we pull a bunch of klines from binance
        # for that coin and save it to disk, so that if we need to fetch the
        # exact same data, we can pull it from disk instead.
        # we pull klines for the last 60min, the last 24h, and the last 1000days

        lock = FileLock("state/load_klines.lockfile", timeout=10)
        symbol = coin.symbol
        logging.info(
            f"{c_from_timestamp(coin.date)}: loading klines for: {symbol}"
        )

        api_url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&"

        # this is only to keep the python LSP happy
        timeslice: int = 0
        minutes_before_now: int = 0

        for unit in ["m", "h", "d"]:

            # lets find out the from what date we need to pull klines from while in
            # backtesting mode.
            coin.averages[unit] = []
            unit_values = {
                "m": (60, 1),
                "h": (24, 60),
                # for 'Days' we retrieve 1000 days, binance API default
                "d": (1000, 60 * 24),
            }
            timeslice, minutes_before_now = unit_values[unit]

            backtest_end_time = coin.date
            end_unix_time = int(
                (backtest_end_time - (60 * minutes_before_now)) * 1000
            )

            query = f"{api_url}endTime={end_unix_time}&interval=1{unit}"
            md5_query = md5(query.encode()).hexdigest()  # nosec
            f_path = f"cache/{symbol}.{md5_query}"

            # wrap results in a try call, in case our cached files are corrupt
            # and attempt to pull the required fields from our data.
            try:
                logging.debug(f"(trying to read klines from {f_path}")
                if exists(f_path):
                    with open(f_path, "r") as f:
                        results = json.load(f)
                    # new listed coins will return an empty array
                    # so we bail out early here
                    if not results:
                        logging.debug(f"(empty klines from {f_path}")
                        return True

                _, _, high, low, _, _, closetime, _, _, _, _, _ = results[0]
            except Exception:  # pylint: disable=broad-except
                logging.debug(
                    f"calling binance after failed read from {f_path}"
                )
                with lock:
                    response = requests_with_backoff(query)
                # binance will return a 400 for when a coin doesn't exist
                if response.status_code == 400:
                    logging.warning(f"got a 400 from binance for {symbol}")
                    if self.mode == "backtesting":
                        with open(f_path, "w") as f:
                            f.write(json.dumps([]))
                    return False

                results = response.json()
                # this can be fairly API intensive for a large number of
                # tickers so we cache these calls on disk, each coin, period,
                # start day is md5sum'd and stored on a dedicated file on
                # /cache
                logging.debug(
                    f"writing klines data from binance into {f_path}"
                )
                if self.mode == "backtesting":
                    with open(f_path, "w") as f:
                        f.write(json.dumps(results))

            if self.debug:
                # ocasionally we obtain an invalid results obj here
                # this might need additional debugging (pun intended)
                if results:
                    logging.debug(f"{symbol} : last_{unit}:{results[-1:]}")
                else:
                    logging.debug(f"{symbol} : last_{unit}:{results}")

            # TODO: review this, in what condition would timeslice be 0?
            # could it be from when we were not pulling all the data by default
            # from binance? and only the klines_trend_period ?
            if timeslice != 0:
                lowest = []
                averages = []
                highest = []
                try:
                    # retrieve and calculate the lowest, highest, averages
                    # from the klines data.
                    # we need to transform the dates into consumable timestamps
                    # that work for our bot.
                    for (
                        _,
                        _,
                        high,
                        low,
                        _,
                        _,
                        closetime,
                        _,
                        _,
                        _,
                        _,
                        _,
                    ) in results:
                        date = float(
                            datetime.fromtimestamp(
                                closetime / 1000
                            ).timestamp()
                        )
                        low = float(low)
                        high = float(high)
                        avg = (low + high) / 2

                        lowest.append((date, low))
                        averages.append((date, avg))
                        highest.append((date, high))

                    # finally, populate all the data coin buckets
                    # we gather all the data we collected and only populate
                    # the required number of records we require.
                    # this could possibly be optimized, but at the same time
                    # this only runs the once when we initialise a coin
                    for d, v in lowest[-timeslice:]:
                        coin.lowest[unit].append((d, v))

                    for d, v in averages[-timeslice:]:
                        coin.averages[unit].append((d, v))

                    for d, v in highest[-timeslice:]:
                        coin.highest[unit].append((d, v))
                except ValueError as e:
                    logging.debug(e)
                    logging.debug("caused by results variable with value:")
                    logging.debug(results)

        self.log_debug_coin(coin)
        return True

    def print_final_balance_report(self):
        """calculates and outputs final balance"""

        current_exposure = float(0)
        for item in self.wallet:
            holding = self.coins[item]
            cost = holding.volume * holding.bought_at
            value = holding.volume * holding.price
            age = holding.holding_time
            current_exposure = current_exposure + self.coins[item].profit

            logging.info(f"WALLET: {item} age:{age} cost:{cost} value:{value}")

        logging.info(f"bot profit: {self.profit}")
        logging.info(f"current exposure: {current_exposure:.3f}")
        logging.info(f"total fees: {self.fees:.3f}")
        logging.info(f"final balance: {self.profit + current_exposure:.3f}")
        logging.info(
            f"investment: start: {int(self.initial_investment)} "
            + f"end: {int(self.investment)}"
        )
        logging.info(
            f"wins:{self.wins} losses:{self.losses} "
            + f"stales:{self.stales} holds:{len(self.wallet)}"
        )

    def calculates_exposure(self):
        """calculates current balance"""

        exposure = 0
        for symbol in self.wallet:
            exposure = exposure + self.coins[symbol].profit

        return exposure


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

        PID = getpid()
        c_handler = colorlog.StreamHandler(sys.stdout)
        c_handler.setFormatter(
            colorlog.ColoredFormatter(
                "%(log_color)s[%(levelname)s] %(message)s",
                log_colors={
                    "WARNING": "yellow",
                    "ERROR": "red",
                    "CRITICAL": "red,bg_white",
                },
            )
        )
        c_handler.setLevel(logging.INFO)

        if cfg["DEBUG"]:
            f_handler = logging.FileHandler("log/debug.log")
            f_handler.setLevel(logging.DEBUG)

            logging.basicConfig(
                level=logging.DEBUG,
                format=" ".join(
                    [
                        "(%(asctime)s)",
                        f"({PID})",
                        "(%(lineno)d)",
                        "(%(funcName)s)",
                        "[%(levelname)s]",
                        "%(message)s",
                    ]
                ),
                handlers=[f_handler, c_handler],
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        else:
            logging.basicConfig(
                level=logging.INFO,
                handlers=[c_handler],
            )

        if args.mode == "backtesting":
            client = cached_binance_client(
                secrets["ACCESS_KEY"], secrets["SECRET_KEY"]
            )
        else:
            client = Client(secrets["ACCESS_KEY"], secrets["SECRET_KEY"])

        module = importlib.import_module(f"strategies.{cfg['STRATEGY']}")
        Strategy = getattr(module, "Strategy")

        bot = Strategy(client, args.config, cfg)  # type: ignore

        logging.info(
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

    except Exception:  # pylint: disable=broad-except
        logging.error(traceback.format_exc())
