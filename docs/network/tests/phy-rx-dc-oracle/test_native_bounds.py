"""Regression checks for conservative native candidate-index proofs."""
import unittest
from native_bounds import prove


def loop(start=0, increment=1):
    return {
        0: (4, 'li', ['s9', str(start)]),
        4: (8, 'li', ['a1', '14']),
        8: (12, 'mv', ['a0', 's9']),
        12: (16, 'bltu', ['a1', 's9', '14']),
        16: (20, 'li', ['a0', '14']),
        20: (24, 'beq', ['a0', 's9', '24']),
        24: (28, 'addi', ['s9', 's9', str(increment)]),
        28: (32, 'j', ['4']),
        36: (40, 'ret', []),
    }


class NativeBoundTests(unittest.TestCase):
    def test_proves_only_the_bounded_edge(self):
        for increment in (1, 2):
            with self.subTest(increment=increment):
                result = prove(loop(increment=increment), 0, 40)
                self.assertEqual(len(result), 1)
                self.assertEqual(result[0]['address'], '0xc')
                self.assertTrue(result[0]['taken'])
                self.assertEqual(result[0]['candidate_values'], list(range(0, 15, increment)))

    def test_rejects_out_of_range_initial_state(self):
        with self.assertRaises(ValueError):
            prove(loop(start=15), 0, 40)

    def test_rejects_increment_that_skips_the_exit(self):
        with self.assertRaises(ValueError):
            prove(loop(increment=3), 0, 40)

    def test_rejects_unmodeled_control_flow(self):
        program = loop()
        program[20] = (24, 'bgez', ['s9', '24'])
        with self.assertRaisesRegex(ValueError, 'Unsupported bound-proof opcode'):
            prove(program, 0, 40)


if __name__ == '__main__':
    unittest.main()
