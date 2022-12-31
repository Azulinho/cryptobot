""" Coin class """

import logging
from lib.helpers import (
    add_100,
    mean,
)


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
        new_minute: bool = self.is_a_new_slot_of(date, "m")
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

        new_slot: bool = False
        # deals with the scenario, where we don't yet have 'units' data
        #  available yet
        if not self.averages[unit] and self.averages[previous]:
            if self.averages[previous][0][0] <= date - period:
                new_slot: bool = True

        # checks if our latest 'unit' record is older than 'period'
        # then we've entered a new 'unit' window
        if self.averages[unit] and not new_slot:
            record_date, _ = self.averages[unit][-1]
            if record_date <= date - period:
                new_slot: bool = True
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

    def check_for_pump_and_dump(self) -> bool:
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
