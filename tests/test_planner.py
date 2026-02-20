from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from modpath_cpp.planner import analyze_compile_commands

FIXTURE_COMPILE_COMMANDS = (
    Path(__file__).parent
    / "fixtures"
    / "sample_project"
    / "compile_commands.json"
)


class PlannerTests(unittest.TestCase):
    def test_core_planner_signals(self) -> None:
        report = analyze_compile_commands(FIXTURE_COMPILE_COMMANDS, top=20)

        self.assertEqual(report.translation_units, 2)

        candidates = {candidate.header: candidate for candidate in report.candidates}

        self.assertIn("include/common/config.h", candidates)
        self.assertGreaterEqual(candidates["include/common/config.h"].macro_defines, 8)
        self.assertGreaterEqual(candidates["include/common/config.h"].risk_score, 65)

        self.assertTrue(candidates["include/core/cycle_a.hpp"].in_cycle)
        self.assertTrue(candidates["include/core/cycle_b.hpp"].in_cycle)

        statuses = {check["title"]: check["status"] for check in report.readiness_checks}
        self.assertEqual(statuses["C++20 compiler mode coverage"], "warn")

    def test_cli_json_output(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        cli_path = repo_root / "modpath-cpp"

        result = subprocess.run(
            [
                sys.executable,
                str(cli_path),
                str(FIXTURE_COMPILE_COMMANDS),
                "--json",
                "--top",
                "5",
            ],
            cwd=repo_root,
            check=True,
            text=True,
            capture_output=True,
        )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["summary"]["translation_units"], 2)
        self.assertGreaterEqual(len(payload["candidates"]), 3)
        self.assertIn("p1_header_units", payload["phases"])


if __name__ == "__main__":
    unittest.main()
