import copy
import json
from pathlib import Path
import unittest
from verify import Oracle

FIXTURE = json.loads(Path(__file__).with_name('original-instructions.json').read_text())
CASE = (1, 0, 0, 0, 1, 3, 1, 0x80000000, 0)


class RejectMalformedEvidence(unittest.TestCase):
    def test_code_hash_or_bytes_changed(self):
        data = copy.deepcopy(FIXTURE['chips']['esp32c3'])
        data['function']['code_hex'] = '00'
        with self.assertRaisesRegex(ValueError, 'Code bytes'):
            Oracle('esp32c3', data)

    def test_missing_literal(self):
        data = copy.deepcopy(FIXTURE['chips']['esp32s3'])
        data['literals'] = {}
        with self.assertRaisesRegex(ValueError, 'Unrecorded literal'):
            Oracle('esp32s3', data).run(CASE)

    def test_unresolved_direct_helper(self):
        data = copy.deepcopy(FIXTURE['chips']['esp32c3'])
        del data['symbols']['rom1_tsens_temp_read']
        with self.assertRaisesRegex(ValueError, 'callback target'):
            Oracle('esp32c3', data).run(CASE)

    def test_parameter_read_out_of_bounds(self):
        data = copy.deepcopy(FIXTURE['chips']['esp32s3'])
        data['symbols']['phy_param']['size_bytes'] = 0x100
        with self.assertRaisesRegex(ValueError, 'parameter size'):
            Oracle('esp32s3', data).run(CASE)

    def test_unknown_instruction(self):
        data = copy.deepcopy(FIXTURE['chips']['esp32c3'])
        data['function']['instructions'][0] = data['function']['instructions'][0].replace('addi', 'unknown')
        with self.assertRaisesRegex(ValueError, 'Unsupported instruction'):
            Oracle('esp32c3', data).run(CASE)


if __name__ == '__main__':
    unittest.main()
