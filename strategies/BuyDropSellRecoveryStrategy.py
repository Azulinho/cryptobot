""" bot buy strategy file """
from app import Bot, Coin
from lib.helpers import percent, c_from_timestamp, logging


class Strategy(Bot):
    """Base Strategy Class"""

    def buy_strategy(self, coin: Coin) -> bool:
        """bot buy strategy"""

        # has the price gone down by x% on a coin we don't own?
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
