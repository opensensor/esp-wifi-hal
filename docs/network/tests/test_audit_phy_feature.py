import unittest
import audit_phy_feature as feature
from test_audit_phy_lifecycle import append_input
from test_audit_phy_temperature import symbol

def fixture(chip='esp32c3',expected='source'):
    base={'chip':chip,'allocations':{'libphy.a':{'inputs':[]}},'excluded_mergeable_string_inputs':[]};syms={}
    for i,(old,new) in enumerate(feature.SELECTED[chip].items()):
        address=(0x4038b000 if old in feature.IRAM else 0x4200e000)+i*32
        syms[old]=symbol(address);syms[new]=symbol(address) if expected=='source' else None
        if expected=='vendor':append_input(base,'phy_feature.o','.iram1' if old in feature.IRAM else '.text.'+old,address,32)
    for name,(member,section) in feature.RETAINED[chip].items():
        syms[name]=symbol(0x4200f000);append_input(base,member,section,0x4200f000,32)
    for name,address in feature.ROM[chip].items():
        syms[name]=symbol(address);syms[name].update(absolute=True,allocated=False)
    return base,syms
class FeatureAudit(unittest.TestCase):
    def test_both_modes_and_chips(self):
        for chip in feature.SELECTED:
            for mode in ['vendor','source']:feature.check_feature(*fixture(chip,mode),mode)
    def test_unknown_mode(self):
        with self.assertRaises(ValueError):feature.check_feature(*fixture(),'automatic')
    def test_every_member_input_rejected(self):
        for section in ['.iram1','.rodata','.data','COMMON','.text.other','.literal.phy_11p_set']:
            b,s=fixture();append_input(b,'phy_feature.o',section)
            with self.assertRaisesRegex(ValueError,'still has allocated'):feature.check_feature(b,s,'source')
    def test_excluded_strings_rejected(self):
        b,s=fixture();b['excluded_mergeable_string_inputs']=[{'member':'phy_feature.o','reported_input_bytes':1}]
        with self.assertRaisesRegex(ValueError,'excluded mergeable'):feature.check_feature(b,s,'source')
    def test_every_alias_checked(self):
        for chip in feature.SELECTED:
            for old in feature.SELECTED[chip]:
                b,s=fixture(chip);s[old]['address']='0x40380000'
                with self.assertRaisesRegex(ValueError,'Incorrect feature source alias'):feature.check_feature(b,s,'source')
    def test_stale_alias_sizes_are_not_body_sizes(self):
        for chip in feature.SELECTED:
            b,s=fixture(chip)
            for old in feature.SELECTED[chip]:s[old].update(symbol_size_bytes=0xffffffff,absolute=True,allocated=False,executable=False,type='STT_NOTYPE')
            feature.check_feature(b,s,'source')
    def test_source_body_must_be_real_and_contained(self):
        for field,value in [('allocated',False),('body_contained',False),('symbol_size_bytes',0),('type','STT_OBJECT'),('executable',False)]:
            b,s=fixture();s['__opensensor_feature_dig'][field]=value
            with self.assertRaisesRegex(ValueError,'Missing allocated function'):feature.check_feature(b,s,'source')
    def test_reset_requires_iram_including_end(self):
        for address in [0x42001000,0x4036fff0,0x403dfff8]:
            b,s=fixture();s['phy_dig_reg_backup']['address']=s['__opensensor_feature_dig']['address']=hex(address)
            with self.assertRaisesRegex(ValueError,'outside IRAM'):feature.check_feature(b,s,'source')
    def test_partial_vendor_overlap_rejected(self):
        b,s=fixture();append_input(b,'other.o','.data',0x4038b008)
        with self.assertRaisesRegex(ValueError,'overlaps vendor'):feature.check_feature(b,s,'source')
    def test_old_named_function_under_other_member_rejected(self):
        b,s=fixture();append_input(b,'other.o','.text.phy_11p_set')
        with self.assertRaisesRegex(ValueError,'Original feature function'):feature.check_feature(b,s,'source')
    def test_vendor_needs_correct_member_and_section(self):
        for field,value in [('member','other.o'),('section','.text.wrong')]:
            b,s=fixture('esp32s3','vendor');b['allocations']['libphy.a']['inputs'][0][field]=value
            with self.assertRaisesRegex(ValueError,'lacks member ownership'):feature.check_feature(b,s,'vendor')
    def test_vendor_rejects_source_symbols(self):
        for chip in feature.SELECTED:
            b,s=fixture(chip,'vendor');s['__opensensor_feature_power']=symbol(0x42001000)
            with self.assertRaisesRegex(ValueError,'Unexpected feature source'):feature.check_feature(b,s,'vendor')
    def test_rom_backups_keep_absolute_bindings(self):
        for chip in feature.SELECTED:
            for name in feature.ROM[chip]:
                for field,value in [('address','0x40380000'),('absolute',False)]:
                    b,s=fixture(chip);s[name][field]=value
                    with self.assertRaisesRegex(ValueError,'Changed ROM backup'):feature.check_feature(b,s,'source')
    def test_rom_stale_size_is_allowed(self):
        for chip in feature.SELECTED:
            b,s=fixture(chip)
            for name in feature.ROM[chip]:s[name].update(symbol_size_bytes=441,type='STT_NOTYPE',executable=False,body_contained=False)
            feature.check_feature(b,s,'source')
    def test_power_helper_ownership_preserved(self):
        for field,value in [('member','other.o'),('section','.text.wrong')]:
            b,s=fixture();b['allocations']['libphy.a']['inputs'][-1][field]=value
            with self.assertRaisesRegex(ValueError,'Retained feature helper'):feature.check_feature(b,s,'source')
class LifecycleFeatureTransition(unittest.TestCase):
    def fixture(self,chip='esp32c3'):
        from test_audit_phy_api import LifecycleComposition
        b,s=LifecycleComposition().fixture(chip)
        b['allocations']['libphy.a']['inputs']=[r for r in b['allocations']['libphy.a']['inputs'] if r['section']!='.text.phy_dig_reg_backup']
        s['phy_dig_reg_backup']=symbol(0x4038c000);s['__opensensor_feature_dig']=symbol(0x4038c000)
        return b,s
    def check(self,b,s,**kwargs):
        from test_audit_phy_lifecycle import TABLE_HASH
        feature.lifecycle.check_lifecycle(b,s,'lifecycle',TABLE_HASH,**kwargs)
    def test_requires_complete_api_stage(self):
        with self.assertRaisesRegex(ValueError,'requires complete API'):self.check(*self.fixture(),feature_source=True)
    def test_checked_feature_allowed_but_old_api_gate_preserved(self):
        for chip in feature.SELECTED:
            b,s=self.fixture(chip);self.check(b,s,api_source=True,feature_source=True)
            with self.assertRaisesRegex(ValueError,'Missing retained vendor helper input'):self.check(b,s,api_source=True)
    def test_feature_alias_and_real_body_required(self):
        b,s=self.fixture();s['phy_dig_reg_backup']['address']='0x4038c100'
        with self.assertRaisesRegex(ValueError,'Incorrect lifecycle source alias'):self.check(b,s,api_source=True,feature_source=True)
        b,s=self.fixture();s['__opensensor_feature_dig']=None
        with self.assertRaisesRegex(ValueError,'Missing allocated function body'):self.check(b,s,api_source=True,feature_source=True)
    def test_feature_entry_iram_and_nonoverlap_required(self):
        b,s=self.fixture();s['phy_dig_reg_backup']['address']=s['__opensensor_feature_dig']['address']='0x42018000'
        with self.assertRaisesRegex(ValueError,'outside IRAM'):self.check(b,s,api_source=True,feature_source=True)
        b,s=self.fixture();append_input(b,'other.o','.iram1',0x4038c008)
        with self.assertRaisesRegex(ValueError,'Source body overlaps vendor input'):self.check(b,s,api_source=True,feature_source=True)

class TransmitGainTransition(unittest.TestCase):
    def fixture(self):
        b,s=fixture();b['allocations']['libphy.a']['inputs']=[]
        s['__opensensor_tx_gain_wifi_set']=symbol(0x4200f000)
        s['ram1_wifi_set_tx_gain'].update(type='STT_NOTYPE',absolute=True,allocated=False,executable=False,symbol_size_bytes=99999)
        return b,s
    def test_transition_requires_source_stage(self):
        with self.assertRaisesRegex(ValueError,'requires complete feature'):feature.check_feature(*self.fixture(),'vendor',tx_gain_source=True)
    def test_transition_requires_explicit_flag(self):
        b,s=self.fixture();feature.check_feature(b,s,'source',tx_gain_source=True)
        with self.assertRaisesRegex(ValueError,'Missing allocated function'):feature.check_feature(b,s,'source')
    def test_real_source_body_required(self):
        for field,value in [('allocated',False),('body_contained',False),('symbol_size_bytes',0),('type','STT_OBJECT'),('executable',False)]:
            b,s=self.fixture();s['__opensensor_tx_gain_wifi_set'][field]=value
            with self.assertRaisesRegex(ValueError,'Missing allocated function'):feature.check_feature(b,s,'source',tx_gain_source=True)
    def test_alias_required(self):
        b,s=self.fixture();s['ram1_wifi_set_tx_gain']['address']='0x4200f008'
        with self.assertRaisesRegex(ValueError,'Incorrect transmit gain helper alias'):feature.check_feature(b,s,'source',tx_gain_source=True)
    def test_overlap_rejected(self):
        b,s=self.fixture();append_input(b,'other.o','.data',0x4200f008,16)
        with self.assertRaisesRegex(ValueError,'overlaps vendor'):feature.check_feature(b,s,'source',tx_gain_source=True)
    def test_old_named_input_rejected(self):
        b,s=self.fixture();append_input(b,'other.o','.text.ram1_wifi_set_tx_gain')
        with self.assertRaisesRegex(ValueError,'Original transmit gain helper input'):feature.check_feature(b,s,'source',tx_gain_source=True)
    def test_s3_has_no_retained_transition(self):
        feature.check_feature(*fixture('esp32s3'),'source',tx_gain_source=True)

if __name__=='__main__':unittest.main()
