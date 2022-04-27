""" bot buy strategy file """
from app import Bot, Coin, logger
from lib.helpers import percent, c_from_timestamp


class Strategy(Bot):
    """Buy Strategy

    """

    def buy_strategy(self, coin: Coin) -> bool:
        """bot buy strategy"""

        unit = str(coin.klines_trend_period[-1:]).lower()
        klines_trend_period = int(coin.klines_trend_period[:-1])

        last_period = list(coin.averages[unit])[-klines_trend_period:]

        if len(last_period) < klines_trend_period:
            return False

        last_period_slice = last_period[0][1]
        # if the price keeps going down, skip it
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

        # has the price gone down by x% on a coin we don't own?
        if (
            coin.price < percent(coin.buy_at_percentage, coin.max)
            and coin.status == ""
            and not coin.naughty
        ):
            coin.dip = coin.price
            logger.send("info",
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
            if coin.price > percent(
                coin.trail_recovery_percentage, coin.dip
            ):
                self.buy_coin(coin)
                return True
        return False
