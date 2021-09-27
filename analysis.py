import re
import math
import sys
import traceback

from termcolor import colored, cprint

from config import (
    INITIAL_INVESTMENT,
    HOLDING_TIME,
    BUY_AT_PERCENTAGE,
    SELL_AT_PERCENTAGE,
    STOP_LOSS_AT_PERCENTAGE,
    EXCLUDED_COINS
)


cprint("reading logfile...", "green")

#with open('23rd.log') as f:
#with open('24th.log') as f:
#with open('25th.log') as f:
with open('prices.log') as f:
    day = f.readlines()
cprint("finished reading logfile...", "green")

percent = lambda part, whole:float(whole) / 100 * float(part)
pattern = '([0-9]{4}-[0-9]{2}-[0-9]{2}\s[0-9]{2}:[0-9]{2}:[0-9]{2}).*\s([0-9|A-Z].*USDT)\s([0-9]*\.[0-9]*)'


coins = {}
holding = False
profit = float(0)
investment = INITIAL_INVESTMENT
excluded_coins = EXCLUDED_COINS
wins = 0
losses = 0
holding_time = 0

for line in day:
    try:
        date, symbol, price  = re.match(pattern,line).groups()

        #  if symbol != 'C98USDT':
        #      continue

        if 'UP' in symbol:
            continue

        if 'DOWN' in symbol:
            continue

        if symbol in excluded_coins:
            continue

        if symbol not in coins:
            coins[symbol] = {}
            coins[symbol]['max'] = float(price)
            coins[symbol]['min'] = float(price)

        coins[symbol]['date'] = date
        coins[symbol]['price'] = float(price)

        # do we have a new min price?
        if float(price) < coins[symbol]['min']:
            coins[symbol]['min'] = float(price)

        # do we have a new max price?
        if float(price) > coins[symbol]['max']:
            coins[symbol]['max'] = float(price)

        # has the price gone down by x% on a coin we don't own?
        if not holding and 'bought_at' not in coins[symbol]:
            if float(price) < percent(BUY_AT_PERCENTAGE, coins[symbol]['max']):
                # do some gimmicks, and don't buy the coin straight away
                # but only buy it when the price is now higher than the minimum
                # price ever recorded. This way we ensure that we got the dip
                cprint(f"{date}: possible buy: {symbol}: current: {price} min: {coins[symbol]['min']}", "blue")
                if float(price) > coins[symbol]['min']:
                    coins[symbol]['bought_at'] = float(price)
                    holding = True
                    holding_time = 0
                    cprint(f"{date}: bought ${investment} of {symbol} with price of {price}", "magenta")
                    continue

        if 'bought_at' in coins[symbol]:
            # This coin is too old, sell it
            if holding_time > HOLDING_TIME: # TODO: this is not a real time count
                cprint(f"{date}: forcing sale of old coin: {symbol}: {price} : {coins[symbol]['max']}", "red")
                volume = float(investment / float(coins[symbol]['bought_at']))
                sale_profit = volume * float(price) - volume * float(coins[symbol]['bought_at'])
                profit = float(profit) + float(sale_profit)
                cprint(f"{date}: sold ${int(float(volume) * float(price))} of {symbol} with price of {price} and loss: {sale_profit}", "red")
                del coins[symbol]['bought_at']
                holding = False
                # and block this coin for today:
                excluded_coins.append(symbol)
                investment = investment + sale_profit
                losses = losses +1
                # clear all stats on coins, like in a new start.
                # we had a stale coin, so its likely the market has shifted
                # and our stats do not reflect the state of the market anymore
                coins = {}
                continue

        if 'bought_at' in coins[symbol]:
            # deal with STOP_LOSS
            if float(price) < percent(STOP_LOSS_AT_PERCENTAGE, coins[symbol]['bought_at']):
                cprint(f"{date}: stop loss: {symbol}: {price} : {coins[symbol]['max']}", "red")
                volume = float(investment / float(coins[symbol]['bought_at']))
                sale_profit = volume * float(price) - volume * float(coins[symbol]['bought_at'])
                profit = float(profit) + float(sale_profit)
                cprint(f"{date}: sold ${int(float(volume) * float(price))} of {symbol} with price of {price} and loss: {sale_profit}", "red")
                del coins[symbol]['bought_at']
                holding = False
                # and block this coin for today:
                excluded_coins.append(symbol)
                investment = investment + sale_profit
                losses = losses +1
                # clear all stats on coins, like in a new start.
                # we had a stop loss, so its likely the market has shifted
                # and our stats do not reflect the state of the market anymore
                coins = {}
                continue

            if float(price) > percent(SELL_AT_PERCENTAGE, coins[symbol]['bought_at']):
                # do some gimmicks, and don't sell the coin straight away
                # but only buy it when the price is now lower than the minimum
                # price ever recorded
                cprint(f"{date}: possible sell: {symbol} current: {price} max: {coins[symbol]['max']}", "blue")
                if float(price) < coins[symbol]['max']:
                    volume = float(investment / float(coins[symbol]['bought_at']))
                    sale_profit = volume * float(price) - volume * float(coins[symbol]['bought_at'])
                    profit = float(profit) + float(sale_profit)

                    cprint(f"{date}: sold ${int(float(volume) * float(price))} of {symbol} with price of {price} and profit: {sale_profit}", "green")
                    del coins[symbol]['bought_at']
                    holding = False
                    # clear all stats on coins, like in a new start.
                    # this mostly clears up the maximum price, to avoid us falling
                    # into a trap, where the price has gone down(crash) from an
                    # earlier time in the day, followed by a down slow slope
                    # which could trigger the -n% in price from earlier and get
                    # us stuck with a coin that will take a long time to recover
                    # as the market moved on since the max price earlier
                    coins = {}
                    # and finally re-invest our profit, we're aiming to compound
                    # so on every sale we invest our profit as well.
                    investment = investment + sale_profit
                    wins = wins + 1
                    continue

        # we hold a coin, increase its age
        if 'bought_at' in coins[symbol]:
            holding_time = holding_time + 1


    except:
        print(traceback.format_exc())
        sys.exit(1)

for symbol in coins.keys():
    if 'bought_at' in coins[symbol]:
        cprint(f"still holding {symbol}", "red")
        volume = float(investment / float(coins[symbol]['bought_at']))
        cprint(f" cost: {volume * coins[symbol]['bought_at']}", "green")
        cprint(f" value: {volume * coins[symbol]['price']}", "red")
        break


print(f"total profit: {profit}")
print(f"initial investment: {INITIAL_INVESTMENT} final investment: {investment}")
print(f"buy_at: {BUY_AT_PERCENTAGE} sell_at: {SELL_AT_PERCENTAGE}")
print(f"wins: {wins} losses: {losses}")
