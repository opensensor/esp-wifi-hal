"""Guard difficult contracts before a production RX-DC implementation exists."""
import copy
import json
import unittest

from verify_contract import DC, HERE, DATA, OUT, MASK


def machine(chip):
    return DC(chip, json.loads((HERE / (chip + '-instructions.json')).read_text()))


def estimates(scores, gates=None):
    return {'kind': 0, 'sample_count': 0xffff0001, 'unused': MASK,
            'samples': [[0x12340000 + i, 0x56780000 + i, score & MASK] for i, score in enumerate(scores)],
            'gates': gates or [[0, 0]] * 8, 'table_mutation': True}


class Contracts(unittest.TestCase):
    def test_thresholds_and_exhaustion_overwrite(self):
        for chip in ['esp32c3', 'esp32s3']:
            for score, calls, result in [(35, 1, 35), (36, 3, 36), (47, 3, 47), (48, 8, 56), (100, 8, 56)]:
                with self.subTest(chip=chip, score=score):
                    o = machine(chip)
                    o.run(estimates([score] * 8))
                    self.assertEqual(o.calls, calls)
                    words = [o.get(OUT + 4 * i, 4) for i in range(3)]
                    self.assertEqual(words, [0, 0, 56] if result == 56 else [0x12340000, 0x56780000, result])

    def test_equal_score_does_not_read_parameter_gate(self):
        for chip in ['esp32c3', 'esp32s3']:
            o = machine(chip)
            trace = o.run(estimates([100] * 8))
            self.assertFalse([r for r in trace if r[0] == 'read' and 0x230000 <= r[1] < 0x230400])

    def test_gate_is_read_after_each_estimator(self):
        for chip in ['esp32c3', 'esp32s3']:
            o = machine(chip)
            o.run(estimates([0] * 8, [[1, 0], [1, 0], [1, 1]] + [[1, 0]] * 5))
            self.assertEqual(o.calls, 3)
            self.assertEqual([o.get(OUT + i * 4, 4) for i in range(3)], [0x12340002, 0x56780002, 0])

    def test_s3_sample_count_is_narrowed_and_c3_is_not(self):
        for chip, count in [('esp32c3', 0xffff0001), ('esp32s3', 1)]:
            o = machine(chip)
            call = next(row for row in o.run(estimates([0] * 8)) if row[0] == 'call')
            self.assertEqual(call[2:4], [1, count])

    def test_callback_table_is_reloaded(self):
        for chip in ['esp32c3', 'esp32s3']:
            o = machine(chip)
            trace = o.run(estimates([100] * 8))
            targets = [row[1] for row in trace if row[0] == 'call']
            self.assertEqual(len(set(targets)), 8)
            self.assertEqual([b - a for a, b in zip(targets, targets[1:])], [0x1000] * 7)

    def test_c3_column_preference_is_carried(self):
        o, bad = machine('esp32c3'), machine('esp32c3')
        c = {'kind': 1, 'status': [2, 2, 2] + [0] * 39, 'data': [0x12340000 + i for i in range(42)],
             'abs_mode': 'abs', 'table_mutation': True}
        trace = o.run(c)
        self.assertNotEqual(trace, bad.run(c, model=True, reset_columns=True))
        self.assertEqual([o.get(DATA + i * 4, 4) for i in range(3, 6)], [0x12340000, 0x12340004, 0x12340005])
        self.assertEqual([bad.get(DATA + i * 4, 4) for i in range(3, 6)], [0x12340000, 0x12340001, 0x12340002])

    def test_s3_falls_back_to_status_two(self):
        o = machine('esp32s3')
        c = {'kind': 1, 'status': [2] + [0] * 13, 'data': [0x12340000 + i for i in range(14)],
             'abs_mode': 'abs', 'table_mutation': True}
        o.run(c)
        self.assertEqual([o.get(DATA + i * 4, 4) for i in range(14)], [0x12340000] * 14)

    def test_absolute_value_result_is_signed_byte(self):
        for chip, cells in [('esp32c3', 42), ('esp32s3', 14)]:
            o, bad = machine(chip), machine(chip)
            c = {'kind': 1, 'status': [2] + [0] * (cells - 1), 'data': [0x12340000 + i for i in range(cells)],
                 'abs_mode': 256, 'table_mutation': True}
            self.assertNotEqual(o.run(c), bad.run(c, model=True, full_abs=True))
            stride = 3 if chip == 'esp32c3' else 1
            self.assertEqual(o.get(DATA + stride * 4, 4), 0x12340000)
            self.assertEqual(bad.get(DATA + stride * 4, 4), 0x12340000 + stride)

    def test_corrupted_fixture_is_rejected(self):
        for chip in ['esp32c3', 'esp32s3']:
            evidence = json.loads((HERE / (chip + '-instructions.json')).read_text())
            altered = copy.deepcopy(evidence)
            raw = bytearray.fromhex(altered['functions'][0]['code_hex'])
            raw[0] ^= 1
            altered['functions'][0]['code_hex'] = raw.hex()
            with self.assertRaisesRegex(ValueError, 'Code hash differs'):
                DC(chip, altered)


if __name__ == '__main__':
    unittest.main()
