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

    def test_contract_guard_runs_before_dependency_installation(self):
        """CI must execute this guard, not merely carry an unexecuted test file."""
        source = WORKFLOW.read_text(encoding="utf-8")
        backend = source.split("  backend:\n", 1)[1].split("\n  frontend:\n", 1)[0]
        guard = "- run: python scripts/test_ci_trigger_contract.py"
        install = "- run: pip install -r backend/requirements-dev.txt"
        self.assertEqual(backend.count(guard), 1)
        self.assertLess(backend.index(guard), backend.index(install))
        self.assertLess(backend.index(guard), backend.index("- run: cd backend && PYTHONPATH=. pytest -q"))

    def test_full_acceptance_jobs_are_not_replaced_by_focused_regressions(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        for job in (
            "backend", "frontend", "docker-smoke", "free-cloud-smoke",
            "postgres-risk-acceptance", "postgres-reservations-acceptance",
        ):
            self.assertIn(f"  {job}:\n", source)
        self.assertIn("      - run: npm test", source)
        self.assertIn("      - run: npm run build", source)
        self.assertIn("      - run: npm audit --omit=dev --audit-level=high", source)
        self.assertIn("      - run: cd backend && PYTHONPATH=. pytest -q", source)


if __name__ == "__main__":
    unittest.main()
