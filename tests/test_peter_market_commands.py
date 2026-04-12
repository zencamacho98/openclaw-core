"""
tests/test_peter_market_commands.py

Unit tests for market command parsing in Peter (peter/commands.py).

Covers:
  - "market" → MARKET_STATUS
  - "market status" → MARKET_STATUS
  - "market report" → MARKET_STATUS
  - "readiness" → MARKET_READINESS
  - "market readiness" → MARKET_READINESS
  - "kill" → KILL_TRADING
  - "kill trading" → KILL_TRADING
  - "kill switch" → KILL_TRADING
  - "kill live trading" → KILL_TRADING with environment="live"
  - Existing commands not broken
"""
from __future__ import annotations

import pathlib
import sys
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from peter.commands import parse_command, CommandType


class TestMarketStatusCommand(unittest.TestCase):

    def _parse(self, text: str) -> CommandType:
        return parse_command(text).type

    def test_market_alone(self):
        self.assertEqual(self._parse("market"), CommandType.MARKET_STATUS)

    def test_market_status(self):
        self.assertEqual(self._parse("market status"), CommandType.MARKET_STATUS)

    def test_market_report(self):
        self.assertEqual(self._parse("market report"), CommandType.MARKET_STATUS)

    def test_feed_status(self):
        self.assertEqual(self._parse("feed status"), CommandType.MARKET_STATUS)

    def test_feed(self):
        self.assertEqual(self._parse("feed"), CommandType.MARKET_STATUS)


class TestMarketReadinessCommand(unittest.TestCase):

    def _parse(self, text: str) -> CommandType:
        return parse_command(text).type

    def test_readiness(self):
        self.assertEqual(self._parse("readiness"), CommandType.MARKET_READINESS)

    def test_market_readiness(self):
        self.assertEqual(self._parse("market readiness"), CommandType.MARKET_READINESS)

    def test_live_readiness(self):
        self.assertEqual(self._parse("live readiness"), CommandType.MARKET_READINESS)

    def test_readiness_scorecard(self):
        self.assertEqual(self._parse("readiness scorecard"), CommandType.MARKET_READINESS)


class TestKillTradingCommand(unittest.TestCase):

    def _parse(self, text: str):
        return parse_command(text)

    def test_kill(self):
        cmd = self._parse("kill")
        self.assertEqual(cmd.type, CommandType.KILL_TRADING)

    def test_kill_trading(self):
        cmd = self._parse("kill trading")
        self.assertEqual(cmd.type, CommandType.KILL_TRADING)

    def test_kill_switch(self):
        cmd = self._parse("kill switch")
        self.assertEqual(cmd.type, CommandType.KILL_TRADING)

    def test_kill_defaults_to_paper(self):
        cmd = self._parse("kill")
        self.assertEqual(cmd.args.get("environment", "paper"), "paper")

    def test_kill_live_sets_live_env(self):
        cmd = self._parse("kill live trading")
        self.assertEqual(cmd.args.get("environment"), "live")


class TestExistingCommandsUnbroken(unittest.TestCase):

    def _parse(self, text: str) -> CommandType:
        return parse_command(text).type

    def test_status_still_works(self):
        self.assertEqual(self._parse("status"), CommandType.STATUS)

    def test_warden_still_works(self):
        self.assertEqual(self._parse("warden"), CommandType.WARDEN_STATUS)

    def test_custodian_still_works(self):
        self.assertEqual(self._parse("custodian"), CommandType.CUSTODIAN_HEALTH)

    def test_sentinel_still_works(self):
        self.assertEqual(self._parse("sentinel"), CommandType.SENTINEL_STATUS)

    def test_help_still_works(self):
        self.assertEqual(self._parse("help"), CommandType.HELP)

    def test_build_still_works(self):
        self.assertEqual(self._parse("build a new route"), CommandType.BUILD_INTENT)


if __name__ == "__main__":
    unittest.main(verbosity=2)
