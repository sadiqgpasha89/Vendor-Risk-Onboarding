import unittest

from evals.runner import run_all


class EvalGate(unittest.TestCase):
    def test_quick_eval_suite_meets_every_threshold(self):
        rep = run_all(quick=True)
        self.assertTrue(rep["passed"], rep["failures"])


if __name__ == "__main__":
    unittest.main()
