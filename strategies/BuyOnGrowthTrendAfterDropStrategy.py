""" bot buy strategy file """
from app import Bot, Coin, logger
from lib.helpers import percent, c_from_timestamp


class Strategy(Bot):
    """Buy Strategy

    Wait for a coin to drop below BUY_AT_PERCENTAGE and then
    monitor its growth trend over a certain period, where each slice of
    that period must grow by at least n% over the previous slice.
    As soon that happens buy this coin.
    """

    def buy_strategy(self, coin: Coin) -> bool:
        """bot buy strategy"""

        unit = str(coin.klines_trend_period[-1:]).lower()
        klines_trend_period = int(''.join(coin.klines_trend_period[:-1]))
        last_period = list(coin.averages[unit])[-klines_trend_period:]

        if len(last_period) < klines_trend_period:
            return False

        # has the price gone down by x% on a coin we don't own?
        if (
            coin.price < percent(coin.buy_at_percentage, coin.max)
            and coin.status == ""
            and not coin.naughty
        ):
            coin.dip = coin.price
            coin.status = "TARGET_DIP"
            logger.send("info",
                f"{c_from_timestamp(coin.date)}: {coin.symbol} [{coin.status}] "
                + f"-> [TARGET_DIP] ({coin.price})"
            )

        if coin.status != "TARGET_DIP":
            return False

        # if the price keeps going down, skip it
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
