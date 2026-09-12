import copy
import json
from pathlib import Path
import unittest
from verify import Oracle

FIXTURE = json.loads(Path(__file__).with_name('original-instructions.json').read_text())
READ = (4, 0, 0, 5, 0x8000abcd, 35, 255, 0, 0, 0)


class OriginalEvidence(unittest.TestCase):
    def oracle(self, chip, data=None):
        return Oracle(chip, data or FIXTURE['chips'][chip])

    def test_all_dac_bytes_and_sentinel(self):
        expected = {5: 0, 7: 1, 15: 2, 11: 3, 10: 4}
        for chip in FIXTURE['chips']:
            o = self.oracle(chip)
            for dac in range(256):
                self.assertEqual(o.run((0, dac, 0, 0, 0, 0, 0, 0, 0, 0)), (expected.get(dac, 5), []))

    def test_range_inclusive_edges_do_not_write(self):
        for chip in FIXTURE['chips']:
            o = self.oracle(chip)
            for index, (low, high, dac) in enumerate(((50,125,5), (20,100,7), (-10,80,15),
                                                     (-30,50,11), (-40,20,10))):
                for temperature in (low, high):
                    result, trace = o.run((1, temperature, index, 0, 0, 0, 0, 0, 0, 0))
                    self.assertEqual(result, dac)
                    self.assertTrue(all(trace[i] == 3 for i in range(0, len(trace), 9)))

    def test_range_selection_edges_write_and_preserve_result(self):
        # Use row zero to force every selection except its in-range high point.
        for chip in FIXTURE['chips']:
            o = self.oracle(chip)
            for temperature, expected in ((-30,10), (-29,11), (-10,11), (-9,15), (49,15), (126,5)):
                result, trace = o.run((1, temperature, 0, 0, 0, 0, 0, 8, 0, 0))
                self.assertEqual(result, expected)
                self.assertEqual(trace[-6:], [105,0,6,3,0,expected])
            for temperature, expected in ((79,15), (80,7), (99,7), (100,5)):
                result, trace = o.run((1, temperature, 4, 0, 0, 0, 0, 8, 0, 0))
                self.assertEqual(result, expected)
                self.assertEqual(trace[-6:], [105,0,6,3,0,expected])

    def test_original_measurement_returned_and_low_half_stored(self):
        for chip in FIXTURE['chips']:
            case = list(READ)
            case[5] = 0x80010005
            result, trace = self.oracle(chip).run(case)
            self.assertEqual(result, 0x80010005)
            self.assertEqual(trace[-9:], [2,2,0x92,5,0,0,0,0,0])

    def test_byte_abi_is_chip_specific(self):
        case = (0, 0x105, 0, 0, 0, 0, 0, 0, 0, 0)
        self.assertEqual(self.oracle('esp32c3').run(case)[0], 5)
        self.assertEqual(self.oracle('esp32s3').run(case)[0], 0)

    def test_signed_half_abi_is_chip_specific(self):
        case = (1, 0x10050, 4, 0, 0, 0, 0, 0, 0, 0)
        self.assertEqual(self.oracle('esp32c3').run(case)[0], 5)
        self.assertEqual(self.oracle('esp32s3').run(case)[0], 7)

    def test_table_reloaded_and_state_reread_after_helpers(self):
        for chip in FIXTURE['chips']:
            case = (4, 0, 0, 5, 0x8000abcd, 100, 255, 63, 4, 3)
            _, trace = self.oracle(chip).run(case)
            events = [trace[i:i+9] for i in range(0,len(trace),9)]
            self.assertEqual([e[1] for e in events if e[0] == 4], [0,1,2,3])
            self.assertEqual([e[3] for e in events if e[0] == 1], [4,3])
            calls = [e for e in events if e[0] == 6]
            self.assertEqual(calls[2][3:5], [0x8000abcd,2])
            self.assertEqual(calls[3][3:9], [105,0,6,3,0,5])

    def test_code_helper_can_repair_sentinel_before_table_access(self):
        for chip in FIXTURE['chips']:
            result, trace = self.oracle(chip).run((4,0,0,0,0x8000abcd,35,255,16,2,0))
            events = [trace[i:i+9] for i in range(0,len(trace),9)]
            self.assertEqual(result,35)
            self.assertIn([2,1,0xaa,5,0,0,0,0,0],events)
            self.assertEqual([e[3] for e in events if e[0] == 1],[2,2])
            self.assertTrue(all(e[2] < 30 for e in events if e[0] == 3))


class RejectMalformedEvidence(unittest.TestCase):
    def test_code_hash_changed(self):
        data = copy.deepcopy(FIXTURE['chips']['esp32c3'])
        data['functions'][0]['code_hex'] = '00' * data['functions'][0]['size_bytes']
        with self.assertRaisesRegex(ValueError, 'Code hash'):
            Oracle('esp32c3', data)

    def test_instruction_bytes_changed(self):
        data = copy.deepcopy(FIXTURE['chips']['esp32c3'])
        data['functions'][0]['instructions'][0] = data['functions'][0]['instructions'][0].replace('4795', '0000')
        with self.assertRaisesRegex(ValueError, 'Instruction bytes'):
            Oracle('esp32c3', data)

    def test_s3_reachable_block_cannot_be_omitted(self):
        data = copy.deepcopy(FIXTURE['chips']['esp32s3'])
        data['functions'][1]['instructions'] = [line for line in data['functions'][1]['instructions']
                                                if not line.startswith('4203be09:')]
        with self.assertRaisesRegex(ValueError, 'Unrecorded nonzero code'):
            Oracle('esp32s3', data)

    def test_unknown_instruction(self):
        data = copy.deepcopy(FIXTURE['chips']['esp32c3'])
        data['functions'][0]['instructions'][0] = data['functions'][0]['instructions'][0].replace('li', 'unknown')
        with self.assertRaisesRegex(ValueError, 'Unsupported instruction'):
            Oracle('esp32c3', data).run((0,5,0,0,0,0,0,0,0,0))

    def test_missing_literal(self):
        data = copy.deepcopy(FIXTURE['chips']['esp32s3'])
        data['literals'] = {}
        with self.assertRaisesRegex(ValueError, 'Unrecorded literal'):
            Oracle('esp32s3', data).run(READ)

    def test_invalid_callback_slot(self):
        data = copy.deepcopy(FIXTURE['chips']['esp32s3'])
        # Semantics validation catches unsupported slots even if a textual
        # instruction edit preserves the independently checked raw bytes.
        data['functions'][2]['instructions'] = [line.replace('a3, a3, 0x188', 'a3, a3, 0x18c')
                                                for line in data['functions'][2]['instructions']]
        with self.assertRaisesRegex(ValueError, 'Unknown callback slot'):
            Oracle('esp32s3', data).run(READ)

    def test_parameter_size(self):
        data = copy.deepcopy(FIXTURE['chips']['esp32s3'])
        data['symbols']['phy_param']['size_bytes'] = 1
        with self.assertRaisesRegex(ValueError, 'Unexpected parameter size'):
            Oracle('esp32s3', data)

    def test_sixth_row_cannot_be_invented(self):
        data = copy.deepcopy(FIXTURE['chips']['esp32s3'])
        data['attribute_bytes'] += [0]*6
        with self.assertRaisesRegex(ValueError, 'Expected five attribute rows'):
            Oracle('esp32s3', data)

    def test_index_five_is_outside_range_domain(self):
        for chip in FIXTURE['chips']:
            with self.assertRaisesRegex(ValueError, 'outside five-row domain'):
                Oracle(chip, FIXTURE['chips'][chip]).run((1,0,5,0,0,0,0,0,0,0))

    def test_unknown_dac_is_not_silently_clamped(self):
        for chip in FIXTURE['chips']:
            case = list(READ)
            case[3] = 0
            with self.assertRaisesRegex(ValueError, 'outside five-row domain'):
                Oracle(chip, FIXTURE['chips'][chip]).run(case)

    def test_mutated_invalid_index_fails(self):
        for chip in FIXTURE['chips']:
            for hooks in (16,32):
                case = list(READ)
                case[7], case[8], case[9] = hooks,5,5
                with self.assertRaisesRegex(ValueError, 'outside five-row domain'):
                    Oracle(chip, FIXTURE['chips'][chip]).run(case)


if __name__ == '__main__':
    unittest.main()
