import sys
sys.path.insert(0, '')

import json
import app
import pytest
import socket
import requests
import yaml
import udatetime
from datetime import datetime, timedelta
from unittest import mock

from binance.client import Client

@pytest.fixture()
def cfg():
    with open("tests/config.yaml") as f:
        config = yaml.safe_load(f.read())
        config["MODE"] = "backtesting"
        return config

def test_percent():
    assert app.percent(0.1, 100.0) == 0.1

@pytest.fixture()
def bot(cfg):
    with mock.patch('binance.client.Client', new_callable=mock.PropertyMock
    ) as mock1:
        mock1.return_value = None
        client = Client("FAKE", "FAKE")

        with mock.patch('requests.get', return_value={}
        ) as mock2:

            bot = app.Bot(client, 'configfilename', cfg)
            bot.client.API_URL = "https://www.google.com"
            yield bot
            del(bot)

@pytest.fixture()
def coin(bot):
    coin = app.Coin(
        symbol="BTCUSDT",
        date=float(udatetime.now().timestamp() - 3600),
        market_price=float(100.00),
        buy_at=float(bot.tickers['BTCUSDT']['BUY_AT_PERCENTAGE']),
        sell_at=float(bot.tickers['BTCUSDT']['SELL_AT_PERCENTAGE']),
        stop_loss=float(bot.tickers['BTCUSDT']['STOP_LOSS_AT_PERCENTAGE']),
        trail_target_sell_percentage=float(bot.tickers['BTCUSDT']['TRAIL_TARGET_SELL_PERCENTAGE']),
        trail_recovery_percentage=float(bot.tickers['BTCUSDT']['TRAIL_RECOVERY_PERCENTAGE']),
        soft_limit_holding_time=int(bot.tickers['BTCUSDT']['SOFT_LIMIT_HOLDING_TIME']),
        hard_limit_holding_time=int(bot.tickers['BTCUSDT']['HARD_LIMIT_HOLDING_TIME']),
        naughty_timeout=int(bot.tickers['BTCUSDT']['NAUGHTY_TIMEOUT']),
        klines_trend_period=str(bot.tickers['BTCUSDT']['KLINES_TREND_PERIOD']),
        klines_slice_percentage_change=float(
            bot.tickers['BTCUSDT']["KLINES_SLICE_PERCENTAGE_CHANGE"]
        )
    )
    yield coin
    del(coin)

class TestCoin:
    def test_update_coin_wont_age_if_not_owned(self, coin):
        coin.holding_time = 0
        coin.status = ""
        coin.update(float(udatetime.now().timestamp()), 100.0)
        assert coin.holding_time == 0

    def test_update_coin_in_target_sell_status_will_age(self, coin):
        coin.holding_time = 0
        coin.status = "TARGET_SELL"
        coin.bought_date =  float(udatetime.now().timestamp() - 3600)
        coin.update(float(udatetime.now().timestamp()), 100.0)
        assert coin.holding_time == 3600

    def test_update_coin_in_hold_status_will_age(self, coin):
        coin.holding_time = 0
        coin.status = "HOLD"
        coin.bought_date =  float(udatetime.now().timestamp() - 3600)
        coin.update(float(udatetime.now().timestamp()), 100.0)
        assert coin.holding_time == 3600

    def test_update_coin_in_naughty_reverts_to_non_naughty_after_timeout_(self, coin):
        coin.naughty_timeout = 3599
        coin.naughty = True
        coin.naughty_date =  float(udatetime.now().timestamp() - 3600)
        coin.update(float(udatetime.now().timestamp()), 100.0)
        assert coin.naughty == False

    def test_update_coin_in_naughty_remains_naughty_before_timeout_(self, coin):
        coin.naughty_timeout = 7200
        coin.naughty = True
        coin.naughty_date =  float(udatetime.now().timestamp() - 3600)
        coin.update(float(udatetime.now().timestamp()), 100.0)
        assert coin.naughty == True

    def test_update_reached_new_min(self, coin):
        coin.min = 200
        coin.update(float(udatetime.now().timestamp()), 100.0)
        assert coin.min == 100

    def test_update_reached_new_max(self, coin):
        coin.max = 100
        coin.update(float(udatetime.now().timestamp()), 200.0)
        assert coin.max == 200

    def test_update_value_is_set(self, coin):
        coin.volume = 2
        coin.update(float(udatetime.now().timestamp()), 100.0)
        assert coin.value == 200

    def test_update_coin_change_status_from_hold_to_target_sell(self, coin):
        coin.status = "HOLD"
        coin.sell_at_percentage = 3
        coin.bought_at = 100
        coin.bought_date =  float(udatetime.now().timestamp() - 3600)
        coin.update(float(udatetime.now().timestamp()), 120.00)
        assert coin.status == "TARGET_SELL"

    def test_update_coin_updates_state_dip(self, coin):
        coin.status = "TARGET_DIP"
        coin.dip = 150
        coin.update(float(udatetime.now().timestamp()), 120.00)
        assert coin.dip == 120.00

    def test_update_coin_updates_seconds_averages(self, coin):
        now = float(udatetime.now().timestamp())
        coin.update(now, 120.00)

        # coin.averages['unit'] is a tupple of (date, price)
        assert (now, 120.00) in coin.averages['s']

        # expect one element (date, price)
        assert 120.00 == coin.averages['s'][0][1]
        assert len(coin.averages['s']) == 1


    def test_update_coin_updates_minutes_averages(self, coin):
        for x in list(reversed(range(60 * 2 + 1))):
            coin_time = float(udatetime.now().timestamp() - x)
            coin.update(coin_time , 100)

        assert len(coin.averages['s']) == 60

        assert len(coin.averages['m']) == 2

        for d,v in list(coin.averages['s']):
            assert v == 100

        assert list(coin.averages['m'])[0][1] == 100.0

    def test_update_coin_updates_hour_averages(self, coin):
        for x in list(reversed(range(60 * 60 + 60 + 1))):
            coin_time = float(udatetime.now().timestamp() - x)
            coin.update(coin_time , 100)

        assert len(coin.averages['s']) == 60

        assert len(coin.averages['m']) == 60

        for d,v in list(coin.averages['m']):
            assert v == 100

        assert list(coin.averages['h'])[0][1] == 100.0

    def test_update_coin_updates_days_averages(self, coin):
        for x in list(reversed(range(3600 * 24 + 3600 + 60 + 1))):
            coin_time = float(udatetime.now().timestamp() - x)
            coin.update(coin_time , 100)

        assert len(coin.averages['h']) == 24

        for d,v in list(coin.averages['h']):
            assert v == 100

        assert len(coin.averages['d']) == 1
        assert list(coin.averages['d'])[0][1] == 100.0

    def test_update_coin_updates_minutes_lowest_highest(self, coin):
        price = 100
        for x in list(reversed(range(60 * 2 + 1))):
            coin_time = float(udatetime.now().timestamp() - x)
            coin.update(coin_time , price)
            price = price + 1

        assert len(coin.lowest['m']) == 2
        assert list(coin.lowest['m'])[0][1] == 100.0
        assert list(coin.highest['m'])[0][1] == 160.0

        assert list(coin.lowest['m'])[-1][1] == 160.0
        assert list(coin.highest['m'])[-1][1] == 220.0

    def test_update_coin_updates_hour_lowest_highest(self, coin):
        price = 100
        for x in list(reversed(range(60 * 60 + 60 + 1))):
            coin_time = float(udatetime.now().timestamp() - x)
            coin.update(coin_time , price)
            price = price + 1

        assert len(coin.lowest['m']) == 60
        assert len(coin.highest['m']) == 60
        assert len(coin.lowest['h']) == 1
        assert len(coin.highest['h']) == 1

        assert list(coin.lowest['h'])[0][1] == 100.0
        assert list(coin.highest['h'])[0][1] == 3760.0

    def test_update_coin_updates_day_lowest_highest(self, coin):
        price = 100
        for x in list(reversed(range(3600 * 24 + 3600 + 60 + 1))):
            coin_time = float(udatetime.now().timestamp() - x)
            coin.update(coin_time , price)
            price = price + 1

        assert len(coin.lowest['h']) == 24
        assert len(coin.highest['h']) == 24
        assert len(coin.lowest['d']) == 1
        assert len(coin.highest['d']) == 1

        assert list(coin.lowest['d'])[0][1] == 100.0
        assert list(coin.highest['d'])[0][1] == 90160.0

    def test_trim_averages(self, coin):
        price = 100
        now = udatetime.now().timestamp()

        for x in list(reversed(range(3600 * 48 + 3600 + 60 + 1))):
            coin_time = float(now - x)
            coin.update(coin_time , price)

        for unit in ['s', 'm', 'h']:
            coin.trim_averages(now, unit)

        assert coin.averages['s'][0] == (now - 60, 100.0)
        assert coin.averages['s'][59] == (now - 1, 100.0)

        assert coin.averages['m'][0] == (now - 3600, 100.0)
        assert coin.averages['m'][59] == (now - 60, 100.0)

        assert coin.averages['h'][0] == (now - 86400, 100.0)
        assert coin.averages['h'][23] == (now - 3600, 100.0)

    def test_for_pump_and_dump_returns_true_on_pump(self, coin):
        now = udatetime.now().timestamp()

        coin.klines_trend_period = "2h"
        coin.klines_slice_percentage_change = float(1)

        coin.update(now - 3600 * 3, 500)
        coin.update(now - 3600 * 2, 500)
        coin.update(now - 3600 , 500)
        # price has gone up 500%
        coin.update(now, 100)

        assert coin.check_for_pump_and_dump() is True

    def test_for_pump_and_dump_returns_false_on_pump(self, coin):
        now = udatetime.now().timestamp()

        coin.klines_trend_period = "1h"
        coin.klines_slice_percentage_change = float(1)

        coin.update(now - 3600 * 3, 100)
        coin.update(now - 3600 * 2, 100)
        coin.update(now - 3600 , 100)
        # price has gone up 500%
        coin.update(now, 500)

        assert coin.check_for_pump_and_dump() is False


class TestBot:
    def test_sell_coin_in_testnet(self, bot, coin):
        bot.mode = "testnet"
        coin.price = 100
        bot.wallet = [ "BTCUSDT" ]
        bot.coins["BTCUSDT"] = coin

        with mock.patch.object(
            bot.client, 'create_order', return_value={
                "symbol": "BTCUSDT",
                "orderId": "1",
                "transactTime": 1507725176595,
                "fills": [
                    {
                        "price": "100",
                        "qty": "1",
                        "commission": "1",
                    }
                ]
            }
        ) as m1:
            with mock.patch.object(
                bot.client, 'get_all_orders', return_value=[
                    {
                        "symbol": "BTCUSDT",
                        "orderId": 1
                    }
                ]
            ) as m2:
                with mock.patch.object(
                    bot, 'get_symbol_precision', return_value=1
                ) as m3:
                    bot.sell_coin(coin)
                    assert bot.wallet == []
                    assert float(coin.price) == float(100)
                    assert float(coin.bought_at) == float(0)
                    assert float(coin.value) == float(0.0)


    def test_get_symbol_precision(self, bot, coin):
        with mock.patch.object(
            bot.client, 'get_symbol_info', return_value={
                "symbol": "BTCUSDT",
                "filters": [
                    {},
                    {},
                    { "stepSize": "0.1" }
                ]
            }
        ) as m1:
            result = bot.get_symbol_precision('BTCUSDT')
            assert result == 1

    def test_extract_order_data(self):
        pass

    def test_calculate_volume_size(self, bot, coin):
        with mock.patch.object(
            bot, 'get_symbol_precision', return_value=1
        ) as m1:
            volume = bot.calculate_volume_size(coin)
            assert volume == 0.5

    def test_get_binance_prices(self, bot, coin):
        pass

    def test_init_or_update_coin(self, bot, coin, cfg):
        binance_data = {"symbol":"BTCUSDT","price":"101.000"}

        bot.load_klines_for_coin = mock.Mock()

        result = bot.init_or_update_coin(binance_data)
        assert result == None

        assert float(bot.coins['BTCUSDT'].price) == float(101.0)
        assert bot.coins['BTCUSDT'].buy_at_percentage == float(
            100 + cfg['TICKERS']['BTCUSDT']['BUY_AT_PERCENTAGE']
        )
        assert bot.coins['BTCUSDT'].stop_loss_at_percentage == float(
            100 + cfg['TICKERS']['BTCUSDT']['STOP_LOSS_AT_PERCENTAGE']
        )
        assert bot.coins['BTCUSDT'].sell_at_percentage == float(
            100 + cfg['TICKERS']['BTCUSDT']['SELL_AT_PERCENTAGE']
        )
        assert bot.coins['BTCUSDT'].trail_target_sell_percentage == float(
            100 + cfg['TICKERS']['BTCUSDT']['TRAIL_TARGET_SELL_PERCENTAGE']
        )
        assert bot.coins['BTCUSDT'].trail_recovery_percentage == float(
            100 + cfg['TICKERS']['BTCUSDT']['TRAIL_RECOVERY_PERCENTAGE']
        )
        assert bot.coins['BTCUSDT'].naughty_timeout == int(
            cfg['TICKERS']['BTCUSDT']['NAUGHTY_TIMEOUT']
        )

    def test_process_coins(self, bot, coin):
        # the bot will not buy coins when we have less than 31days of prices
        # so we mock those calls done in process_coins() to so that
        # the new_listing() check doesn't return False
        # as the coin won't have any averages['d'] value
        bot.load_klines_for_coin = mock.Mock()
        bot.new_listing = mock.Mock()

        for x in list(reversed(range(32))):
            coin_time = float(udatetime.now().timestamp() - (x * 86400))
            coin.update(coin_time , 0)

        bot.coins['BTCUSDT'] = coin

        with mock.patch.object(
            bot.client, 'create_order', return_value={
                "symbol": "BTCUSDT",
                "orderId": "1",
                "transactTime": 1507725176595,
                "fills": [
                    {
                        "price": "100",
                        "qty": "1",
                        "commission": "1",
                    }
                ]
            }
        ) as m1:
            with mock.patch.object(
                bot.client, 'get_all_orders', return_value=[
                    {
                        "symbol": "BTCUSDT",
                        "orderId": 1
                    }
                ]
            ) as m2:
                with mock.patch.object(
                    bot, 'get_symbol_precision', return_value=1
                ) as m3:
                    binance_data = [
                        {"symbol":"BTCUSDT","price":"101.000"},
                        {"symbol":"BTCUSDT","price":"70.000"},
                        {"symbol":"BTCUSDT","price":"75.000"},
                    ]
                    with mock.patch.object(
                        bot, 'get_binance_prices', return_value=binance_data
                    ) as m4:
                        with mock.patch.object(
                            bot, 'run_strategy', return_value=None
                        ) as m5:
                            bot.process_coins()
                            assert m5.assert_called() is None


    def test_load_klines_for_coin(self, bot, coin):
        date = float(datetime.fromisoformat(
            "2021-12-04 05:23:05.693516",
        ).timestamp())
        r = requests.models.Response()
        r.status_code = 200
        r.headers['Content-Type'] = "application/json"
        response = []
        price = 1
        seconds = 0
        for _ in range(60):
            response.append([
                date + seconds,
                price,
                price + 1,
                price - 1,
                price,
                '3722.44662000',
                date + seconds,
                '227105989.39175430',
                79789,
                '1764.30200000',
                '107638043.51761510',
                '0'
            ])
            price = price + 1
            seconds = seconds + 60

        coin.date = date + seconds
        r._content = json.dumps(response).encode('utf-8')

        with mock.patch('requests.get', return_value=r) as mock2:
            app.open =  mock.mock_open()
            bot.load_klines_for_coin(coin)

        # upstream we retrieve 1000 days of history, but we only mock 60 days
        # in here. so we should expect 60 days of data
        assert len(coin.lowest['d']) == 60
        assert len(coin.lowest['h']) == 24
        assert len(coin.lowest['m']) == 60

        assert len(coin.averages['d']) == 60
        assert len(coin.averages['h']) == 24
        assert len(coin.averages['m']) == 60

        assert len(coin.highest['d']) == 60
        assert len(coin.highest['h']) == 24
        assert len(coin.highest['m']) == 60

        assert coin.lowest['m'] == [
            (1638595.385694, 0.0), (1638595.445694, 1.0), (1638595.505694, 2.0),
            (1638595.565694, 3.0), (1638595.625694, 4.0), (1638595.685694, 5.0),
            (1638595.745694, 6.0), (1638595.805694, 7.0), (1638595.865694, 8.0),
            (1638595.925694, 9.0), (1638595.985694, 10.0), (1638596.045694, 11.0),
            (1638596.105694, 12.0), (1638596.165694, 13.0), (1638596.225694, 14.0),
            (1638596.285694, 15.0), (1638596.345694, 16.0), (1638596.405694, 17.0),
            (1638596.465694, 18.0), (1638596.525694, 19.0), (1638596.585694, 20.0),
            (1638596.645694, 21.0), (1638596.705694, 22.0), (1638596.765694, 23.0),
            (1638596.825694, 24.0), (1638596.885694, 25.0), (1638596.945694, 26.0),
            (1638597.005694, 27.0), (1638597.065694, 28.0), (1638597.125694, 29.0),
            (1638597.185694, 30.0), (1638597.245694, 31.0), (1638597.305694, 32.0),
            (1638597.365694, 33.0), (1638597.425694, 34.0), (1638597.485694, 35.0),
            (1638597.545694, 36.0), (1638597.605694, 37.0), (1638597.665694, 38.0),
            (1638597.725694, 39.0), (1638597.785694, 40.0), (1638597.845694, 41.0),
            (1638597.905694, 42.0), (1638597.965694, 43.0), (1638598.025694, 44.0),
            (1638598.085694, 45.0), (1638598.145694, 46.0), (1638598.205694, 47.0),
            (1638598.265694, 48.0), (1638598.325694, 49.0), (1638598.385694, 50.0),
            (1638598.445694, 51.0), (1638598.505694, 52.0), (1638598.565694, 53.0),
            (1638598.625694, 54.0), (1638598.685694, 55.0), (1638598.745694, 56.0),
            (1638598.805694, 57.0), (1638598.865694, 58.0), (1638598.925694, 59.0)
        ]

        assert coin.averages['m'] == [
            (1638595.385694, 1.0), (1638595.445694, 2.0), (1638595.505694, 3.0),
            (1638595.565694, 4.0), (1638595.625694, 5.0), (1638595.685694, 6.0),
            (1638595.745694, 7.0), (1638595.805694, 8.0), (1638595.865694, 9.0),
            (1638595.925694, 10.0), (1638595.985694, 11.0), (1638596.045694, 12.0),
            (1638596.105694, 13.0), (1638596.165694, 14.0), (1638596.225694, 15.0),
            (1638596.285694, 16.0), (1638596.345694, 17.0), (1638596.405694, 18.0),
            (1638596.465694, 19.0), (1638596.525694, 20.0), (1638596.585694, 21.0),
            (1638596.645694, 22.0), (1638596.705694, 23.0), (1638596.765694, 24.0),
            (1638596.825694, 25.0), (1638596.885694, 26.0), (1638596.945694, 27.0),
            (1638597.005694, 28.0), (1638597.065694, 29.0), (1638597.125694, 30.0),
            (1638597.185694, 31.0), (1638597.245694, 32.0), (1638597.305694, 33.0),
            (1638597.365694, 34.0), (1638597.425694, 35.0), (1638597.485694, 36.0),
            (1638597.545694, 37.0), (1638597.605694, 38.0), (1638597.665694, 39.0),
            (1638597.725694, 40.0), (1638597.785694, 41.0), (1638597.845694, 42.0),
            (1638597.905694, 43.0), (1638597.965694, 44.0), (1638598.025694, 45.0),
            (1638598.085694, 46.0), (1638598.145694, 47.0), (1638598.205694, 48.0),
            (1638598.265694, 49.0), (1638598.325694, 50.0), (1638598.385694, 51.0),
            (1638598.445694, 52.0), (1638598.505694, 53.0), (1638598.565694, 54.0),
            (1638598.625694, 55.0), (1638598.685694, 56.0), (1638598.745694, 57.0),
            (1638598.805694, 58.0), (1638598.865694, 59.0), (1638598.925694, 60.0)
        ]

        assert coin.highest['m'] == [
            (1638595.385694, 2.0), (1638595.445694, 3.0), (1638595.505694, 4.0),
            (1638595.565694, 5.0), (1638595.625694, 6.0), (1638595.685694, 7.0),
            (1638595.745694, 8.0), (1638595.805694, 9.0), (1638595.865694, 10.0),
            (1638595.925694, 11.0), (1638595.985694, 12.0), (1638596.045694, 13.0),
            (1638596.105694, 14.0), (1638596.165694, 15.0), (1638596.225694, 16.0),
            (1638596.285694, 17.0), (1638596.345694, 18.0), (1638596.405694, 19.0),
            (1638596.465694, 20.0), (1638596.525694, 21.0), (1638596.585694, 22.0),
            (1638596.645694, 23.0), (1638596.705694, 24.0), (1638596.765694, 25.0),
            (1638596.825694, 26.0), (1638596.885694, 27.0), (1638596.945694, 28.0),
            (1638597.005694, 29.0), (1638597.065694, 30.0), (1638597.125694, 31.0),
            (1638597.185694, 32.0), (1638597.245694, 33.0), (1638597.305694, 34.0),
            (1638597.365694, 35.0), (1638597.425694, 36.0), (1638597.485694, 37.0),
            (1638597.545694, 38.0), (1638597.605694, 39.0), (1638597.665694, 40.0),
            (1638597.725694, 41.0), (1638597.785694, 42.0), (1638597.845694, 43.0),
            (1638597.905694, 44.0), (1638597.965694, 45.0), (1638598.025694, 46.0),
            (1638598.085694, 47.0), (1638598.145694, 48.0), (1638598.205694, 49.0),
            (1638598.265694, 50.0), (1638598.325694, 51.0), (1638598.385694, 52.0),
            (1638598.445694, 53.0), (1638598.505694, 54.0), (1638598.565694, 55.0),
            (1638598.625694, 56.0), (1638598.685694, 57.0), (1638598.745694, 58.0),
            (1638598.805694, 59.0), (1638598.865694, 60.0), (1638598.925694, 61.0)
        ]

        assert coin.lowest['h'] == [
            (1638597.545694, 36.0), (1638597.605694, 37.0), (1638597.665694, 38.0),
            (1638597.725694, 39.0), (1638597.785694, 40.0), (1638597.845694, 41.0),
            (1638597.905694, 42.0), (1638597.965694, 43.0), (1638598.025694, 44.0),
            (1638598.085694, 45.0), (1638598.145694, 46.0), (1638598.205694, 47.0),
            (1638598.265694, 48.0), (1638598.325694, 49.0), (1638598.385694, 50.0),
            (1638598.445694, 51.0), (1638598.505694, 52.0), (1638598.565694, 53.0),
            (1638598.625694, 54.0), (1638598.685694, 55.0), (1638598.745694, 56.0),
            (1638598.805694, 57.0), (1638598.865694, 58.0), (1638598.925694, 59.0)
        ]

        assert coin.averages['h'] == [
            (1638597.545694, 37.0), (1638597.605694, 38.0), (1638597.665694, 39.0),
            (1638597.725694, 40.0), (1638597.785694, 41.0), (1638597.845694, 42.0),
            (1638597.905694, 43.0), (1638597.965694, 44.0), (1638598.025694, 45.0),
            (1638598.085694, 46.0), (1638598.145694, 47.0), (1638598.205694, 48.0),
            (1638598.265694, 49.0), (1638598.325694, 50.0), (1638598.385694, 51.0),
            (1638598.445694, 52.0), (1638598.505694, 53.0), (1638598.565694, 54.0),
            (1638598.625694, 55.0), (1638598.685694, 56.0), (1638598.745694, 57.0),
            (1638598.805694, 58.0), (1638598.865694, 59.0), (1638598.925694, 60.0)
        ]

        assert coin.highest['h'] == [
            (1638597.545694, 38.0), (1638597.605694, 39.0), (1638597.665694, 40.0),
            (1638597.725694, 41.0), (1638597.785694, 42.0), (1638597.845694, 43.0),
            (1638597.905694, 44.0), (1638597.965694, 45.0), (1638598.025694, 46.0),
            (1638598.085694, 47.0), (1638598.145694, 48.0), (1638598.205694, 49.0),
            (1638598.265694, 50.0), (1638598.325694, 51.0), (1638598.385694, 52.0),
            (1638598.445694, 53.0), (1638598.505694, 54.0), (1638598.565694, 55.0),
            (1638598.625694, 56.0), (1638598.685694, 57.0), (1638598.745694, 58.0),
            (1638598.805694, 59.0), (1638598.865694, 60.0), (1638598.925694, 61.0)
        ]

        # we're mocking 60 data points, which is the number of data points
        # in the minutes counters, so we should be able to consume those
        # instead of providing a full set of values here
        assert coin.lowest['d'] == coin.lowest['m']
        assert coin.averages['d'] == coin.averages['m']
        assert coin.highest['d'] == coin.highest['m']


class TestBotCheckForSaleConditions:
    def test_returns_early_on_empty_wallet(self, bot, coin):
        bot.wallet = []
        result = bot.check_for_sale_conditions(coin)
        assert result == (False, 'EMPTY_WALLET')

    def test_returns_early_on_stop_loss(self, bot, coin):
        bot.wallet = ["BTCUSDT"]
        coin.price = 1
        coin.bought_at = 100
        result = bot.check_for_sale_conditions(coin)
        assert result == (True, 'STOP_LOSS')

    def test_returns_early_on_stale_coin(self, bot, coin):
        bot.wallet = ["BTCUSDT"]
        coin.price = 1000
        coin.holding_time = 99999
        coin.status = "DIRTY"
        bot.hard_limit_holding_time = 1
        result = bot.check_for_sale_conditions(coin)
        assert result == (True, 'STALE')

    def test_returns_early_on_coing_gone_up_and_dropped_when_flagged_on(self, bot, coin):
        bot.wallet = ["BTCUSDT"]
        bot.sell_as_soon_it_drops = True
        coin.status = "TARGET_SELL"
        coin.price = 100.5
        coin.last = 120
        coin.bought_at = 100
        result = bot.check_for_sale_conditions(coin)
        print(coin.stop_loss_at_percentage)
        assert result == (True, 'GONE_UP_AND_DROPPED')

    def test_returns_early_on_possible_sale(self, bot, coin):
        bot.wallet = ["BTCUSDT"]
        coin.status = "TARGET_SELL"
        coin.bought_at = 1
        coin.price = 50
        coin.last = 100
        coin.tip = 200
        result = bot.check_for_sale_conditions(coin)
        assert result == (True, 'TARGET_SELL')

    def test_returns_final_on_past_soft_limit(self, bot, coin):
        bot.wallet = ["BTCUSDT"]
        coin.bought_at = 100
        coin.price = 100
        coin.last = 100
        coin.tip = 100
        result = bot.check_for_sale_conditions(coin)
        assert result == (False, 'HOLD')

class TestBuyCoin:
    def test_buy_coin_when_coin_already_on_wallet(self, bot, coin):
        bot.wallet = ["BTCUSDT"]
        bot.buy_coin(coin)
        assert bot.wallet == ["BTCUSDT"]

    def test_buy_coin_when_wallet_is_full(self, bot, coin):
        bot.wallet = ["BTCUSDT", "ETHUSDT"]
        bot.buy_coin(coin)
        assert bot.wallet == ["BTCUSDT", "ETHUSDT"]

    def test_buy_coin_when_coin_is_naughty(self, bot, coin):
        coin.naughty = True
        bot.buy_coin(coin)
        assert bot.wallet == []

    @mock.patch('app.Bot.get_symbol_precision', return_value=1)
    def test_buy_coin_in_backtesting(self, mocked, bot, coin):
        bot.mode = "backtesting"
        coin.price = 100

        bot.buy_coin(coin)
        assert bot.wallet == ["BTCUSDT"]
        assert coin.bought_at == 100
        assert coin.volume == 0.5

    def test_buy_coin_in_testnet(self, bot, coin):
        bot.mode = "testnet"
        coin.price = 100

        with mock.patch.object(
            bot.client, 'create_order', return_value={
                "symbol": "BTCUSDT",
                "orderId": "1",
                "transactTime": 1507725176595,
                "fills": [
                    {
                        "price": "100",
                        "qty": "1",
                        "commission": "1",
                    }
                ]
            }
        ) as m1:
            with mock.patch.object(
                bot.client, 'get_all_orders', return_value=[
                    {
                        "symbol": "BTCUSDT",
                        "orderId": 1
                    }
                ]
            ) as m2:
                with mock.patch.object(
                    bot, 'get_symbol_precision', return_value=1
                ) as m3:

                    bot.buy_coin(coin)
                    assert bot.wallet == ["BTCUSDT"]
                    assert coin.bought_at == 100
                    assert coin.volume == 0.5
                    # TODO: assert that clear_all_coins_stats

class TestCoinStatus:
    def test_stop_loss(self, bot, coin):
        bot.wallet = ["BTCUSDT"]
        coin.bought_at = 100
        coin.cost = 100
        coin.price = 20
        coin.value = 20
        coin.volume = 1

        with mock.patch.object(
            bot.client, 'create_order', return_value={
                "symbol": "BTCUSDT",
                "orderId": "1",
                "transactTime": 1507725176595,
                "fills": [
                    {
                        "price": "100",
                        "qty": "1",
                        "commission": "1",
                    }
                ]
            }
        ) as m1:
            with mock.patch.object(
                bot.client, 'get_all_orders', return_value=[
                    {
                        "symbol": "BTCUSDT",
                        "orderId": 1
                    }
                ]
            ) as m2:
                bot.stop_loss(coin)
                assert bot.wallet == []
                assert bot.profit == -80.12
                assert round(bot.investment, 2) == float(19.88)
                assert bot.losses == 1


    def test_coin_gone_up_and_dropped(self, bot, coin):
        bot.wallet = ["BTCUSDT"]
        coin.bought_at = 100
        coin.cost = 100
        coin.price = 1
        coin.profit = -99
        coin.status = "TARGET_SELL"
        coin.value = 1
        coin.volume = 1
        with mock.patch.object(
            bot.client, 'create_order', return_value={
                "symbol": "BTCUSDT",
                "orderId": "1",
                "transactTime": 1507725176595,
                "fills": [
                    {
                        "price": "100",
                        "qty": "1",
                        "commission": "1",
                    }
                ]
            }
        ) as m1:
            with mock.patch.object(
                bot.client, 'get_all_orders', return_value=[
                    {
                        "symbol": "BTCUSDT",
                        "orderId": 1
                    }
                ]
            ) as m2:

                result = bot.coin_gone_up_and_dropped(coin)
                assert result == True
                assert bot.wins == 1
                assert bot.profit == -99.101
                assert round(bot.investment, 1) == round(0.89, 1)


    def test_possible_sale(self, bot, coin):
        bot.wallet = ["BTCUSDT"]
        coin.bought_at = 100
        coin.cost = 100
        coin.tip = 300
        coin.last = 290
        coin.price = 200
        coin.profit = 100
        coin.status = "TARGET_SELL"
        coin.value = 200
        coin.volume = 1
        with mock.patch.object(
            bot.client, 'create_order', return_value={
                "symbol": "BTCUSDT",
                "orderId": "1",
                "transactTime": 1507725176595,
                "fills": [
                    {
                        "price": "100",
                        "qty": "1",
                        "commission": "1",
                    }
                ]
            }
        ) as m1:
            with mock.patch.object(
                bot.client, 'get_all_orders', return_value=[
                    {
                        "symbol": "BTCUSDT",
                        "orderId": 1
                    }
                ]
            ) as m2:

                result = bot.possible_sale(coin)
                assert result == True
                assert bot.wins == 1
                assert bot.profit == 99.7
                assert round(bot.investment, 1) == round(199.7, 1)

    def test_past_hard_limit(self, bot, coin, cfg):
        bot.wallet = ["BTCUSDT"]
        coin.bought_at = 100
        coin.cost = 100
        coin.tip = 300
        coin.last = 290
        coin.price = 200
        coin.profit = 100
        coin.value = 200
        coin.volume = 1
        coin.holding_time = 9999999
        with mock.patch.object(
            bot.client, 'create_order', return_value={
                "symbol": "BTCUSDT",
                "orderId": "1",
                "transactTime": 1507725176595,
                "fills": [
                    {
                        "price": "100",
                        "qty": "1",
                        "commission": "1",
                    }
                ]
            }
        ) as m1:
            with mock.patch.object(
                bot.client, 'get_all_orders', return_value=[
                    {
                        "symbol": "BTCUSDT",
                        "orderId": 1
                    }
                ]
            ) as m2:

                result = bot.past_hard_limit(coin)
                assert result == True
                assert bot.stales == 1
                assert bot.profit == 99.7
                assert coin.naughty_timeout == int(bot.tickers['BTCUSDT']['NAUGHTY_TIMEOUT'])
                assert round(bot.investment, 1) == round(199.7, 1)

    def test_past_soft_limit(self, bot, coin):
        coin.bought_at = 100
        coin.bought_date =  float(udatetime.now().timestamp() - 3600)
        coin.cost = 100
        coin.tip = 300
        coin.last = 290
        coin.price = 200
        coin.profit = 100
        coin.value = 200
        coin.volume = 1
        coin.holding_time = 5400
        with mock.patch.object(
            bot.client, 'create_order', return_value={
                "symbol": "BTCUSDT",
                "orderId": "1",
                "transactTime": 1507725176595,
                "fills": [
                    {
                        "price": "100",
                        "qty": "1",
                        "commission": "1",
                    }
                ]
            }
        ) as m1:
            with mock.patch.object(
                bot.client, 'get_all_orders', return_value=[
                    {
                        "symbol": "BTCUSDT",
                        "orderId": 1
                    }
                ]
            ) as m2:

                result = bot.past_soft_limit(coin)
                assert result == True
                assert coin.naughty_timeout == int(bot.tickers['BTCUSDT']['NAUGHTY_TIMEOUT'])
                assert coin.sell_at_percentage == 101.5
                assert coin.trail_target_sell_percentage == 99.749

    def test_clear_all_coins_stats(self, bot, coin):
        coin1 = coin
        coin2 = coin
        coin1.symbol = "BTCUSDT"
        coin1.status = "DIRTY"
        coin2.symbol = "ETHUSDT"
        coin2.status = "DIRTY"
        bot.coins['BTCUSDT'] = coin1
        bot.coins['ETHUSDT'] = coin2

        result = bot.clear_all_coins_stats()
        assert result is None
        assert bot.coins['BTCUSDT'].status == ""
        assert bot.coins['ETHUSDT'].status == ""

    def test_clear_coin_stats(self, bot, coin, cfg):
        coin.status = "DIRTY"
        coin.holding_time = 999
        coin.buy_at_percentage = 999
        coin.sell_at_percentage = 999
        coin.stop_loss_at_percentage = 999
        coin.trail_target_sell_percentage = 999
        coin.trail_recovery_percentage = 999
        coin.bought_at = float(9999)
        coin.dip = float(9999)
        coin.tip = float(9999)
        coin.max = float(9999)
        coin.min = float(9999)

        result = bot.clear_coin_stats(coin)
        assert result == None
        assert coin.status == ""
        assert coin.holding_time == 1
        assert coin.buy_at_percentage == 100 + cfg['TICKERS']['BTCUSDT']['BUY_AT_PERCENTAGE']
        assert coin.sell_at_percentage == 100 + cfg['TICKERS']['BTCUSDT']['SELL_AT_PERCENTAGE']
        assert coin.stop_loss_at_percentage == 100 + cfg['TICKERS']['BTCUSDT']['STOP_LOSS_AT_PERCENTAGE']
        assert coin.trail_target_sell_percentage == 100 + cfg['TICKERS']['BTCUSDT']['TRAIL_TARGET_SELL_PERCENTAGE']
        assert coin.trail_recovery_percentage == 100 + cfg['TICKERS']['BTCUSDT']['TRAIL_RECOVERY_PERCENTAGE']
        assert coin.bought_at == float(0)
        assert coin.dip == float(0)
        assert coin.tip == float(0)
        assert coin.max == float(100)
        assert coin.min == float(100)
        assert coin.min == coin.price
        assert coin.max == coin.price

class TestBotProfit:
    def test_update_investment(self, bot):
        bot.profit = 10

        result = bot.update_investment()
        assert result is None
        assert bot.investment == 110

    def test_update_bot_profit_returns_None(self, bot, coin):
        result = bot.update_bot_profit(coin)
        assert result == None

    def test_update_bot_profit_on_profit(self, bot, coin):
        coin.cost = 100
        coin.value = 200
        coin.profit = 100

        result = bot.update_bot_profit(coin)
        # bought 100 of coin and paid 0.1% of fees which is 0.10
        # sold 200 of coin and paid 0.1% of fees which is 0.20
        assert float(round(bot.fees, 1)) == float(0.3)
        assert float(bot.profit) == float(99.7)

    def test_update_bot_profit_on_loss(self, bot, coin):
        coin.cost = 110
        coin.value = 100
        coin.profit = -10

        result = bot.update_bot_profit(coin)
        # bought 110 of coin and paid 0.1% of fees which is 0.11
        # sold 100 of coin and paid 0.1% of fees which is 0.10
        assert bot.profit == -10.21
        assert bot.fees == 0.21000000000000002

class StrategyBaseTestClass:
    def test_coin_is_set_to_target_dip_when_price_drops(self, bot, coin):
        coin.status = ""
        coin.price = 90
        coin.max = 100
        for _ in range(32):
            # TODO: mock new_listing()
            # address pump_checks
            coin.averages['d'].append(
                (datetime.now().timestamp(), 9999)
            )
            coin.averages['h'].append(
                (datetime.now().timestamp(), 9999)
            )

        result = bot.buy_strategy(coin)
        assert result == False
        assert coin.status == "TARGET_DIP"

    def test_returns_early_when_coin_is_not_TARGET_DIP(self, bot, coin):
        coin.status = ""
        coin.price = 100
        coin.max = 100
        result = bot.buy_strategy(coin)
        assert result == False
        assert coin.status == ""


class TestStrategyBuyDropSellRecovery(StrategyBaseTestClass):
    @pytest.fixture()
    def bot(self, cfg):
        with mock.patch('binance.client.Client', new_callable=mock.PropertyMock
        ) as mock1:
            mock1.return_value = None
            client = Client("FAKE", "FAKE")

            with mock.patch('requests.get', return_value={}
            ) as mock2:

                bot = app.BuyDropSellRecoveryStrategy(
                    client, 'configfilename', cfg
                )
                bot.client.API_URL = "https://www.google.com"
                yield bot
                del(bot)

    def test_coin_is_not_bought_when_current_price_lower_than_last(self, bot, coin):
        coin.status = "TARGET_DIP"
        coin.price = 90
        coin.last = 100
        with mock.patch.object(
            bot, 'buy_coin', return_value=False
        ) as m1:
            result = bot.buy_strategy(coin)
            assert result == False
            assert coin.status == "TARGET_DIP"
            m1.assert_not_called()

    def test_bot_buys_coin_when_price_over_trail_recovery_dip(self, bot, coin):
        coin.status = "TARGET_DIP"
        coin.price = 90
        coin.last = 80
        coin.dip = 80

        for _ in range(14):
            coin.averages['d'].append(0)

        with mock.patch.object(
            bot, 'buy_coin', return_value=False
        ) as m1:
            result = bot.buy_strategy(coin)
            assert result == True
            assert coin.status == "TARGET_DIP"
            m1.assert_called()

class TestStrategyMoonSellRecovery:
    @pytest.fixture()
    def bot(self, cfg):
        with mock.patch('binance.client.Client', new_callable=mock.PropertyMock
        ) as mock1:
            mock1.return_value = None
            client = Client("FAKE", "FAKE")

            with mock.patch('requests.get', return_value={}
            ) as mock2:

                bot = app.BuyMoonSellRecoveryStrategy(
                    client, 'configfilename', cfg
                )
                bot.client.API_URL = "https://www.google.com"
                yield bot
                del(bot)

    def test_bot_does_not_buy_coin_when_price_below_buy_at_percentage(self, bot, coin):
        # TODO: refactor this into its own config fixture
        coin.buy_at_percentage = 105
        coin.price = 101
        coin.last = 100
        with mock.patch.object(
            bot, 'buy_coin', return_value=False
        ) as m1:
            result = bot.buy_strategy(coin)
            assert result == False
            m1.assert_not_called()

    def test_bot_buys_coin_when_price_above_buy_at_percentage(self, bot, coin):
        # TODO: refactor this into its own config fixture
        coin.buy_at_percentage = 105
        coin.price = 100
        coin.last = 90
        for _ in range(14):
            coin.averages['d'].append(0)

        with mock.patch.object(
            bot, 'buy_coin', return_value=True
        ) as m1:
            result = bot.buy_strategy(coin)
            assert result == True
            m1.assert_called()


class TestStrategyBuyOnGrowthTrendAfterDrop(StrategyBaseTestClass):
    @pytest.fixture()
    def bot(self, cfg):
        with mock.patch('binance.client.Client', new_callable=mock.PropertyMock
        ) as mock1:
            mock1.return_value = None
            client = Client("FAKE", "FAKE")

            with mock.patch('requests.get', return_value={}
            ) as mock2:

                bot = app.BuyOnGrowthTrendAfterDropStrategy(
                    client, 'configfilename', cfg
                )
                bot.client.API_URL = "https://www.google.com"
                yield bot
                del(bot)


    def test_coin_not_bought_when_price_below_averages_threshold(self, bot, coin):
        coin.status = "TARGET_DIP"
        coin.price = 90
        coin.last = 80
        coin.dip = 80

        coin.klines_slice_percentage_change = float(1)
        coin.klines_trend_period = "3h"

        for x in list(reversed(range(14))):
            coin_time = float(udatetime.now().timestamp() - (86400 * x))
            coin.averages['d'].append((coin_time, 1))

        with mock.patch.object(
            bot, 'buy_coin', return_value=True
        ) as m1:
            result = bot.buy_strategy(coin)
            assert result == False
            assert coin.status == "TARGET_DIP"
            m1.assert_not_called()

    def test_coin_bought_when_price_above_averages_threshold(self, bot, coin):
        coin.status = "TARGET_DIP"
        coin.price = 90
        coin.last = 80
        coin.dip = 80

        coin.klines_slice_percentage_change = 1 # +1%
        coin.klines_trend_period = "4d"

        avg_price = float(1)
        for x in list(reversed(range(14))):
            coin_time = float(udatetime.now().timestamp() - (86400 * x))
            coin.averages['d'].append((coin_time, avg_price))
            avg_price = avg_price * 1.01 # +1%

        with mock.patch.object(
            bot, 'buy_coin', return_value=True
        ) as m1:
            result = bot.buy_strategy(coin)
            m1.assert_called()
            assert coin.status == "TARGET_DIP"
            assert result == True


class TestBacktesting:
    def backtesting(self):
        pass

    def backtest_logfile(self):
        pass
