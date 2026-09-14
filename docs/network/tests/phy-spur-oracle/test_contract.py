"""Focused ISA/ABI checks independent of the generated trace digest."""
import copy
import json
import unittest
from pathlib import Path
from machine import Machine, IntegerDivideByZero, MASK
from verify_contract import Spur, base


class Instruction(Machine):
    chip = 'esp32s3'
    read = write = get = lambda *args: None

    def run(self, left, right, dest='a2', chip='esp32s3'):
        self.chip = chip
        self.program = {0: (3, 'quos', [dest, 'a4', 'a3']), 3: (5, 'retw.n', [])}
        self.visited, self.branches, self.steps = set(), set(), 0
        self.r = self.registers()
        self.r.update(a4=left & MASK, a3=right & MASK, a2=0x12345678)
        self.execute(0, self.r, 0)
        return self.r[dest]


class Division(unittest.TestCase):
    def test_rounding_toward_zero(self):
        for a, b, expected in [(7, 3, 2), (-7, 3, -2), (7, -3, -2), (-7, -3, 2),
                                (1, -3, 0), (-1, 3, 0), (0x7fffffff, 1, 0x7fffffff),
                                (-2147483648, 1, -2147483648)]:
            with self.subTest(a=a, b=b):
                self.assertEqual(Instruction().run(a, b), expected & MASK)

    def test_overflow_wraps(self):
        self.assertEqual(Instruction().run(-2147483648, -1), 0x80000000)

    def test_zero_traps_before_destination_write(self):
        m = Instruction()
        with self.assertRaises(IntegerDivideByZero) as caught:
            m.run(80, 0)
        self.assertEqual(caught.exception.exccause, 6)
        self.assertEqual(m.r['a2'], 0x12345678)
        self.assertEqual(m.visited, {0})

    def test_operand_alias(self):
        self.assertEqual(Instruction().run(-123, 10, 'a4'), (-12) & MASK)
        self.assertEqual(Instruction().run(123, -10, 'a3'), (-12) & MASK)

    def test_wrong_architecture_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Xtensa'):
            Instruction().run(7, 3, chip='esp32c3')


class Contract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.e = json.loads(Path(__file__).with_name('esp32s3-instructions.json').read_text())

    def run_case(self, c):
        original, model = Spur(self.e), Spur(self.e)
        trace = original.run(c)
        self.assertEqual(trace, model.run(c, True))
        return trace

    def calls(self, trace, name):
        return [row[3:] for row in trace if row[:2] == ['call', name]]

    def test_scalar_narrowing_and_seventh_stack_argument(self):
        c = base(0)
        c['args'] = [0x123400ff, 0x12340080, 0x12340001, 0x12340002,
                     0x1234ffff, 0x1234abcd, 0x1234ed01]
        trace = self.run_case(c)
        self.assertEqual(self.calls(trace, 'slot_1d4'), [[MASK]])
        self.assertEqual(self.calls(trace, 'slot_50'), [[2443, 10, 48, 1], [2443, 10, 0xabcd, 1]])

    def test_disable_preserves_other_bits(self):
        c = base(0)
        c['args'][2], c['args'][4], c['parameter_enable'] = 0, 0, 0
        trace = self.run_case(c)
        self.assertEqual(self.calls(trace, 'slot_50'), [])
        self.assertEqual([r for r in trace if r[:2] == ['write', 0x6001d014]],
                         [['write', 0x6001d014, 4, c['register'] & ~0x2000]])
        self.assertEqual([r for r in trace if r[:2] == ['write', 0x6001d018]],
                         [['write', 0x6001d018, 4, c['register'] & ~0x2000]])

    def test_enable_threshold_and_force(self):
        for forced, parameter, level, enabled in [(0, 0, 255, False), (0, 1, 10, False),
                                                 (0, 1, 11, True), (1, 0, 0, True)]:
            c = base(0)
            c['args'][2], c['args'][4] = forced, 0
            c.update(parameter_enable=parameter, parameter_level=level)
            trace = self.run_case(c)
            self.assertEqual(len(self.calls(trace, 'slot_50')), int(enabled))

    def test_live_callback_mutations(self):
        c = base(0)
        c['args'][2] = 0
        c.update(parameter_enable=0, mutation=True)
        trace = self.run_case(c)
        # The lookup callback changes enable from zero before the first read.
        self.assertEqual(self.calls(trace, 'slot_50')[0][2], 48)
        callbacks = [r for r in trace if r[0] == 'call' and r[1].startswith('slot_')]
        self.assertEqual(len({r[2] // 0x1000 for r in callbacks}), len(callbacks))

    def test_wrapped_scaling_and_channel_mask(self):
        c = base(0)
        c['scale_returns'] = [0x200000, 0x200000]
        trace = self.run_case(c)
        self.assertEqual(self.calls(trace, 'slot_4c'), [[0, (-21474836) & MASK], [1, (-21474836) & MASK]])
        c['args'][0] = 32
        trace = self.run_case(c)
        self.assertEqual(self.calls(trace, 'slot_4c')[-1], [1, 0])

    def test_final_register_uses_two_snapshots(self):
        c = base(0)
        c.update(final_register_reads=[0x03000000, 0xab123456], divisor=3)
        trace = self.run_case(c)
        self.assertEqual([r for r in trace if r[:2] == ['read', 0x6001cc48]],
                         [['read', 0x6001cc48, 4, 0x03000000], ['read', 0x6001cc48, 4, 0xab123456]])
        self.assertEqual(trace[-1], ['write', 0x6001cc48, 4, 0xab0000d5])

    def test_zero_divisor_keeps_prior_effects(self):
        c = base(0)
        c['divisor'] = 0
        trace = self.run_case(c)
        self.assertEqual(trace[-1], ['exception', 6])
        self.assertEqual(len(self.calls(trace, 'slot_4c')), 2)
        self.assertFalse(any(r[:2] == ['write', 0x6001cc48] for r in trace))

    def test_first_power_sample_and_log_width(self):
        c = base(1)
        c.update(numeric_returns=[0x1234, 384], logging=0x100)
        trace = self.run_case(c)
        self.assertEqual(self.calls(trace, 'slot_f0'), [[1, 4095]])
        self.assertEqual(self.calls(trace, 'phy_printf'), [])
        self.assertEqual([r for r in trace if r[0] == 'write'][-2:],
                         [['write', 0x2302d7, 1, 0x23], ['write', 0x2302d8, 1, 24]])

    def test_minimum_ties_keep_first_associated_result(self):
        c = base(1)
        c.update(numeric_returns=[1600, 640, 3200, 640])
        trace = self.run_case(c)
        self.assertEqual(len(self.calls(trace, 'slot_f0')), 10)
        self.assertEqual(self.calls(trace, 'phy_printf'), [[0, 10, 0x12445, 100, 40]])

    def test_unsigned_minimum_and_signed_packed_byte(self):
        c = base(1)
        c.update(numeric_returns=[0x7ffffff8, 0xfffffff8, 0x80000000, 400])
        trace = self.run_case(c)
        # (-8+8)>>4 is zero and immediately accepted. The associated overflowed
        # result remains a full word for printf and narrows only at its store.
        self.assertEqual(self.calls(trace, 'phy_printf'), [[0, 0, 0x12445, 0xf8000000, 0]])

    def test_signed_square_high_and_carry(self):
        c = base(1)
        c.update(samples=[[0x80000000, 0x80000000, 0, 0, 0x80000000]], numeric_returns=[0, 0])
        trace = self.run_case(c)
        self.assertEqual(self.calls(trace, 'slot_104'), [[0xfe000000, 0], [0xffc00000, 0]])

    def test_unknown_callback_target_rejected(self):
        m = Spur(self.e)
        m.init(base(0))
        with self.assertRaisesRegex(ValueError, 'Unknown callback'):
            m.dispatch(0x71000555, lambda n: [0]*n, {}, 0)


if __name__ == '__main__':
    unittest.main()
