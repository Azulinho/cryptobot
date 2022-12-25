""" bot buy strategy file """
from app import Bot, Coin
from lib.helpers import c_from_timestamp, logging, mean, percent


class Strategy(Bot):
    """BuyOnRecoveryAfterDropFromAverageStrategy"""

    def buy_strategy(self, coin: Coin) -> bool:
        """BuyOnRecoveryAfterDropFromAverageStrategy buy_strategy

        This strategy looks for coins that are below the average price over
        the last KLINES_TREND_PERIOD by at least the BUY_AT_PERCENTAGE.
        if it is, then mark the coin as TARGET_DIP
        and buy it as soon we're over the dip by TRAIL_RECOVERY_PERCENTAGE.
        """

        unit = str(coin.klines_trend_period[-1:]).lower()
        klines_trend_period = int("".join(coin.klines_trend_period[:-1]))

        last_period = list(coin.averages[unit])[-klines_trend_period:]

        # we need at least a full period of klines before we can
        # make a buy decision
        if len(last_period) < klines_trend_period:
            return False

        average = mean([v for _, v in last_period])
        # check if the average price recorded over the last_period is now
        # lower than the BUY_AT_PERCENTAGE
        if (
            coin.status == ""
            and not coin.naughty
            and (coin.price < percent(coin.buy_at_percentage, average))
        ):
            coin.dip = coin.price
            logging.info(
                f"{c_from_timestamp(coin.date)}: {coin.symbol} [{coin.status}] "
                + f"-> [TARGET_DIP] ({coin.price})"
            )
            coin.status = "TARGET_DIP"

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
