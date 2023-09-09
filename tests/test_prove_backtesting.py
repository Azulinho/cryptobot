""" test_prove_backtesting """

import os
import unittest
from typing import Tuple, Dict, Any
from unittest import mock
from datetime import datetime

import json
import importlib

pb = importlib.import_module("utils.prove-backtesting")

CONFIG: Dict = {
    "FILTER_BY": "",
    "FROM_DATE": "20180101",
    "END_DATE": "20221231",
    "ROLL_BACKWARDS": 4,
    "ROLL_FORWARD": 3,
    "STRATEGY": "BuyDropSellRecoveryStrategy",
    "RUNS": {},
    "PAUSE_FOR": "0.1",
    "INITIAL_INVESTMENT": 100,
    "RE_INVEST_PERCENTAGE": 100,
    "MAX_COINS": 1,
    "PAIRING": "USDT",
    "CLEAR_COIN_STATS_AT_BOOT": True,
    "CLEAR_COIN_STATS_AT_SALE": True,
    "DEBUG": False,
    "TRADING_FEE": 0.1,
    "SELL_AS_SOON_IT_DROPS": True,
    "STOP_BOT_ON_LOSS": False,
    "STOP_BOT_ON_STALE": False,
    "ENABLE_NEW_LISTING_CHECKS": True,
    "ENABLE_NEW_LISTING_CHECKS_AGE_IN_DAYS": 30,
    "KLINES_CACHING_SERVICE_URL": "http://klines",
    "PRICE_LOG_SERVICE_URL": "http://price-log",
    "CONCURRENCY": 1,
    "MIN_WINS": 1,
    "MIN_PROFIT": 1,
    "MAX_LOSSES": 1,
    "MAX_STALES": 1,
    "MAX_HOLDS": 1,
    "VALID_TOKENS": [],
}


def mocked_get_index_json_call(_):
    """mocks get_index_json"""

    class Obj:  # pylint: disable=too-few-public-methods
        """mocks get_index_json"""

        def __init__(self):
            """mocks get_index_json"""
            self.content = json.dumps({})

    return Obj()


class TestProveBacktesting(unittest.TestCase):
    """Test ProveBacktesting"""

    def test_parse_backtesting_line(self):
        """test parse backtesting line"""

        pb.get_index_json = mocked_get_index_json_call
        obj = pb.ProveBacktesting(CONFIG)

        # Define test inputs
        line = "|".join(
            [
                "profit:99.000",
                "investment:199.0",
                "days:1",
                "w1,l0,s0,h0",
                "cfg:coin.fake.yaml",
                ", ".join(
                    [
                        '{"CLEAR_COIN_STATS_AT_BOOT": true',
                        '"CLEAR_COIN_STATS_AT_SALE": true',
                        '"DEBUG": false',
                        '"ENABLE_NEW_LISTING_CHECKS": true',
                        '"ENABLE_NEW_LISTING_CHECKS_AGE_IN_DAYS": 31',
                        '"INITIAL_INVESTMENT": 100.0',
                        '"KLINES_CACHING_SERVICE_URL": "http://klines:8999"',
                        '"MAX_COINS": 1',
                        '"PAIRING": "USDT"',
                        '"PAUSE_FOR": 1.0',
                        '"PRICE_LOGS": ["20211207.log.gz"]',
                        '"PRICE_LOG_SERVICE_URL": "http://price-log-service:8998"',
                        '"RE_INVEST_PERCENTAGE": 100.0',
                        '"SELL_AS_SOON_IT_DROPS": true',
                        '"STOP_BOT_ON_LOSS": false',
                        '"STOP_BOT_ON_STALE": false',
                        '"STRATEGY": "BuyDropSellRecoveryStrategy"',
                        '"TICKERS": {"fake": {}}',
                        '"TRADING_FEE": "1e-06"',
                        '"MODE": "backtesting"}',
                    ]
                ),
            ]
        )

        coins: Dict = {}

        # Call the method being tested
        result: Any = obj.parse_backtesting_line(line, coins)

        # Define the expected output
        expected: Tuple = (
            True,
            {
                "fake": {
                    "profit": 99.0,
                    "wls": "w1,l0,s0,h0",
                    "w": 1,
                    "l": 0,
                    "s": 0,
                    "h": 0,
                    "cfgname": "cfg:coin.fake.yaml",
                    "coincfg": {},
                }
            },
        )

        # Assert the result
        self.assertEqual(result, expected)

    def test_generate_start_dates(self):
        """Test Generate Start Dates"""

        pb.get_index_json = mocked_get_index_json_call
        instance = pb.ProveBacktesting(CONFIG)

        # Define input parameters
        start_date = datetime(2022, 1, 1)
        end_date = datetime(2022, 1, 31)
        jump = 7

        # Call the function
        result = instance.generate_start_dates(start_date, end_date, jump)

        # Define the expected output
        expected_output = [
            "20220101",
            "20220108",
            "20220115",
            "20220122",
            "20220129",
        ]

        # Perform the assertion
        self.assertEqual(result, expected_output)

    def test_rollback_dates_from(self):
        """test rollback dates from"""
        end_date = "20211231"
        expected_dates = ["20211228", "20211229", "20211230", "20211231"]

        pb.get_index_json = mocked_get_index_json_call
        instance = pb.ProveBacktesting(CONFIG)

        actual_dates = instance.rollback_dates_from(end_date)
        self.assertEqual(actual_dates, expected_dates)

    def test_rollforward_dates_from(self):
        """test rollforward dates from"""
        pb.get_index_json = mocked_get_index_json_call
        instance = pb.ProveBacktesting(CONFIG)

        end_date = "20210101"
        instance.roll_forward = 3
        expected_result = ["20210102", "20210103", "20210104"]
        result = instance.rollforward_dates_from(end_date)
        self.assertEqual(result, expected_result)

        end_date = "20211230"
        instance.roll_forward = 1
        expected_result = ["20211231"]
        result = instance.rollforward_dates_from(end_date)
        self.assertEqual(result, expected_result)

        end_date = "20210131"
        instance.roll_forward = 0
        expected_result = []
        result = instance.rollforward_dates_from(end_date)
        self.assertEqual(result, expected_result)

    def test_generate_price_log_list(self):
        """test generate price log"""

        dates = ["20210101", "20210102", "20210103"]
        symbol = "AAPL"
        expected_urls = [
            "AAPL/20210101.log.gz",
            "AAPL/20210102.log.gz",
            "AAPL/20210103.log.gz",
        ]

        pb.get_index_json = mocked_get_index_json_call
        instance = pb.ProveBacktesting(CONFIG)

        result = instance.generate_price_log_list(dates, symbol)

        # Assert
        self.assertEqual(result, expected_urls)

    def test_filter_on_avail_days_with_log(self):
        """test filter on avail days with log"""
        pb.get_index_json = mocked_get_index_json_call
        instance = pb.ProveBacktesting(CONFIG)

        # Define test input
        dates = ["2021-01-01", "2021-01-02"]
        data = {
            "2021-01-01": ["BTCUSDT", "ETHUSDT"],
            "2021-01-02": ["BTCUSDT", "ETHUSDT"],
            "2021-01-03": ["BTCUSDT", "ETHUSDT"],
        }

        # Call the method under test
        result = instance.filter_on_avail_days_with_log(dates, data)

        # Define the expected output
        expected = {
            "BTCUSDT": [
                "BTCUSDT/2021-01-01.log.gz",
                "BTCUSDT/2021-01-02.log.gz",
            ],
            "ETHUSDT": [
                "ETHUSDT/2021-01-01.log.gz",
                "ETHUSDT/2021-01-02.log.gz",
            ],
        }

        # Assert the result matches the expected output
        self.assertEqual(result, expected)

    def test_filter_on_coins_with_min_age_logs(self):
        """test filter on coins win min age logs"""

        # TODO: review this
        pb.get_index_json = mocked_get_index_json_call
        instance = pb.ProveBacktesting(CONFIG)

        index = {
            "20220101": ["BTCUSDT", "ETHUSDT", "BNBUSDT"],
            "20220102": ["BTCUSDT", "ETHUSDT"],
            "20220103": ["BNBUSDT"],
        }
        last_day = "20220104"
        next_run_coins = {
            "BTCUSDT": ["20220101.log.gz", "20220102.log.gz"],
            "ETHUSDT": ["20220101.log.gz", "20220102.log.gz"],
            "BNBUSDT": ["20220101.log.gz", "20220103.log.gz"],
        }
        instance.enable_new_listing_checks_age_in_days = 2

        expected_result = {
            "BTCUSDT": ["20220101.log.gz", "20220102.log.gz"],
            "ETHUSDT": ["20220101.log.gz", "20220102.log.gz"],
            "BNBUSDT": ["20220101.log.gz", "20220103.log.gz"],
        }

        result = instance.filter_on_coins_with_min_age_logs(
            index, last_day, next_run_coins
        )
        self.assertEqual(result, expected_result)

    @mock.patch("builtins.open")
    def test_gather_best_results_from_run(self, mock_open):
        """test gather best results from run"""
        # Mock the file contents and search results
        mock_open.return_value.__enter__.return_value.read.return_value = (
            "INFO wins:10 losses:2 stales:3 holds:4 final balance: 100.0"
        )

        pb.get_index_json = mocked_get_index_json_call
        obj = pb.ProveBacktesting(CONFIG)

        # Set the desired values for min_wins, min_profit, max_losses, max_stales, max_holds
        obj.min_wins = 5
        obj.min_profit = 50.0
        obj.max_losses = 10
        obj.max_stales = 10
        obj.max_holds = 10

        # Set the desired coin list and run_id
        coin_list = {"coin1"}
        run_id = "123"

        # Call the method
        result = obj.sum_of_results_from_run(coin_list, run_id)

        # Assert the expected results
        self.assertEqual(result["total_wins"], 10)
        self.assertEqual(result["total_losses"], 2)
        self.assertEqual(result["total_stales"], 3)
        self.assertEqual(result["total_holds"], 4)
        self.assertEqual(result["total_profit"], 100.0)

    def test_find_best_results_from_backtesting_log(self):
        """test find best results from backtesting log"""
        pb.get_index_json = mocked_get_index_json_call
        instance = pb.ProveBacktesting(CONFIG)

        # TODO: mock open and os.remove
        # Create a mock backtesting.log file
        with open("log/backtesting.log", "w", encoding="utf-8") as f:
            f.write("line 1\n")
            f.write("line 2\n")
            f.write("line 3\n")

        def mock_parse_backtesting_line(_, __) -> Tuple[bool, Dict[str, Any]]:
            """mock parse backtesting line"""
            return True, {
                "coin1": {"coincfg": "config1"},
                "coin2": {"coincfg": "config2"},
            }

        with mock.patch.object(
            instance,
            "parse_backtesting_line",
            side_effect=mock_parse_backtesting_line,
        ):
            # Call the method under test
            result = instance.find_best_results_from_backtesting_log("coincfg")

        os.remove("log/backtesting.log")

        expected_result = {"coin1": "config1", "coin2": "config2"}
        self.assertEqual(result, expected_result)
