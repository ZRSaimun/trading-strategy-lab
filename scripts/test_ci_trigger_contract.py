"""Regression guard for manually rerunnable, paper-only CI checks.

No network, credentials, trading APIs or market data are accessed.
"""
from pathlib import Path
import unittest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/checks.yml"


class WorkflowTriggerRegression(unittest.TestCase):
    def test_manual_dispatch_keeps_push_and_pr_checks(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("on:\n  push:\n  pull_request:\n  workflow_dispatch:\n", source)
        self.assertIn("name: foundation-checks", source)

    def test_hourly_fvg_suite_stays_visible_as_separate_step(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("name: Causal hourly FVG provenance regressions", source)
        self.assertIn("node --experimental-strip-types --test tests/hourly-fvg-*.test.ts", source)
        self.assertLess(source.index("name: Causal hourly FVG provenance regressions"), source.index("- run: npm test"))


if __name__ == "__main__":
    unittest.main()
