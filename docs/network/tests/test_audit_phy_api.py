import unittest
import audit_phy_api as api
from test_audit_phy_lifecycle import append_input, fixture as lifecycle_fixture, TABLE_HASH
from test_audit_phy_temperature import symbol

def fixture(chip='esp32c3',expected='source'):
    base={'chip':chip,'allocations':{'libphy.a':{'inputs':[]}},'excluded_mergeable_string_inputs':[]};syms={}
    for i,(old,new) in enumerate(api.SELECTED[chip].items()):
        address=(0x4038b000 if old in api.IRAM else 0x4200e000)+i*32
        syms[old]=symbol(address);syms[new]=symbol(address) if expected=='source' else None
        if expected=='vendor':append_input(base,'phy_api.o','.iram1' if old in api.IRAM else '.text.'+old,address,32)
    for i,(name,(member,section)) in enumerate(api.RETAINED[chip].items()):
        address=(0x4039b000 if section=='.iram1' else 0x4200f000)+i*32
        syms[name]=symbol(address);append_input(base,member,section,address,32)
    return base,syms

class ApiAudit(unittest.TestCase):
    def test_control_and_source_on_both_chips(self):
        for chip in api.SELECTED:
            for expected in ['vendor','source']:api.check_api(*fixture(chip,expected),expected)
    def test_unknown_mode_rejected(self):
        with self.assertRaisesRegex(ValueError,'Expected API'):api.check_api(*fixture(),'auto')
    def test_every_member_input_rejected_in_source(self):
        for section in ['.iram1','.rodata','.data','COMMON','.literal.phy_set_tx_seed','.text.phy_close_rf']:
            b,s=fixture();append_input(b,'phy_api.o',section)
            with self.assertRaisesRegex(ValueError,'phy_api.o still'):api.check_api(b,s,'source')
    def test_excluded_strings_cannot_hide_member(self):
        b,s=fixture();b['excluded_mergeable_string_inputs']=[{'member':'phy_api.o','reported_input_bytes':1}]
        with self.assertRaisesRegex(ValueError,'excluded mergeable'):api.check_api(b,s,'source')
    def test_every_alias_must_match(self):
        for chip in api.SELECTED:
            for old in api.SELECTED[chip]:
                b,s=fixture(chip);s[old]['address']='0x40380000'
                with self.subTest(chip=chip,name=old),self.assertRaisesRegex(ValueError,'Incorrect API source alias'):api.check_api(b,s,'source')
    def test_stale_alias_sizes_and_absolute_assignments_allowed(self):
        b,s=fixture()
        for old in api.SELECTED['esp32c3']:s[old].update(symbol_size_bytes=0xffffffff,absolute=True,allocated=False,executable=False,type='STT_NOTYPE')
        api.check_api(b,s,'source')
    def test_source_needs_allocated_contained_nonempty_function(self):
        for field,value in [('allocated',False),('body_contained',False),('symbol_size_bytes',0),('type','STT_OBJECT'),('executable',False)]:
            b,s=fixture();s['__opensensor_api_wakeup'][field]=value
            with self.assertRaisesRegex(ValueError,'Missing allocated function'):api.check_api(b,s,'source')
    def test_iram_includes_end_address(self):
        for address in [0x4200e000,0x4036fff0,0x403dfff8]:
            b,s=fixture();s['phy_wakeup_init']['address']=s['__opensensor_api_wakeup']['address']=hex(address)
            with self.assertRaisesRegex(ValueError,'outside IRAM'):api.check_api(b,s,'source')
    def test_vendor_overlap_rejected(self):
        b,s=fixture();append_input(b,'other.o','.data',0x4038b008)
        with self.assertRaisesRegex(ValueError,'overlaps vendor'):api.check_api(b,s,'source')
    def test_old_named_section_cannot_hide_under_another_member(self):
        b,s=fixture();append_input(b,'other.o','.text.phy_close_rf')
        with self.assertRaisesRegex(ValueError,'Original API function'):api.check_api(b,s,'source')
    def test_control_needs_original_member_and_section(self):
        for field,value in [('member','renamed.o'),('section','.text.fake')]:
            b,s=fixture('esp32s3','vendor');b['allocations']['libphy.a']['inputs'][0][field]=value
            with self.assertRaisesRegex(ValueError,'lacks member ownership'):api.check_api(b,s,'vendor')
    def test_control_rejects_source_symbol(self):
        b,s=fixture('esp32c3','vendor');s['__opensensor_api_close']=symbol(0x4038c000)
        with self.assertRaisesRegex(ValueError,'Unexpected API source'):api.check_api(b,s,'vendor')
    def test_c3_rejects_s3_seed_replacement(self):
        b,s=fixture();s['__opensensor_api_tx_seed']=symbol(0x42001000)
        with self.assertRaisesRegex(ValueError,'Unexpected API source'):api.check_api(b,s,'source')
    def test_retained_helper_requires_original_member(self):
        for chip in api.SELECTED:
            for name in api.RETAINED[chip]:
                b,s=fixture(chip);s[name]['address']='0x40381000'
                with self.subTest(chip=chip,name=name),self.assertRaisesRegex(ValueError,'Retained API helper'):api.check_api(b,s,'source')

class LifecycleComposition(unittest.TestCase):
    def fixture(self, chip='esp32c3'):
        b,s=lifecycle_fixture(chip)
        b['allocations']['libphy.a']['inputs']=[row for row in b['allocations']['libphy.a']['inputs']
            if row['member']!='phy_api.o' and row['section'].split('.',2)[-1] not in api.lifecycle.API_REPLACEMENTS]
        for i,(old,new) in enumerate(api.lifecycle.API_REPLACEMENTS.items()):
            s[old]=symbol(0x4038b000+i*32)
            s[new]=symbol(0x4038b000+i*32)
        return b,s

    def check(self,b,s,**kwargs):
        api.lifecycle.check_lifecycle(b,s,'lifecycle',TABLE_HASH,**kwargs)

    def test_explicit_api_stage_accepts_checked_source_on_both_chips(self):
        for chip in api.SELECTED:self.check(*self.fixture(chip),api_source=True)

    def test_default_still_requires_original_helpers(self):
        with self.assertRaisesRegex(ValueError,'Missing retained vendor helper input'):
            self.check(*self.fixture())

    def test_temperature_only_cannot_enable_api_replacement(self):
        with self.assertRaisesRegex(ValueError,'requires complete sensor lifecycle'):
            api.lifecycle.check_lifecycle(*self.fixture(),'temperature',TABLE_HASH,api_source=True)

    def test_bad_alias_and_missing_body_rejected(self):
        for old,new in api.lifecycle.API_REPLACEMENTS.items():
            b,s=self.fixture();s[old]['address']='0x4038a000'
            with self.assertRaisesRegex(ValueError,'Incorrect lifecycle source alias'):
                self.check(b,s,api_source=True)
            b,s=self.fixture();s[new]=None
            with self.assertRaisesRegex(ValueError,'Missing allocated function body'):
                self.check(b,s,api_source=True)

    def test_new_bodies_require_iram_and_disjoint_vendor_allocation(self):
        for old,new in api.lifecycle.API_REPLACEMENTS.items():
            b,s=self.fixture();s[old]['address']=s[new]['address']='0x4201e000'
            with self.assertRaisesRegex(ValueError,'outside IRAM'):self.check(b,s,api_source=True)
            b,s=self.fixture();append_input(b,'other.o','.iram1',int(s[new]['address'],0)+8)
            with self.assertRaisesRegex(ValueError,'Source body overlaps vendor input'):self.check(b,s,api_source=True)

    def test_every_other_retained_helper_is_still_required(self):
        for name in set(api.lifecycle.RETAINED_FUNCTIONS)-set(api.lifecycle.API_REPLACEMENTS):
            b,s=self.fixture();s[name]=None
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'Missing allocated function body'):
                self.check(b,s,api_source=True)

class HardwareFrequencyComposition(unittest.TestCase):
    def fixture(self,chip='esp32c3'):
        b,s=fixture(chip);b['allocations']['libphy.a']['inputs']=[r for r in b['allocations']['libphy.a']['inputs'] if r['member']!='phy_hw_freq.o']
        s['__opensensor_hw_freq_initialize']=s['get_rf_freq_init'].copy()
        s['get_rf_freq_init'].update(absolute=True,allocated=False,type='STT_NOTYPE',symbol_size_bytes=0)
        return b,s
    def test_explicit_stage_accepts_checked_body(self):
        for chip in api.SELECTED:api.check_api(*self.fixture(chip),'source',hw_freq_source=True)
    def test_default_still_requires_vendor_helper(self):
        with self.assertRaisesRegex(ValueError,'Missing allocated function'):api.check_api(*self.fixture(),'source')
    def test_cannot_enable_for_vendor_api(self):
        with self.assertRaisesRegex(ValueError,'requires API source'):api.check_api(*fixture(),'vendor',hw_freq_source=True)
    def test_helper_alias_and_body_and_ownership_checked(self):
        for chip in api.SELECTED:
            b,s=self.fixture(chip);s['get_rf_freq_init']['address']='0x42010000'
            with self.assertRaisesRegex(ValueError,'helper alias'):api.check_api(b,s,'source',hw_freq_source=True)
            for field,value in [('allocated',False),('executable',False),('body_contained',False),('symbol_size_bytes',0),('type','STT_OBJECT')]:
                b,s=self.fixture(chip);s['__opensensor_hw_freq_initialize'][field]=value
                with self.assertRaisesRegex(ValueError,'Missing allocated function'):api.check_api(b,s,'source',hw_freq_source=True)
            b,s=self.fixture(chip);append_input(b,'other.o','.data',int(s['__opensensor_hw_freq_initialize']['address'],0)+8)
            with self.assertRaisesRegex(ValueError,'overlaps vendor'):api.check_api(b,s,'source',hw_freq_source=True)
            b,s=self.fixture(chip);append_input(b,'other.o','.text.get_rf_freq_init')
            with self.assertRaisesRegex(ValueError,'still allocated'):api.check_api(b,s,'source',hw_freq_source=True)
    def test_other_retained_helpers_still_require_vendor_ownership(self):
        for chip in api.SELECTED:
            for name in set(api.RETAINED[chip])-{'get_rf_freq_init'}:
                b,s=self.fixture(chip);s[name]=None
                with self.assertRaisesRegex(ValueError,'Missing allocated function'):api.check_api(b,s,'source',hw_freq_source=True)

if __name__=='__main__':unittest.main()
