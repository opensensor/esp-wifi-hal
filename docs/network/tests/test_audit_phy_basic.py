import unittest
import audit_phy_basic as basic
from test_audit_phy_lifecycle import append_input
from test_audit_phy_temperature import symbol

def fixture(chip='esp32c3',expected='source'):
    base={'chip':chip,'allocations':{'libphy.a':{'inputs':[]}},'excluded_mergeable_string_inputs':[]};syms={}
    for i,(old,new) in enumerate(basic.SELECTED[chip].items()):
        address=(0x4038b000 if old in basic.IRAM else 0x4200e000)+i*32
        syms[old]=symbol(address);syms[new]=symbol(address) if expected=='source' else None
        if expected=='vendor':append_input(base,'phy_basic.o','.iram1' if old in basic.IRAM else '.text.'+old,address,32)
    syms['phy_set_most_tpw']=symbol(0x4200f000);append_input(base,'phy_feature.o','.text.phy_set_most_tpw',0x4200f000,32)
    syms['rom_set_chan_reg']=symbol(basic.ROM[chip]);syms['rom_set_chan_reg'].update(absolute=True,allocated=False)
    return base,syms
class BasicAudit(unittest.TestCase):
    def test_both_modes_and_chips(self):
        for chip in basic.SELECTED:
            for mode in ['vendor','source']:basic.check_basic(*fixture(chip,mode),mode)
    def test_unknown_mode(self):
        with self.assertRaises(ValueError):basic.check_basic(*fixture(),'automatic')
    def test_every_member_input_rejected(self):
        for section in ['.iram1','.rodata','.data','COMMON','.text.other','.literal.chan14_mic_cfg']:
            b,s=fixture();append_input(b,'phy_basic.o',section)
            with self.assertRaisesRegex(ValueError,'still has allocated'):basic.check_basic(b,s,'source')
    def test_excluded_strings_rejected(self):
        b,s=fixture();b['excluded_mergeable_string_inputs']=[{'member':'phy_basic.o','reported_input_bytes':1}]
        with self.assertRaisesRegex(ValueError,'excluded mergeable'):basic.check_basic(b,s,'source')
    def test_every_alias_checked(self):
        for chip in basic.SELECTED:
            for old in basic.SELECTED[chip]:
                b,s=fixture(chip);s[old]['address']='0x40380000'
                with self.assertRaisesRegex(ValueError,'Incorrect basic source alias'):basic.check_basic(b,s,'source')
    def test_stale_alias_sizes_are_not_body_sizes(self):
        for chip in basic.SELECTED:
            b,s=fixture(chip)
            for old in basic.SELECTED[chip]:s[old].update(symbol_size_bytes=0xffffffff,absolute=True,allocated=False,executable=False,type='STT_NOTYPE')
            basic.check_basic(b,s,'source')
    def test_source_body_must_be_real_and_contained(self):
        for field,value in [('allocated',False),('body_contained',False),('symbol_size_bytes',0),('type','STT_OBJECT'),('executable',False)]:
            b,s=fixture();s['__opensensor_basic_reset'][field]=value
            with self.assertRaisesRegex(ValueError,'Missing allocated function'):basic.check_basic(b,s,'source')
    def test_reset_requires_iram_including_end(self):
        for address in [0x42001000,0x4036fff0,0x403dfff8]:
            b,s=fixture();s['rom1_i2c_master_reset']['address']=s['__opensensor_basic_reset']['address']=hex(address)
            with self.assertRaisesRegex(ValueError,'outside IRAM'):basic.check_basic(b,s,'source')
    def test_partial_vendor_overlap_rejected(self):
        b,s=fixture();append_input(b,'other.o','.data',0x4038b008)
        with self.assertRaisesRegex(ValueError,'overlaps vendor'):basic.check_basic(b,s,'source')
    def test_old_named_function_under_other_member_rejected(self):
        b,s=fixture();append_input(b,'other.o','.text.chan14_mic_cfg')
        with self.assertRaisesRegex(ValueError,'Original basic function'):basic.check_basic(b,s,'source')
    def test_vendor_needs_correct_member_and_section(self):
        for field,value in [('member','other.o'),('section','.text.wrong')]:
            b,s=fixture('esp32s3','vendor');b['allocations']['libphy.a']['inputs'][0][field]=value
            with self.assertRaisesRegex(ValueError,'lacks member ownership'):basic.check_basic(b,s,'vendor')
    def test_vendor_and_c3_reject_unexpected_source(self):
        for mode in ['vendor','source']:
            b,s=fixture('esp32c3',mode);s['__opensensor_basic_interpolate']=symbol(0x42001000)
            with self.assertRaisesRegex(ValueError,'Unexpected basic source'):basic.check_basic(b,s,mode)
    def test_rom_channel_keeps_absolute_binding(self):
        for chip in basic.SELECTED:
            for field,value in [('address','0x40380000'),('absolute',False)]:
                b,s=fixture(chip);s['rom_set_chan_reg'][field]=value
                with self.assertRaisesRegex(ValueError,'Changed ROM channel'):basic.check_basic(b,s,'source')
    def test_rom_stale_size_is_allowed(self):
        for chip in basic.SELECTED:
            b,s=fixture(chip);s['rom_set_chan_reg'].update(symbol_size_bytes=116,type='STT_NOTYPE',executable=False,body_contained=False)
            basic.check_basic(b,s,'source')
    def test_power_helper_ownership_preserved(self):
        for field,value in [('member','other.o'),('section','.text.wrong')]:
            b,s=fixture();b['allocations']['libphy.a']['inputs'][0][field]=value
            with self.assertRaisesRegex(ValueError,'Retained basic helper'):basic.check_basic(b,s,'source')
    def test_feature_transition_requires_basic_source(self):
        with self.assertRaisesRegex(ValueError,'requires basic source'):basic.check_basic(*fixture('esp32c3','vendor'),'vendor',feature_source=True)
    def test_feature_transition_requires_real_power_body_and_alias(self):
        for chip in basic.SELECTED:
            b,s=fixture(chip)
            with self.assertRaisesRegex(ValueError,'Missing allocated function'):basic.check_basic(b,s,'source',feature_source=True)
            s['__opensensor_feature_power']=symbol(0x42010000)
            with self.assertRaisesRegex(ValueError,'Incorrect feature power alias'):basic.check_basic(b,s,'source',feature_source=True)
            s['phy_set_most_tpw']['address']='0x42010000'
            with self.assertRaisesRegex(ValueError,'Original feature power'):basic.check_basic(b,s,'source',feature_source=True)
            b['allocations']['libphy.a']['inputs'].clear()
            basic.check_basic(b,s,'source',feature_source=True)
            with self.assertRaisesRegex(ValueError,'Retained basic helper'):basic.check_basic(b,s,'source')
    def test_feature_transition_rejects_vendor_overlap(self):
        b,s=fixture();b['allocations']['libphy.a']['inputs'].clear()
        s['__opensensor_feature_power']=symbol(0x42010000);s['phy_set_most_tpw']['address']='0x42010000'
        append_input(b,'other.o','.data',0x42010008)
        with self.assertRaisesRegex(ValueError,'Feature power overlaps'):basic.check_basic(b,s,'source',feature_source=True)
if __name__=='__main__':unittest.main()
