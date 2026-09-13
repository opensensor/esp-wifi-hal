import unittest
import audit_phy_debug as debug
from test_audit_phy_lifecycle import append_input
from test_audit_phy_temperature import symbol

def fixture(chip='esp32c3',expected='source'):
    base={'chip':chip,'allocations':{'libphy.a':{'inputs':[]}},'excluded_mergeable_string_inputs':[]};syms={}
    for i,(old,new) in enumerate(debug.SELECTED[chip].items()):
        address=0x4200e000+i*32;syms[old]=symbol(address);syms[new]=symbol(address) if expected=='source' else None
        if expected=='vendor':append_input(base,'phy_debug.o','.text.'+old,address,32)
    return base,syms
class DebugAudit(unittest.TestCase):
    def test_both_modes_and_chips(self):
        for chip in debug.SELECTED:
            for mode in ['vendor','source']:debug.check_debug(*fixture(chip,mode),mode)
    def test_unknown_mode(self):
        with self.assertRaises(ValueError):debug.check_debug(*fixture(),'automatic')
    def test_every_member_input_rejected(self):
        for section in ['.iram1','.rodata','.data','COMMON','.text.other','.literal.phy_get_vdd33']:
            b,s=fixture();append_input(b,'phy_debug.o',section)
            with self.assertRaisesRegex(ValueError,'still has allocated'):debug.check_debug(b,s,'source')
    def test_excluded_strings_rejected(self):
        b,s=fixture();b['excluded_mergeable_string_inputs']=[{'member':'phy_debug.o','reported_input_bytes':1}]
        with self.assertRaisesRegex(ValueError,'excluded mergeable'):debug.check_debug(b,s,'source')
    def test_every_alias_checked(self):
        for chip in debug.SELECTED:
            for old in debug.SELECTED[chip]:
                b,s=fixture(chip);s[old]['address']='0x40380000'
                with self.assertRaisesRegex(ValueError,'Incorrect debug source alias'):debug.check_debug(b,s,'source')
    def test_stale_alias_sizes_are_not_body_sizes(self):
        for chip in debug.SELECTED:
            b,s=fixture(chip)
            for old in debug.SELECTED[chip]:s[old].update(symbol_size_bytes=0xffffffff,absolute=True,allocated=False,executable=False,type='STT_NOTYPE')
            debug.check_debug(b,s,'source')
    def test_every_source_body_must_be_real_and_contained(self):
        for name in debug.ALL_SOURCE_NAMES:
            for field,value in [('allocated',False),('body_contained',False),('symbol_size_bytes',0),('type','STT_OBJECT'),('executable',False)]:
                b,s=fixture();s[name][field]=value
                with self.assertRaisesRegex(ValueError,'Missing allocated function'):debug.check_debug(b,s,'source')
    def test_partial_vendor_overlap_rejected(self):
        b,s=fixture();append_input(b,'other.o','.data',0x4200e008)
        with self.assertRaisesRegex(ValueError,'overlaps vendor'):debug.check_debug(b,s,'source')
    def test_old_named_function_under_other_member_rejected(self):
        for name in debug.SELECTED['esp32c3']:
            b,s=fixture();append_input(b,'other.o','.text.'+name)
            with self.assertRaisesRegex(ValueError,'Original debug function'):debug.check_debug(b,s,'source')
    def test_vendor_needs_correct_member_and_section(self):
        for field,value in [('member','other.o'),('section','.text.wrong')]:
            b,s=fixture('esp32s3','vendor');b['allocations']['libphy.a']['inputs'][0][field]=value
            with self.assertRaisesRegex(ValueError,'lacks member ownership'):debug.check_debug(b,s,'vendor')
    def test_vendor_rejects_every_source_symbol(self):
        for chip in debug.SELECTED:
            for name in debug.ALL_SOURCE_NAMES:
                b,s=fixture(chip,'vendor');s[name]=symbol(0x42001000)
                with self.assertRaisesRegex(ValueError,'Unexpected debug source'):debug.check_debug(b,s,'vendor')
    def test_missing_alias_and_missing_body_rejected(self):
        for chip in debug.SELECTED:
            for old,new in debug.SELECTED[chip].items():
                b,s=fixture(chip);s.pop(old)
                with self.assertRaisesRegex(ValueError,'Incorrect debug source alias'):debug.check_debug(b,s,'source')
                b,s=fixture(chip);s.pop(new)
                with self.assertRaisesRegex(ValueError,'Missing allocated function'):debug.check_debug(b,s,'source')
if __name__=='__main__':unittest.main()
