import unittest
from unittest.mock import patch
from pathlib import Path
import audit_phy_tx_detector as audit
from test_audit_phy_init import symbol, append_input


def fixture(chip='esp32s3', mode='source'):
    base = {'chip': chip, 'allocations': {'libphy.a': {'inputs': []}}}
    symbols = {}
    for i, (old, new) in enumerate(audit.SELECTED.items()):
        address = 0x42002000 + i * 64
        symbols[old] = symbol(address)
        symbols[new] = symbol(address) if mode == 'source' else None
        if mode == 'vendor':
            append_input(base, 'phy_tx_cal.o', '.text.' + old, address, 32)
    for i, name in enumerate(audit.RETAINED):
        address = 0x42003000 + i * 64
        symbols[name] = symbol(address)
        append_input(base, 'phy_tx_cal.o', '.text.' + name, address, 32)
    return base, symbols


class Tests(unittest.TestCase):
    def test_both_chips_and_stages(self):
        for chip in ('esp32c3', 'esp32s3'):
            for mode in ('source', 'vendor'):
                audit.check_detector(*fixture(chip, mode), mode)

    def test_invalid_inputs(self):
        for chip, mode in [('esp32', 'source'), ('esp32s3', 'auto')]:
            with self.assertRaises(ValueError):
                audit.check_detector(*fixture(chip), mode)

    def test_alias_address(self):
        for name in audit.SELECTED:
            b, s = fixture(); s[name]['address'] = '0x42009900'
            with self.assertRaises(ValueError):
                audit.check_detector(b, s, 'source')

    def test_missing_alias(self):
        b, s = fixture(); s.pop('pwdet_ref_code')
        with self.assertRaises(ValueError):
            audit.check_detector(b, s, 'source')

    def test_alias_must_be_live_or_absolute(self):
        b, s = fixture(); s['pwdet_ref_code'].update(allocated=False, absolute=False)
        with self.assertRaises(ValueError):
            audit.check_detector(b, s, 'source')

    def test_source_body_kind_and_extent(self):
        for name in audit.SELECTED.values():
            for field, value in [('allocated', False), ('executable', False), ('body_contained', False),
                                 ('type', 'STT_OBJECT'), ('symbol_size_bytes', 0)]:
                b, s = fixture(); s[name][field] = value
                with self.assertRaises(ValueError):
                    audit.check_detector(b, s, 'source')

    def test_source_overlap(self):
        b, s = fixture(); append_input(b, 'wrong.o', '.text', 0x42002001, 12)
        with self.assertRaises(ValueError):
            audit.check_detector(b, s, 'source')

    def test_original_text_and_literals_absent(self):
        for prefix in ('.text.', '.literal.'):
            for name in audit.SELECTED:
                b, s = fixture(); append_input(b, 'phy_tx_cal.o', prefix + name)
                with self.assertRaises(ValueError):
                    audit.check_detector(b, s, 'source')

    def test_control_owner(self):
        b, s = fixture(mode='vendor'); b['allocations']['libphy.a']['inputs'][0]['member'] = 'wrong.o'
        with self.assertRaises(ValueError):
            audit.check_detector(b, s, 'vendor')

    def test_source_not_in_control(self):
        b, s = fixture(mode='vendor'); s['__opensensor_tx_detector_reference'] = symbol(0x42008000)
        with self.assertRaises(ValueError):
            audit.check_detector(b, s, 'vendor')

    def test_each_remaining_tx_body_required(self):
        for name in audit.RETAINED:
            b, s = fixture(); s[name] = None
            with self.assertRaises(ValueError):
                audit.check_detector(b, s, 'source')

    def test_remaining_tx_owner(self):
        b, s = fixture(); b['allocations']['libphy.a']['inputs'][-1]['member'] = 'wrong.o'
        with self.assertRaises(ValueError):
            audit.check_detector(b, s, 'source')

    def test_previous_gate_cannot_be_skipped(self):
        with patch.object(audit.allocations, 'audit', return_value={}), patch.object(
                audit.previous, 'audit', side_effect=ValueError('earlier ownership failed')):
            with self.assertRaisesRegex(ValueError, 'earlier ownership failed'):
                audit.audit(Path('unopened.elf'), Path('unopened.map'), 'unit', 'source')


if __name__ == '__main__':
    unittest.main()
