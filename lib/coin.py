""" Coin class """

from typing import Dict, List
from lib.helpers import add_100


class Coin:  # pylint: disable=too-few-public-methods
    """Coin Class"""

    offset: Dict[str, int] = {"s": 60, "m": 3600, "h": 86400}

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
        self.lowest: dict[str, List[List[float]]] = {
            "m": [],
            "h": [],
            "d": [],
        }
        self.averages: dict[str, List[List[float]]] = {
            "s": [],
            "m": [],
            "h": [],
            "d": [],
        }
        self.highest: dict[str, List[List[float]]] = {
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
