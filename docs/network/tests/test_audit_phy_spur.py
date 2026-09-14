import importlib
import unittest
import audit_phy_spur as audit
from test_audit_phy_init import symbol, append_input


def fixture(chip='esp32s3', mode='source'):
    base = {'chip': chip, 'allocations': {'libphy.a': {'inputs': []}}}
    symbols = {}
    if chip == 'esp32s3':
        for i, (old, new) in enumerate(audit.SELECTED.items()):
            address = 0x42002000+i*64
            symbols[old] = symbol(address)
            symbols[new] = symbol(address) if mode == 'source' else None
            if mode == 'vendor':
                append_input(base, 'phy_rx_cal.o', '.text.'+old, address, 32)
    return base, symbols


class Tests(unittest.TestCase):
    def test_chips_and_stages(self):
        for chip in ('esp32c3', 'esp32s3'):
            for mode in ('source', 'vendor'):
                audit.check_spur(*fixture(chip, mode), mode)

    def test_invalid_expectation_and_chip(self):
        with self.assertRaises(ValueError):
            audit.check_spur(*fixture(), 'auto')
        with self.assertRaises(ValueError):
            audit.check_spur(*fixture('esp32'), 'source')

    def test_aliases(self):
        for old in audit.SELECTED:
            b, s = fixture()
            s[old]['address'] = '0x42009900'
            with self.assertRaises(ValueError):
                audit.check_spur(b, s, 'source')

    def test_body_extent_and_kind(self):
        for name in audit.SELECTED.values():
            for field, value in [('allocated', False), ('executable', False),
                                 ('body_contained', False), ('type', 'STT_OBJECT'),
                                 ('symbol_size_bytes', 0)]:
                b, s = fixture()
                s[name][field] = value
                with self.assertRaises(ValueError):
                    audit.check_spur(b, s, 'source')

    def test_vendor_overlap(self):
        b, s = fixture()
        append_input(b, 'wrong.o', '.text', 0x42002001, 12)
        with self.assertRaises(ValueError):
            audit.check_spur(b, s, 'source')

    def test_entire_rx_member_absent(self):
        for chip in ('esp32c3', 'esp32s3'):
            for section in ['.rodata', '.data', '.text.other', '.literal.spur_coef_cfg_new']:
                b, s = fixture(chip)
                append_input(b, 'phy_rx_cal.o', section)
                with self.assertRaises(ValueError):
                    audit.check_spur(b, s, 'source')

    def test_excluded_strings_absent(self):
        for chip in ('esp32c3', 'esp32s3'):
            b, s = fixture(chip)
            b['excluded_mergeable_string_inputs'] = [dict(member='phy_rx_cal.o', reported_input_bytes=4)]
            with self.assertRaises(ValueError):
                audit.check_spur(b, s, 'source')

    def test_vendor_owner(self):
        b, s = fixture(mode='vendor')
        b['allocations']['libphy.a']['inputs'][0]['member'] = 'wrong.o'
        with self.assertRaises(ValueError):
            audit.check_spur(b, s, 'vendor')

    def test_source_not_in_control(self):
        b, s = fixture(mode='vendor')
        s['__opensensor_spur_power'] = symbol(0x42008000)
        with self.assertRaises(ValueError):
            audit.check_spur(b, s, 'vendor')

    def test_s3_symbols_absent_on_c3(self):
        for name in [*audit.SELECTED, *audit.SELECTED.values()]:
            b, s = fixture('esp32c3')
            s[name] = symbol(0x42008000)
            with self.assertRaises(ValueError):
                audit.check_spur(b, s, 'source')

    def test_all_prior_transitions_explicit(self):
        for stage, check in [('rx_controls', 'check_controls'), ('rx_iq', 'check_iq'),
                             ('rf_iq', 'check_rf_iq'), ('rx_dc', 'check_rx_dc'),
                             ('dc_search', 'check_dc_search'), ('rx_gain_cal', 'check_rx_gain_cal')]:
            module = importlib.import_module('audit_phy_'+stage)
            make = importlib.import_module('test_audit_phy_'+stage).fixture
            for old in audit.SELECTED:
                b, s = make('esp32s3')
                # Move both spur bodies to source and remove their old allocation.
                for name in audit.SELECTED:
                    s[name]['address'] = '0x42009900'
                b['allocations']['libphy.a']['inputs'] = [r for r in b['allocations']['libphy.a']['inputs']
                                                          if r['section'] not in ['.text.'+n for n in audit.SELECTED]]
                with self.assertRaises(ValueError):
                    getattr(module, check)(b, s, 'source')
                getattr(module, check)(b, s, 'source', spur_source=True)

    def test_transition_cannot_skip_other_dependencies(self):
        import audit_phy_rx_controls as old
        from test_audit_phy_rx_controls import fixture as make
        b, s = make('esp32s3')
        s['set_rx_gain_cal_iq']['address'] = '0x42009900'
        with self.assertRaises(ValueError):
            old.check_controls(b, s, 'source', spur_source=True)

    def test_prior_transition_rejects_c3(self):
        from test_audit_phy_rx_gain_cal import fixture as make
        with self.assertRaises(ValueError):
            audit.previous.check_rx_gain_cal(*make('esp32c3'), 'source', spur_source=True)


if __name__ == '__main__':
    unittest.main()
