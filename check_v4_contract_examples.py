"""Illustrative V4 contract checks. No API, solver, file mutation or archive imports."""
from decimal import Decimal as D
import unittest


class ContractExamples(unittest.TestCase):
    def test_actual_charge_horizon(self):
        H, travel, turnaround, maximum_charge = 20, 2, 1, 3
        old_latest = H - travel - turnaround - maximum_charge
        self.assertEqual(old_latest, 14)
        self.assertLessEqual(17 + travel + turnaround + 0, H)
        self.assertGreater(17 + travel + turnaround + 1, H)

    def test_objective_examples(self):
        self.assertEqual(20 * 2 + 2 + 10 + 2, 54)
        self.assertEqual(5 * 10, 50)
        self.assertEqual(13 - 10 - 2, 1)
        self.assertEqual(12 * 5 - 5, 55)

    def test_case_012_soc(self):
        initial, reserve = D('2.722988'), D('2.5')
        arrival = initial - D('0.16982064')
        self.assertEqual(arrival, D('2.55316736'))
        self.assertGreaterEqual(arrival, reserve)
        final = arrival + D('0.95') - D('0.125632')
        self.assertEqual(final, D('3.37753536'))
        self.assertLess(arrival - D('0.125632'), reserve)

    def test_segment_subdivision(self):
        def energy(segments):
            return sum(distance * (D('0.03') + D('2') * D('0.01')) *
                       (1 + D('0.06') * wind) for distance, wind in segments)
        self.assertEqual(energy([(D('10'), D('0')), (D('2'), D('3'))]),
                         energy([(D('4'), D('0')), (D('6'), D('0')), (D('2'), D('3'))]))

    def test_epsilon_boundary(self):
        reference, model, policy, eps = D('1'), D('1.00009'), D('1.00018'), D('0.0001')
        self.assertLessEqual(model - reference, eps)
        self.assertGreater(policy - reference, eps)
        self.assertLessEqual(abs(policy - model), eps)
        # Policy-first epsilon tie can reject quality that exact comparison retains.
        self.assertEqual(min(model, policy), model)


if __name__ == '__main__':
    unittest.main(verbosity=2)
