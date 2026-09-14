import hashlib
import unittest
import audit_phy_reg as track
from test_audit_phy_lifecycle import append_input
from test_audit_phy_temperature import symbol

def fixture(chip='esp32c3',expected='source'):
    base={'chip':chip,'allocations':{'libphy.a':{'inputs':[]}},'excluded_mergeable_string_inputs':[]};syms={}
    for i,(old,new) in enumerate(track.SELECTED[chip].items()):
        address=(0x40380000 if new in track.IRAM else 0x4200e000)+i*32;syms[old]=symbol(address);syms[new]=symbol(address) if expected=='source' else None
        if expected=='vendor':append_input(base,'phy_reg.o','.iram1' if new in track.IRAM else '.text.'+old,address,32)
    return base,syms
class RegisterAudit(unittest.TestCase):
    def test_both_modes_and_chips(self):
        for chip in track.SELECTED:
            for mode in ['vendor','source']:track.check_reg(*fixture(chip,mode),mode)
    def test_unknown_mode(self):
        with self.assertRaises(ValueError):track.check_reg(*fixture(),'automatic')
    def test_every_member_input_rejected(self):
        for section in ['.iram1','.rodata','.data','COMMON','.text.other','.literal.get_power_db']:
            b,s=fixture();append_input(b,'phy_reg.o',section)
            with self.assertRaisesRegex(ValueError,'still has allocated'):track.check_reg(b,s,'source')
    def test_excluded_strings_rejected(self):
        b,s=fixture();b['excluded_mergeable_string_inputs']=[{'member':'phy_reg.o','reported_input_bytes':1}]
        with self.assertRaisesRegex(ValueError,'excluded mergeable'):track.check_reg(b,s,'source')
    def test_every_alias_checked(self):
        for chip in track.SELECTED:
            for old in track.SELECTED[chip]:
                b,s=fixture(chip);s[old]['address']=hex(int(s[old]['address'],0)^8)
                with self.assertRaisesRegex(ValueError,'Incorrect register programming source alias'):track.check_reg(b,s,'source')
    def test_stale_alias_sizes_are_not_body_sizes(self):
        for chip in track.SELECTED:
            b,s=fixture(chip)
            for old in track.SELECTED[chip]:s[old].update(symbol_size_bytes=0xffffffff,absolute=True,allocated=False,executable=False,type='STT_NOTYPE')
            track.check_reg(b,s,'source')
    def test_every_source_body_must_be_real_and_contained(self):
        for chip in track.SELECTED:
            for name in track.SELECTED[chip].values():
                for field,value in [('allocated',False),('body_contained',False),('symbol_size_bytes',0),('type','STT_OBJECT'),('executable',False)]:
                    b,s=fixture(chip);s[name][field]=value
                    with self.assertRaisesRegex(ValueError,'Missing allocated function'):track.check_reg(b,s,'source')
    def test_partial_vendor_overlap_rejected(self):
        b,s=fixture();append_input(b,'other.o','.data',0x40380008)
        with self.assertRaisesRegex(ValueError,'overlaps vendor'):track.check_reg(b,s,'source')
    def test_old_named_function_under_other_member_rejected(self):
        for name in track.SELECTED['esp32c3']:
            b,s=fixture();append_input(b,'other.o','.text.'+name)
            with self.assertRaisesRegex(ValueError,'Original register programming function'):track.check_reg(b,s,'source')
    def test_vendor_needs_correct_member_and_section(self):
        for field,value in [('member','other.o'),('section','.text.wrong')]:
            b,s=fixture('esp32s3','vendor');b['allocations']['libphy.a']['inputs'][0][field]=value
            with self.assertRaisesRegex(ValueError,'lacks member ownership'):track.check_reg(b,s,'vendor')
    def test_vendor_rejects_every_source_symbol(self):
        for chip in track.SELECTED:
            for name in track.ALL_SOURCE_NAMES:
                b,s=fixture(chip,'vendor');s[name]=symbol(0x42001000)
                with self.assertRaisesRegex(ValueError,'Unexpected register programming source'):track.check_reg(b,s,'vendor')
    def test_missing_alias_and_missing_body_rejected(self):
        for chip in track.SELECTED:
            for old,new in track.SELECTED[chip].items():
                b,s=fixture(chip);s.pop(old)
                with self.assertRaisesRegex(ValueError,'Incorrect register programming source alias'):track.check_reg(b,s,'source')
                b,s=fixture(chip);s.pop(new)
                with self.assertRaisesRegex(ValueError,'Missing allocated function'):track.check_reg(b,s,'source')
    def test_all_nine_source_helpers_must_stay_in_iram(self):
        for chip in track.SELECTED:
            for old,new in track.SELECTED[chip].items():
                if new not in track.IRAM:continue
                for address in [0x42010000,0x40000000,0x3fc80000,0x403ffff8]:
                    b,s=fixture(chip);s[new]['address']=hex(address);s[old]['address']=hex(address)
                    with self.assertRaisesRegex(ValueError,'must reside in IRAM'):track.check_reg(b,s,'source')
    def test_vendor_iram_requires_containing_member_input(self):
        b,s=fixture('esp32s3','vendor');b['allocations']['libphy.a']['inputs'][0]['size_bytes']=1
        with self.assertRaisesRegex(ValueError,'lacks member ownership'):track.check_reg(b,s,'vendor')


from test_audit_phy_pbus import fixture as pbus_fixture
from test_audit_phy_lifecycle import TABLE_HASH
import audit_phy_pbus as pbus
class RegisterComposition(unittest.TestCase):
    def fixture(self,chip='esp32c3'):
        b,s=pbus_fixture(chip);b['allocations']['libphy.a']['inputs']=[r for r in b['allocations']['libphy.a']['inputs'] if r['section']!='.text.stop_tx_tone']
        s['__opensensor_reg_stop_tone']=s['stop_tx_tone'].copy()
        s['stop_tx_tone'].update(absolute=True,allocated=False,type='STT_NOTYPE',symbol_size_bytes=0)
        return b,s
    def check(self,b,s,**kw):pbus.check_pbus(b,s,'source',TABLE_HASH,**kw)
    def test_explicit_stage_accepts_checked_body(self):
        for chip in pbus.SELECTED:self.check(*self.fixture(chip),reg_source=True)
    def test_default_requires_vendor(self):
        with self.assertRaisesRegex(ValueError,'Missing allocated'):self.check(*self.fixture())
    def test_other_retained_helper_still_required(self):
        b,s=self.fixture();s['bb_init']=None
        with self.assertRaisesRegex(ValueError,'Missing allocated'):self.check(b,s,reg_source=True)
    def test_bad_alias(self):
        b,s=self.fixture();s['stop_tx_tone']['address']='0x40000000'
        with self.assertRaisesRegex(ValueError,'helper alias'):self.check(b,s,reg_source=True)
    def test_bad_body_and_vendor_overlap(self):
        for chip in pbus.SELECTED:
            for field,value in [('allocated',False),('body_contained',False),('executable',False),('type','STT_OBJECT'),('symbol_size_bytes',0)]:
                b,s=self.fixture(chip);s['__opensensor_reg_stop_tone'][field]=value
                with self.assertRaisesRegex(ValueError,'Missing allocated'):self.check(b,s,reg_source=True)
            b,s=self.fixture(chip);append_input(b,'other.o','.data',int(s['__opensensor_reg_stop_tone']['address'],0)+8)
            with self.assertRaisesRegex(ValueError,'overlaps vendor'):self.check(b,s,reg_source=True)
            b,s=self.fixture(chip);append_input(b,'other.o','.text.stop_tx_tone')
            with self.assertRaisesRegex(ValueError,'still allocated'):self.check(b,s,reg_source=True)
if __name__=='__main__':unittest.main()
