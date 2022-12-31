""" bot buy strategy file """
from lib.bot import Bot
from lib.coin import Coin
from lib.helpers import c_from_timestamp, logging, percent


class Strategy(Bot):
    """BuyOnRecoveryAfterDropDuringGrowthTrendStrategy"""

    def buy_strategy(self, coin: Coin) -> bool:
        """BuyOnRecoveryAfterDropDuringGrowthTrendStrategy buy_strategy

        This strategy looks for coins that have gone up by
        KLINES_SLICE_PERCENTAGE_CHANGE in each slice (m,h,d) of the
        KLINES_TREND_PERIOD.
        Then it checkous that the current price for those is
        lower than the BUY_AT_PERCENTAGE over the maximum price recorded.
        if it is, then mark the coin as TARGET_DIP
        and buy it as soon we're over the dip by TRAIL_RECOVERY_PERCENTAGE.
        """

        unit = str(coin.klines_trend_period[-1:]).lower()
        klines_trend_period = int(coin.klines_trend_period[:-1])

        last_period = list(coin.averages[unit])[-klines_trend_period:]

        # we need at least a full period of klines before we can
        # make a buy decision
        if len(last_period) < klines_trend_period:
            return False

        last_period_slice = last_period[0][1]
        # if the price keeps going down, skip it
        # we want to make sure the price has increased over n slices of the
        # klines_trend_period (m, h, d) by klines_slice_percentage_change
        # each time.
        for _, n in last_period[1:]:
            if (
                percent(
                    100 + coin.klines_slice_percentage_change,
                    last_period_slice,
                )
                > n
            ):
                return False
            last_period_slice = n

        # check if the maximum price recorded is now lower than the
        # BUY_AT_PERCENTAGE
        if (
            coin.price < percent(coin.buy_at_percentage, coin.max)
            and coin.status == ""
            and not coin.naughty
        ):
            coin.dip = coin.price
            logging.info(
                f"{c_from_timestamp(coin.date)}: {coin.symbol} [{coin.status}] "
                + f"-> [TARGET_DIP] ({coin.price})"
            )
            coin.status = "TARGET_DIP"
            return False

        if coin.status != "TARGET_DIP":
            return False

        # do some gimmicks, and don't buy the coin straight away
        # but only buy it when the price is now higher than the last
        # price recorded. This way we ensure that we got the dip
        self.log_debug_coin(coin)
        if coin.price > coin.last:
            if coin.price > percent(coin.trail_recovery_percentage, coin.dip):
                self.buy_coin(coin)
                return True
        return False
