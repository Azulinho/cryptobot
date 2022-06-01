""" bot buy strategy file """
from app import Bot, Coin
from lib.helpers import c_from_timestamp, logging, percent


class Strategy(Bot):
    """BuyDropSellRecoveryStrategy"""

    def buy_strategy(self, coin: Coin) -> bool:
        """BuyDropSellRecoveryStrategy buy_strategy

        this strategy, looks for the recovery point in price for a coin after
        a drop in price.
        when a coin drops by BUY_AT_PERCENTAGE the bot marks that coin
        as TARGET_DIP, and then monitors its price recording the lowest
        price it sees(the dip).
        As soon the coin goes above the dip by TRAIL_RECOVERY_PERCENTAGE
        the bot buys the coin."""

        if (
            # as soon the price goes below BUY_AT_PERCENTAGE, mark coin as
            # TARGET_DIP
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

        # record the dip, and wait until the price recovers all the way
        # to the TRAIL_RECOVERY_PERCENTAGE, then buy.
        self.log_debug_coin(coin)
        if coin.price > coin.last:
            if coin.price > percent(coin.trail_recovery_percentage, coin.dip):
                self.buy_coin(coin)
                return True
        return False
