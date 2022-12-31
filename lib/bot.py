""" Bot Class """

import hashlib
from lib.coin import Coin
from typing import Any, Dict, List, Tuple
from tenacity import retry, wait_exponential
from filelock import SoftFileLock
from binance.exceptions import BinanceAPIException
import yaml
from isal import igzip
import requests
from lz4.frame import open as lz4open
from tenacity import retry, wait_exponential
import json
import udatetime
import logging
import pickle  # nosec
import pprint
import sys
import traceback
from datetime import datetime
from itertools import islice
from os import fsync, unlink
from os.path import basename, exists
from time import sleep
from typing import Any, Dict, List, Tuple


from lib.helpers import (
    add_100,
    c_date_from,
    c_from_timestamp,
    floor_value,
    percent,
    requests_with_backoff,
)


class Bot:
    """Bot Class"""

    def __init__(
        self,
        conn,
        config_file,
        config,
        logs_dir="log",
    ) -> None:
        """Bot object"""

        # Binance API handler
        self.client = conn
        # amount available to the bot to invest as set in the config file
        self.initial_investment: float = float(config["INITIAL_INVESTMENT"])
        # current investment amount
        self.investment: float = float(config["INITIAL_INVESTMENT"])
        # re-investment percentage
        self.re_invest_percentage: float = float(
            config.get("RE_INVEST_PERCENTAGE", 100.0)
        )
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
        # indicates where we found a control/STOP flag file
        self.stop_flag: bool = False
        # set by the bot so to quit safely as soon as possible.
        # used by STOP_BOT_ON_LOSS checks
        self.quit: bool = False
        # define if we want to use MARKET or LIMIT orders
        self.order_type: str = config.get("ORDER_TYPE", "MARKET")
        self.binance_lock = SoftFileLock("state/binance.lock", timeout=90)
        # generate a md5 hash of the tickers config based on the same method
        # used in the config-endpoint-service. We want a hash to be available
        # at boot so that when we first get the config from config-endpoint-service
        # and if the tickers haven't changed match the bot won't assume the
        # tickers or the config have changed.
        # this is needed to prevent SELL_ALL_ON_PULL_CONFIG_CHANGE to sell all
        # the coins at bot startup.
        self.pull_config_md5: str = hashlib.md5(
            (json.dumps(dict(config["TICKERS"]), sort_keys=True)).encode(
                "utf-8"
            )
        ).hexdigest()
        self.pull_config_address: str = config.get("PULL_CONFIG_ADDRESS", "")
        self.sell_all_on_pull_config_change: bool = config.get(
            "SELL_ALL_ON_PULL_CONFIG_CHANGE", False
        )
        self.logs_dir = logs_dir
        self.klines_caching_service_url: str = config.get(
            "KLINES_CACHING_SERVICE_URL", "http://klines:8999"
        )

    def extract_order_data(  # pylint: disable=no-self-use
        self, order_details, coin
    ) -> Dict[str, Any]:
        """calculate average price and volume for a buy order"""

        # Each order will be fullfilled by different traders, and made of
        # different amounts and prices. Here we calculate the average over all
        # those different lines in our order.

        total: float = 0
        qty: float = 0

        logging.debug(f"{coin.symbol} -> order_dtails:{order_details}")

        for k in order_details["fills"]:
            item_price: float = float(k["price"])
            item_qty: float = float(k["qty"])

            total += item_price * item_qty
            qty += item_qty

        avg: float = total / qty

        volume: float = float(self.calculate_volume_size(coin))
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
            self.target_sell(coin)
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
        bid: str = ""
        order_details: str = ""
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
            with open("log/binance.place_sell_order.log", "at") as f:
                f.write(f"{coin.symbol} {coin.date} {self.order_type} ")
                f.write(f"{bid} {coin.volume} {order_details}\n")
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
                with open("log/binance.place_sell_order.log", "at") as f:
                    f.write(f"{coin.symbol} {coin.date} {self.order_type} ")
                    f.write(f"{bid} {coin.volume} {order_details}\n")
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
        with open("log/binance.place_sell_order.log", "at") as f:
            f.write(f"{coin.symbol} {coin.date} {self.order_type} ")
            f.write(f"{bid} {coin.volume} {order_details}\n")
        return True

    def place_buy_order(self, coin, volume):
        """places a limit/market buy order"""
        bid: str = ""
        order_details: str = ""
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
            with open("log/binance.place_buy_order.log", "at") as f:
                f.write(f"{coin.symbol} {coin.date} {self.order_type} ")
                f.write(f"{bid} {coin.volume} {order_details}\n")
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
                    with open("log/binance.place_buy_order.log", "at") as f:
                        f.write(
                            f"{coin.symbol} {coin.date} {self.order_type} "
                        )
                        f.write(f"{bid} {coin.volume} {order_details}\n")
                    return False
                sleep(0.1)

            except BinanceAPIException as error_msg:
                with open("log/binance.place_buy_order.log", "at") as f:
                    f.write(f"{coin.symbol} {coin.date} {self.order_type} ")
                    f.write(f"{bid} {coin.volume} {order_details}\n")
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
        with open("log/binance.place_buy_order.log", "at") as f:
            f.write(f"{coin.symbol} {coin.date} {self.order_type} ")
            f.write(f"{bid} {coin.volume} {order_details}\n")
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
            coin.volume = float(volume)
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
            + f"BP:-{(100 - coin.buy_at_percentage):.2f}% "
            + f"TRP:{(coin.trail_recovery_percentage - 100):.2f}% "
            + f"S:+{s_value:.3f}% "
            + f"TTS:-{(100 - coin.trail_target_sell_percentage):.2f}% "
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

        word: str = ""
        if coin.profit < 0:
            word = "LS"
        else:
            word = "PRF"

        message: str = " ".join(
            [
                f"{c_from_timestamp(coin.date)}: {coin.symbol} "
                f"[SOLD_BY_{coin.status}]",
                f"A:{coin.holding_time}s",
                f"U:{coin.volume} P:{coin.price} T:{coin.value}",
                f"{word}:{coin.profit:.3f}",
                f"BP:{coin.bought_at}",
                f"BP:-{(100 - coin.buy_at_percentage):.2f}%",
                f"TRP:{(coin.trail_recovery_percentage - 100):.2f}%",
                f"SP:{coin.bought_at * coin.sell_at_percentage /100}",
                f"TP:{100 - (coin.bought_at / coin.price * 100):.2f}%",
                f"SL:{coin.bought_at * coin.stop_loss_at_percentage/100}",
                f"S:+{percent(coin.trail_target_sell_percentage,coin.sell_at_percentage) - 100:.3f}%",  # pylint: disable=line-too-long
                f"TTS:-{(100 - coin.trail_target_sell_percentage):.3f}%",
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

        exposure: float = self.calculates_exposure()
        logging.info(
            f"{c_from_timestamp(coin.date)}: INVESTMENT: {self.investment} "
            + f"PROFIT: {self.profit} EXPOSURE: {exposure} WALLET: "
            + f"({len(self.wallet)}/{self.max_coins}) {self.wallet}"
        )
        return True

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
        f_path: str = f"cache/{symbol}.precision"
        if self.mode == "backtesting" and exists(f_path):
            with open(f_path, "r") as f:
                info = json.load(f)
        else:
            try:
                info = self.client.get_symbol_info(symbol)
            except BinanceAPIException as error_msg:
                logging.error(error_msg)
                return str(-1)

        for d in info["filters"]:
            if "filterType" in d.keys():
                if d["filterType"] == "LOT_SIZE":
                    step_size = d["stepSize"]

        if self.mode == "backtesting" and not exists(f_path):
            with open(f_path, "w") as f:
                f.write(json.dumps(info))

        with open("log/binance.step_size.log", "at") as f:
            f.write(f"{symbol} {step_size}\n")
        return step_size

    def calculate_volume_size(self, coin) -> float:
        """calculates the amount of coin we are to buy"""

        # calculates the number of units we are about to buy based on the number
        # of decimal points used, the share of the investment and the price
        step_size: str = self.get_step_size(coin.symbol)

        investment: float = percent(self.investment, self.re_invest_percentage)

        volume: float = float(
            floor_value((investment / self.max_coins) / coin.price, step_size)
        )
        if self.debug:
            logging.debug(
                f"[{coin.symbol}] investment:{self.investment}{self.pairing} "
                + f"vol:{volume} price:{coin.price} step_size:{step_size}"
            )
        with open("log/binance.volume.log", "at") as f:
            f.write(f"{coin.symbol} {step_size} {investment} {volume}\n")
        return volume

    @retry(wait=wait_exponential(multiplier=1, max=3))
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
            price_log = f"{self.logs_dir}/testnet.log"
        else:
            price_log = (
                f"{self.logs_dir}/{datetime.now().strftime('%Y%m%d')}.log"
            )
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

    def target_sell(self, coin: Coin) -> bool:  # pylint: disable=R0201
        """
        Check for a coin we HOLD if we reached the SELL_AT_PERCENTAGE
        and mark that coin as TARGET_SELL if we have.
        """
        if coin.status == "TARGET_SELL":
            return True

        if coin.status == "HOLD":
            if coin.price > percent(coin.sell_at_percentage, coin.bought_at):
                coin.status = "TARGET_SELL"
                s_value: float = (
                    percent(
                        coin.trail_target_sell_percentage,
                        coin.sell_at_percentage,
                    )
                    - 100
                )
                logging.info(
                    f"{c_from_timestamp(coin.date)}: {coin.symbol} [HOLD] "
                    + f"-> [TARGET_SELL] ({coin.price}) "
                    + f"A:{coin.holding_time}s "
                    + f"U:{coin.volume} P:{coin.price} T:{coin.value} "
                    + f"BP:{coin.bought_at} "
                    + f"SP:{coin.bought_at * coin.sell_at_percentage /100} "
                    + f"S:+{s_value:.3f}% "
                    + f"TTS:-{(100 - coin.trail_target_sell_percentage):.2f}% "
                    + f"LP:{coin.min}(-{100 - ((coin.min/coin.max) * 100):.3f}%) "
                )
                return True
        return False

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
            ttl: float = 100 * (
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
            # had to pay in fees.
            # However, It's quite likely that if we didn't sell our coin by
            # now, we are likely to hit HARD_LIMIT_HOLDING_TIME
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
        coins_to_remove: List = []
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

    def buy_strategy(
        self, coin: Coin  # pylint: disable=unused-argument,R0201
    ) -> bool:
        """buy strategy"""
        return False

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
            if self.pull_config_address:
                self.refresh_config_from_config_endpoint_service()
            self.process_coins()
            # saves all coin and wallet data to disk
            self.save_coins()
            self.process_control_flags()
            if self.quit:
                return

            self.wait()

    def logmode(self) -> None:
        """the bot LogMode main loop"""
        while True:
            # TODO: should we extract write_log from process_coins()?
            self.process_coins()
            self.wait()

    def split_logline(self, line: str) -> Tuple:
        """splits a log line into symbol, date, price"""

        try:
            symbol, price = line[27:].split(" ", maxsplit=1)
            # ocasionally binance returns rubbish
            # we just skip it
            market_price = float(price)
        except ValueError:
            return (False, False, False)

        if symbol not in self.tickers:
            return (False, False, False)

        # datetime is very slow, discard the .microseconds and fetch a
        # cached pre-calculated unix epoch timestamp
        date = c_date_from(line[0:19])

        return (symbol, date, market_price)

    def check_for_delisted_coin(self, symbol: str) -> bool:
        """checks if a coin has been delisted"""

        # when we process old logfiles, we might encounter symbols that are
        # no longer available on binance, these will not return any klines
        # data from the API. For those we are better to remove them from our
        # tickers list as we don't want to process them.

        # TODO: re-work this by checking values in 'm' if they're []
        # as this will return a True
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
            # gzip -3 files provide the fastest decompression times I was able
            # to measure.
            if price_log.endswith(".lz4"):
                f = lz4open(price_log, mode="rt")
            else:
                f = igzip.open(price_log, "rt")
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
        if not self.cfg["TICKERS"]:
            logging.warning("no tickers to backtest")
        else:
            for price_log in self.price_logs:
                self.backtest_logfile(price_log)
                self.process_control_flags()
                if self.quit:
                    break

        # now that we are done, lets record our results
        with open(
            f"{self.logs_dir}/backtesting.log", "a", encoding="utf-8"
        ) as f:
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

        ok: bool = False
        data: dict = {}
        # fetch all the available klines for this coin, for the last
        # 60min, 24h, and 1000 days
        if self.mode in ["testnet", "live"]:
            data = self.fetch_klines_from_binance(coin.symbol, coin.date)
        else:
            response: requests.Response = requests.get(
                self.klines_caching_service_url
                + f"?symbol={coin.symbol}"
                + f"&date={coin.date}"
                + f"&mode={self.mode}"
                + f"&debug={self.debug}"
            )
            data = response.json()
        # TODO: rework this
        if data:
            ok = True

        if ok:
            coin.lowest = data["lowest"]
            coin.averages = data["averages"]
            coin.highest = data["highest"]

        # trim values
        unit_values: dict = {
            "m": (60, 1),
            "h": (24, 60),
            # for 'Days' we retrieve 1000 days, binance API default
            "d": (1000, 60 * 24),
        }
        for unit in ["m", "h", "d"]:
            # make sure we don't keep more values that we should
            timeslice, _ = unit_values[unit]
            while len(coin.lowest[unit]) > timeslice:
                coin.lowest[unit].pop()
            while len(coin.averages[unit]) > timeslice:
                coin.averages[unit].pop()
            while len(coin.highest[unit]) > timeslice:
                coin.highest[unit].pop()

        return ok

    def fetch_klines_from_binance(self, symbol: str, date: int) -> dict:
        """fetches from binance"""

        # when we initialise a coin, we pull a bunch of klines from binance.
        # we pull klines for the last 60min, the last 24h, and the last 1000days

        # url to pull klines data from
        api_url: str = (
            f"https://api.binance.com/api/v3/klines?symbol={symbol}&"
        )

        # build a dict to allows to calculate how far back in h,m,d we are going
        # to pull klines data from
        unit_values: dict = {
            "m": (60, 1),
            "h": (24, 60),
            # for 'Days' we retrieve 1000 days, binance API default
            "d": (1000, 60 * 24),
        }

        # build all the query strings we need to fetch data from binance
        binance_query_strings: dict = {}
        for unit in ["m", "h", "d"]:

            # lets find out the from what date we need to pull klines from while in
            # backtesting mode.
            timeslice, minutes_before_now = unit_values[unit]

            backtest_end_time = date
            end_unix_time: int = int(
                (backtest_end_time - (60 * minutes_before_now)) * 1000
            )

            query: str = f"{api_url}endTime={end_unix_time}&interval=1{unit}"
            binance_query_strings[unit] = query

        # now we need to initialize a temp buckets{} with the
        # lowest[], averages[], highest[]
        buckets: dict = {}
        for bucket in ["lowest", "averages", "highest"]:
            buckets[bucket] = {}
            for unit in ["m", "h", "d", "s"]:
                buckets[bucket][unit] = []

        # now we need to query binance and populate our buckets dict
        for unit in ["m", "h", "d"]:

            # the call binance for list of klines for our loop var
            # unit ('m', 'm', 'd')
            ok, klines = self.call_binance_for_klines(
                binance_query_strings[unit]
            )
            if ok:
                # and get a dict with the lowest, averages, highest lists from those
                # binance raw klines
                ok, low_avg_high = self.populate_values(klines, unit)

            if ok:
                # we should now have a new dict containing list of our
                # lowest, averages, highest values in low_avg_high
                for bucket in ["lowest", "averages", "highest"]:
                    buckets[bucket][unit] = low_avg_high[bucket]
                    # we need to trim our lists, so that we don't keep more
                    # values that we should,
                    # like storing the last 1000 minutes
                    #
                    # keep 60 minutes on our minutes bucket
                    # 24 hours in our hours bucket
                    timeslice, _ = unit_values[unit]
                    while len(buckets[bucket][unit]) > timeslice:
                        buckets[bucket][unit].pop()
        return buckets

    def call_binance_for_klines(self, query):
        """calls upstream binance and retrieves the klines for a coin"""
        logging.info(f"calling binance on {query}")
        response = requests_with_backoff(query)
        if response.status_code == 400:
            # 400 typically means binance has no klines for this coin
            logging.warning(f"got a 400 from binance for {query}")
            return (True, [])
        return (True, response.json())

    def process_klines_line(self, kline):
        """returns date, low, avg, high from a kline"""
        (_, _, high, low, _, _, closetime, _, _, _, _, _) = kline

        date = float(c_from_timestamp(closetime / 1000).timestamp())
        low = float(low)
        high = float(high)
        avg = (low + high) / 2

        return date, low, avg, high

    def populate_values(self, klines, unit) -> Tuple:
        """builds averages[], lowest[], highest[] out of klines"""
        _lowest: list = []
        _averages: list = []
        _highest: list = []

        # retrieve and calculate the lowest, highest, averages
        # from the klines data.
        # we need to transform the dates into consumable timestamps
        # that work for our bot.
        for line in klines:
            date, low, avg, high = self.process_klines_line(line)
            _lowest.append((date, low))
            _averages.append((date, avg))
            _highest.append((date, high))

        # finally, populate all the data coin buckets
        buckets: dict = {}
        for metric in ["lowest", "averages", "highest"]:
            buckets[metric] = []

        unit_buckets: Dict[str, int] = {
            "m": 60,
            "h": 24,
            # for 'Days' we retrieve 1000 days, binance API default
            "d": 1000,
        }

        timeslice: int = unit_buckets[unit]
        # we gather all the data we collected and only populate
        # the required number of records we require.
        # this could possibly be optimized, but at the same time
        # this only runs the once when we initialise a coin
        for d, v in _lowest[-timeslice:]:
            buckets["lowest"].append((d, v))

        for d, v in _averages[-timeslice:]:
            buckets["averages"].append((d, v))

        for d, v in _highest[-timeslice:]:
            buckets["highest"].append((d, v))

        return (True, buckets)

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

    def print_current_balance_report(self):
        """calculates and current balance"""

        for item in self.wallet:
            holding = self.coins[item]
            cost = holding.volume * holding.bought_at
            value = holding.volume * holding.price
            age = holding.holding_time

            logging.info(
                " ".join(
                    [
                        f"WALLET: {item} age:{age}",
                        f"bought_at:{holding.bought_at}",
                        f"current_price:{holding.price}",
                        f"cost:{cost} value:{value}",
                    ]
                )
            )

    def calculates_exposure(self):
        """calculates current balance"""

        exposure = 0
        for symbol in self.wallet:
            exposure = exposure + self.coins[symbol].profit

        return exposure

    def refresh_config_from_config_endpoint_service(self) -> None:
        """updates the bot config (ticker list) from the config endpoint"""
        try:
            r = requests.get(self.pull_config_address).json()
            if r["md5"] == self.pull_config_md5:
                return

            # create a placeholder for us to add old and new tickers
            old_tickers_in_use = {}
            # if SELL_ALL_ON_PULL_CONFIG_CHANGE is set, we will
            # simply sell all tokens and start from an empty wallet
            if self.sell_all_on_pull_config_change:
                for symbol in self.wallet:
                    sale: bool = self.sell_coin(self.coins[symbol])
                    if not sale:
                        logging.warning("Failed to sell {symbol}")
                self.clear_all_coins_stats()

            else:
                for symbol in self.wallet:
                    old_tickers_in_use[symbol] = self.tickers[symbol]

            # we need to make sure we maintain any tickers for coins we may
            # have in our wallet.
            old_tickers_in_use.update(r["TICKERS"])
            self.tickers = old_tickers_in_use
            now = udatetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
            logging.info(
                f"{now}: updating tickers: had: "
                + f"{self.pull_config_md5} now: {r['md5']}"
            )
            logging.info("new tickers:")
            pp: pprint.PrettyPrinter = pprint.PrettyPrinter(indent=4)
            pp.pprint(self.tickers)
            self.pull_config_md5 = r["md5"]
            # clean old coins data, or we will get errors later on
            symbols: List[str] = list(self.coins.keys())
            for symbol in symbols:
                if symbol not in self.tickers.keys():
                    del self.coins[symbol]
            # we now need to update the config file, so that when we restart
            # the bot will have access to all the ticker info on any coins
            # it might be holding
            with open(self.config_file, encoding="utf-8") as f:
                _cfg = yaml.safe_load(f.read())
                _cfg["TICKERS"] = self.tickers
            with open(self.config_file, "wt", encoding="utf-8") as f:
                yaml.dump(_cfg, f, default_flow_style=False)

        except Exception as error_msg:  # pylint: disable=broad-except
            logging.warning(
                f"Failed to pull config from {self.pull_config_address}"
            )
            logging.error(error_msg)

    def process_control_flags(self) -> None:
        """process control/flags"""
        if exists("control/BALANCE"):
            self.print_current_balance_report()
            unlink("control/BALANCE")
        if exists("control/SELL"):
            logging.warning("control/SELL flag found")
            with open("control/SELL") as f:
                for line in f:
                    symbol = line.strip()
                    if symbol in self.wallet:
                        logging.warning(f"control/SELL contains {symbol}")
                        self.coins[symbol].status = "CONTROL_FLAG"
                        self.sell_coin(self.coins[symbol])
            unlink("control/SELL")
        if exists("control/STOP"):
            logging.warning("control/STOP flag found. Stopping bot.")
            self.quit = True
            unlink("control/STOP")
            return
        while exists("control/PAUSE"):
            logging.warning("control/PAUSE flag found. Sleeping 1min.")
            sleep(60)
