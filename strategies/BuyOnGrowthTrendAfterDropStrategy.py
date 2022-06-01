""" bot buy strategy file """
from app import Bot, Coin
from lib.helpers import c_from_timestamp, logging, percent


class Strategy(Bot):
    """BuyOnGrowthTrendAfterDropStrategy"""

    def buy_strategy(self, coin: Coin) -> bool:
        """BuyOnGrowthTrendAfterDropStrategy buy_strategy
        Wait for a coin to drop below BUY_AT_PERCENTAGE and then
        monitor its growth trend over a certain period, where each slice of
        that period must grow by at least n% over the previous slice.
        As soon that happens buy this coin.
        """

        unit = str(coin.klines_trend_period[-1:]).lower()
        klines_trend_period = int("".join(coin.klines_trend_period[:-1]))
        last_period = list(coin.averages[unit])[-klines_trend_period:]

        # we need at least a full period of klines before we can
        # make a buy decision
        if len(last_period) < klines_trend_period:
            return False

        # check if the maximum price recorded is now lower than the
        # BUY_AT_PERCENTAGE
        if (
            coin.price < percent(coin.buy_at_percentage, coin.max)
            and coin.status == ""
            and not coin.naughty
        ):
            coin.dip = coin.price
            coin.status = "TARGET_DIP"
            logging.info(
                f"{c_from_timestamp(coin.date)}: {coin.symbol} [{coin.status}] "
                + f"-> [TARGET_DIP] ({coin.price})"
            )

        if coin.status != "TARGET_DIP":
            return False

        # if the price keeps going down, skip it
        # we want to make sure the price has increased over n slices of the
        # klines_trend_period (m, h, d) by klines_slice_percentage_change
        # each time.
        last_period_slice = last_period[0][1]
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
        self.buy_coin(coin)
        return True
