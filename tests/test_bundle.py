import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest

from scanner.bundle import value_bundle


class TestBundleValuation(unittest.TestCase):
    def test_spec_example_shape(self):
        # Camera $100, Lens1 $150, Lens2 $90, Accessories $30 -> gross $370
        v = value_bundle([100, 150, 90, 30])
        self.assertEqual(v.gross_component_value, 370.0)
        self.assertLess(v.quick_sale_bundle_value, v.gross_component_value)
        self.assertLess(v.component_breakup_value, v.gross_component_value)
        self.assertGreaterEqual(v.maximum_realistic_value, v.quick_sale_bundle_value)

    def test_no_optimistic_stacking(self):
        v = value_bundle([100, 100])
        # Sanity: nothing should exceed the raw gross sum
        self.assertLessEqual(v.maximum_realistic_value, v.gross_component_value)

    def test_handles_none_components(self):
        v = value_bundle([100, None, 50])
        self.assertEqual(v.gross_component_value, 150.0)

    def test_empty_components(self):
        v = value_bundle([])
        self.assertEqual(v.gross_component_value, 0.0)
        self.assertEqual(v.maximum_realistic_value, 0.0)


if __name__ == "__main__":
    unittest.main()
