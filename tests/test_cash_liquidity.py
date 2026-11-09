from __future__ import annotations

import unittest
from decimal import Decimal

from .helpers import configure_test_environment


configure_test_environment()

from alpaca_desktop.engine import cash_percent_of_equity


class CashLiquidityTests(unittest.TestCase):
    def test_all_cash_account_is_fully_liquid(self) -> None:
        self.assertEqual(cash_percent_of_equity("509.35", "509.35"), Decimal("100.0"))

    def test_partly_invested_account(self) -> None:
        self.assertEqual(cash_percent_of_equity("250", "1010"), Decimal("24.8"))

    def test_no_equity_reports_zero_instead_of_dividing(self) -> None:
        self.assertEqual(cash_percent_of_equity("0", "0"), Decimal("0"))
        self.assertEqual(cash_percent_of_equity("10", None), Decimal("0"))
