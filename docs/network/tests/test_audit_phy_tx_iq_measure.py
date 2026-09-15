import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import audit_phy_tx_iq_measure as audit
from test_audit_phy_tx_detector import fixture as detector_fixture
from test_audit_phy_init import symbol, append_input


def fixture(chip='esp32s3', expected='source'):
    base, symbols = detector_fixture(chip)
    if expected == 'source':
        for i, (old, new) in enumerate(audit.SELECTED.items()):
            symbols[old] = symbol(0x42005000 + i * 64)
            symbols[new] = symbol(0x42005000 + i * 64)
        base['allocations']['libphy.a']['inputs'] = [
            row for row in base['allocations']['libphy.a']['inputs']
            if row['section'] not in ['.text.' + name for name in audit.SELECTED]]
    return base, symbols


def check(base, symbols, expected='source'):
    audit.previous.check_detector(base, symbols, 'source', expected_iq=expected)


class Tests(unittest.TestCase):
    def test_both_chips_and_stages(self):
        for chip in ('esp32c3', 'esp32s3'):
            for mode in ('source', 'vendor'):
                check(*fixture(chip, mode), mode)

    def test_default_detector_gate_still_requires_vendor_iq(self):
        with self.assertRaises(ValueError):
            audit.previous.check_detector(*fixture(), 'source')

    def test_invalid_iq_expectation(self):
        with self.assertRaises(ValueError):
            check(*fixture(), 'auto')

    def test_alias_and_source_body_extent(self):
        for old, new in audit.SELECTED.items():
            for field, value in [('address', '0x42009900'), ('allocated', False),
                                 ('executable', False), ('body_contained', False),
                                 ('type', 'STT_OBJECT'), ('symbol_size_bytes', 0)]:
                b, s = fixture(); s[new][field] = value
                with self.assertRaises(ValueError):
                    check(b, s)
            b, s = fixture(); s.pop(old)
            with self.assertRaises(ValueError):
                check(b, s)

    def test_original_text_literals_and_overlap_rejected(self):
        for name in audit.SELECTED:
            for prefix in ('.text.', '.literal.'):
                b, s = fixture(); append_input(b, 'phy_tx_cal.o', prefix + name)
                with self.assertRaises(ValueError):
                    check(b, s)
        b, s = fixture(); append_input(b, 'wrong.o', '.text', 0x42005001, 12)
        with self.assertRaises(ValueError):
            check(b, s)

    def test_vendor_control_owner_and_absent_source(self):
        b, s = fixture(expected='vendor')
        for row in b['allocations']['libphy.a']['inputs']:
            if row['section'] == '.text.txiq_get_mis_pwr':
                row['member'] = 'wrong.o'
        with self.assertRaises(ValueError):
            check(b, s, 'vendor')
        b, s = fixture(expected='vendor'); s['__opensensor_txiq_measure'] = symbol(0x42009000)
        with self.assertRaises(ValueError):
            check(b, s, 'vendor')

    def test_all_fourteen_remaining_vendor_bodies_required(self):
        self.assertEqual(len(audit.RETAINED), 14)
        for name in audit.RETAINED:
            b, s = fixture(); s[name] = None
            with self.assertRaises(ValueError):
                check(b, s)

    def test_detector_body_cannot_be_dropped(self):
        b, s = fixture(); s['__opensensor_tx_detector_reference'] = None
        with self.assertRaises(ValueError):
            check(b, s)

    def test_earlier_gates_cannot_be_skipped_without_elftools(self):
        with patch.dict(sys.modules, {'elftools': None, 'elftools.elf': None,
                                      'elftools.elf.elffile': None}), patch.object(
                audit.previous.allocations, 'audit', return_value={}), patch.object(
                audit.previous.previous, 'audit', side_effect=ValueError('earlier ownership failed')):
            with self.assertRaisesRegex(ValueError, 'earlier ownership failed'):
                audit.audit(Path('unopened.elf'), Path('unopened.map'), 'unit', 'source')


if __name__ == '__main__':
    unittest.main()
