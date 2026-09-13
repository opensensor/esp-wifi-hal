import hashlib
import unittest
import audit_phy_analog as analog
from test_audit_phy_lifecycle import append_input
from test_audit_phy_temperature import symbol

def fixture(chip='esp32c3',expected='source'):
    base={'chip':chip,'allocations':{'libphy.a':{'inputs':[]}},'excluded_mergeable_string_inputs':[]};syms={}
    for i,(old,new) in enumerate(analog.SELECTED[chip].items()):
        address=0x4200e000+i*32;syms[old]=symbol(address);syms[new]=symbol(address) if expected=='source' else None
        if expected=='vendor':append_input(base,'phy_analog_cal.o','.text.'+old,address,32)
    if chip=='esp32c3':
        for i,(old,(new,value)) in enumerate(analog.DATA.items()):
            address=0x3fc80000+i*2;body=symbol(address,2,function=False)
            body.update(writable=True,body_sha256=hashlib.sha256(value.to_bytes(2,'little')).hexdigest())
            syms[old]=body.copy();syms[new]=body.copy() if expected=='source' else None
            if expected=='vendor':append_input(base,'phy_analog_cal.o','.data.'+old,address,2)
    return base,syms
class AnalogAudit(unittest.TestCase):
    def test_both_modes_and_chips(self):
        for chip in analog.SELECTED:
            for mode in ['vendor','source']:analog.check_analog(*fixture(chip,mode),mode)
    def test_unknown_mode(self):
        with self.assertRaises(ValueError):analog.check_analog(*fixture(),'automatic')
    def test_every_member_input_rejected(self):
        for section in ['.iram1','.rodata','.data','COMMON','.text.other','.literal.get_power_db']:
            b,s=fixture();append_input(b,'phy_analog_cal.o',section)
            with self.assertRaisesRegex(ValueError,'still has allocated'):analog.check_analog(b,s,'source')
    def test_excluded_strings_rejected(self):
        b,s=fixture();b['excluded_mergeable_string_inputs']=[{'member':'phy_analog_cal.o','reported_input_bytes':1}]
        with self.assertRaisesRegex(ValueError,'excluded mergeable'):analog.check_analog(b,s,'source')
    def test_every_alias_checked(self):
        for chip in analog.SELECTED:
            for old in analog.SELECTED[chip]:
                b,s=fixture(chip);s[old]['address']='0x40380000'
                with self.assertRaisesRegex(ValueError,'Incorrect analog source alias'):analog.check_analog(b,s,'source')
    def test_stale_alias_sizes_are_not_body_sizes(self):
        for chip in analog.SELECTED:
            b,s=fixture(chip)
            for old in analog.SELECTED[chip]:s[old].update(symbol_size_bytes=0xffffffff,absolute=True,allocated=False,executable=False,type='STT_NOTYPE')
            analog.check_analog(b,s,'source')
    def test_every_source_body_must_be_real_and_contained(self):
        for name in analog.ALL_SOURCE_NAMES:
            for field,value in [('allocated',False),('body_contained',False),('symbol_size_bytes',0),('type','STT_OBJECT'),('executable',False)]:
                b,s=fixture();s[name][field]=value
                with self.assertRaisesRegex(ValueError,'Missing allocated function'):analog.check_analog(b,s,'source')
    def test_partial_vendor_overlap_rejected(self):
        b,s=fixture();append_input(b,'other.o','.data',0x4200e008)
        with self.assertRaisesRegex(ValueError,'overlaps vendor'):analog.check_analog(b,s,'source')
    def test_old_named_function_under_other_member_rejected(self):
        for name in analog.SELECTED['esp32c3']:
            b,s=fixture();append_input(b,'other.o','.text.'+name)
            with self.assertRaisesRegex(ValueError,'Original analog function'):analog.check_analog(b,s,'source')
    def test_vendor_needs_correct_member_and_section(self):
        for field,value in [('member','other.o'),('section','.text.wrong')]:
            b,s=fixture('esp32s3','vendor');b['allocations']['libphy.a']['inputs'][0][field]=value
            with self.assertRaisesRegex(ValueError,'lacks member ownership'):analog.check_analog(b,s,'vendor')
    def test_vendor_rejects_every_source_symbol(self):
        for chip in analog.SELECTED:
            for name in analog.ALL_SOURCE_NAMES:
                b,s=fixture(chip,'vendor');s[name]=symbol(0x42001000)
                with self.assertRaisesRegex(ValueError,'Unexpected analog source'):analog.check_analog(b,s,'vendor')
    def test_missing_alias_and_missing_body_rejected(self):
        for chip in analog.SELECTED:
            for old,new in analog.SELECTED[chip].items():
                b,s=fixture(chip);s.pop(old)
                with self.assertRaisesRegex(ValueError,'Incorrect analog source alias'):analog.check_analog(b,s,'source')
                b,s=fixture(chip);s.pop(new)
                with self.assertRaisesRegex(ValueError,'Missing allocated function'):analog.check_analog(b,s,'source')
    def test_divisor_metadata_and_initial_values(self):
        for mode in ['vendor','source']:
            for old,(new,_) in analog.DATA.items():
                for field,value in [('writable',False),('symbol_size_bytes',4),('allocated',False),('body_contained',False),('executable',True),('type','STT_FUNC'),('body_sha256','wrong'),('address','0x3fc80001')]:
                    b,s=fixture(expected=mode);s[new if mode=='source' else old][field]=value
                    with self.assertRaisesRegex(ValueError,'Invalid writable'):analog.check_analog(b,s,mode)
    def test_divisor_aliases_and_ownership(self):
        for old,(new,_) in analog.DATA.items():
            b,s=fixture();s[old]['address']='0x3fc81000'
            with self.assertRaisesRegex(ValueError,'Incorrect analog data alias'):analog.check_analog(b,s,'source')
            b,s=fixture();append_input(b,'other.o','.data',int(s[new]['address'],0)+1,1)
            with self.assertRaisesRegex(ValueError,'Analog data overlaps'):analog.check_analog(b,s,'source')
            b,s=fixture();append_input(b,'other.o','.data.'+old)
            with self.assertRaisesRegex(ValueError,'Original analog data input'):analog.check_analog(b,s,'source')
            b,s=fixture(expected='vendor');s[new]=symbol(0x3fc81000,2,function=False)
            with self.assertRaisesRegex(ValueError,'Unexpected analog source data'):analog.check_analog(b,s,'vendor')
            b,s=fixture(expected='vendor');b['allocations']['libphy.a']['inputs']=[r for r in b['allocations']['libphy.a']['inputs'] if r['section']!='.data.'+old]
            with self.assertRaisesRegex(ValueError,'data lacks member ownership'):analog.check_analog(b,s,'vendor')
    def test_s3_rejects_c3_data(self):
        for mode in ['source','vendor']:
            for name in set(analog.DATA)|{v[0] for v in analog.DATA.values()}:
                b,s=fixture('esp32s3',mode);s[name]=symbol(0x3fc80000,2,function=False)
                with self.assertRaisesRegex(ValueError,'Unexpected analog divisor'):analog.check_analog(b,s,mode)
    def test_divisor_overlap(self):
        b,s=fixture();left=analog.DATA['wifi_ht20'][0];right=analog.DATA['wifi_ht40'][0]
        s[right]['address']=s[left]['address'];s['wifi_ht40']['address']=s[left]['address']
        with self.assertRaisesRegex(ValueError,'divisor objects overlap'):analog.check_analog(b,s,'source')
if __name__=='__main__':unittest.main()
