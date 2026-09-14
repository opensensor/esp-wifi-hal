import copy,json,unittest
import audit_phy_init as audit
import phy_init_ownership as ownership
import audit_phy_api as api
import audit_phy_pbus as pbus
import audit_phy_lifecycle as lifecycle
from test_audit_phy_temperature import symbol as function_symbol
def symbol(address,size=32,kind="STT_FUNC",executable=True):
 body=function_symbol(address,size);body.update(type=kind,executable=executable);return body
from test_audit_phy_lifecycle import append_input

def fixture(chip='esp32c3',expected='source'):
 base={'chip':chip,'allocations':{'libphy.a':{'inputs':[]}},'excluded_mergeable_string_inputs':[]};syms={}
 for i,(old,new) in enumerate(audit.SELECTED[chip].items()):
  address=(0x40380000 if old.endswith(('phy_wakeup_init','phy_close_rf')) else 0x42002000)+i*64
  syms[old]=symbol(address);syms[new]=symbol(address) if expected=='source' else None
  if expected=='vendor':append_input(base,'phy_init.o','.iram1' if address<0x42000000 else '.text.'+old,address,32)
 for i,(old,new) in enumerate(ownership.DATA.items()):
  size={'phy_param':848 if chip=='esp32c3' else 740,'g_phyFuns':4,'chip7_phy_init_ctrl':42}[old]
  body=symbol(0x3fc80000+i*4096,size=size,kind='STT_OBJECT',executable=False)
  body['body_sha256']=json.loads(ownership.INITIAL.read_text())[chip]['sha256'] if old=='phy_param' else None
  syms[old]=copy.deepcopy(body);syms[new]=copy.deepcopy(body) if expected=='source' else None
  if expected=='vendor':append_input(base,'phy_init.o','.data.'+old,int(body['address'],0),size)
 if chip=='esp32c3' and expected=='source':
  syms['__opensensor_init_rom_version']=symbol(0x3fc84000,size=1,kind='STT_OBJECT',executable=False);syms['__opensensor_init_rom_version']['body_sha256']=None
 return base,syms
class InitializationAudit(unittest.TestCase):
 def test_both_chips_and_stages(self):
  for chip in audit.SELECTED:
   for mode in ('vendor','source'):audit.check_init(*fixture(chip,mode),mode)
 def test_unknown_stage(self):
  with self.assertRaises(ValueError):audit.check_init(*fixture(),'auto')
 def test_each_member_input_is_rejected(self):
  for section in ('.iram1','.text.rf_init','.data.phy_param','.bss.g_phyFuns','COMMON','.rodata','.literal.rf_init'):
   b,s=fixture();append_input(b,'phy_init.o',section)
   with self.assertRaisesRegex(ValueError,'member.*still allocated'):audit.check_init(b,s,'source')
 def test_excluded_strings_cannot_hide_member(self):
  b,s=fixture();b['excluded_mergeable_string_inputs']=[{'member':'phy_init.o','reported_input_bytes':1}]
  with self.assertRaisesRegex(ValueError,'mergeable string'):audit.check_init(b,s,'source')
 def test_all_aliases_checked(self):
  for chip in audit.SELECTED:
   for old in audit.SELECTED[chip]:
    b,s=fixture(chip);s[old]['address']='0x42001000'
    with self.assertRaisesRegex(ValueError,'Incorrect initialization alias'):audit.check_init(b,s,'source')
 def test_stale_alias_sizes_allowed_only_with_real_body(self):
  b,s=fixture()
  for old in [*audit.SELECTED['esp32c3'],*ownership.DATA]:s[old].update(absolute=True,allocated=False,symbol_size_bytes=0xffffffff,type='STT_NOTYPE')
  audit.check_init(b,s,'source')
 def test_function_body_extent_and_kind_required(self):
  for name in audit.SELECTED['esp32c3'].values():
   for field,value in [('allocated',False),('executable',False),('body_contained',False),('type','STT_OBJECT'),('symbol_size_bytes',0)]:
    b,s=fixture();s[name][field]=value
    with self.assertRaisesRegex(ValueError,'Missing allocated function'):audit.check_init(b,s,'source')
 def test_source_state_size_alignment_and_kind_required(self):
  for old,new in ownership.DATA.items():
   for field,value in [('symbol_size_bytes',0),('address','0x3fc80001' if old!='chip7_phy_init_ctrl' else '0'),('type','STT_FUNC'),('executable',True),('body_contained',False)]:
    b,s=fixture();s[new][field]=value
    with self.assertRaises(ValueError):audit.check_init(b,s,'source')
 def test_changed_initial_state_rejected(self):
  for chip in audit.SELECTED:
   for name in ownership.DATA.values():
    b,s=fixture(chip);s[name]['body_sha256']='0'*64
    with self.assertRaisesRegex(ValueError,'defaults differ'):audit.check_init(b,s,'source')
 def test_state_aliases_checked(self):
  for old in ownership.DATA:
   b,s=fixture();s[old]['address']='0x3fc88000'
   with self.assertRaisesRegex(ValueError,'state alias'):audit.check_init(b,s,'source')
 def test_state_cannot_overlap_vendor_input(self):
  b,s=fixture();append_input(b,'other.o','.data',0x3fc80008,16)
  with self.assertRaisesRegex(ValueError,'state overlaps vendor'):audit.check_init(b,s,'source')
 def test_original_function_cannot_hide_in_another_member(self):
  b,s=fixture();append_input(b,'other.o','.text.rf_init')
  with self.assertRaisesRegex(ValueError,'Original initialization'):audit.check_init(b,s,'source')
 def test_iram_entries_must_stay_in_ram(self):
  for old in ('ram1_phy_wakeup_init','ram1_phy_close_rf'):
   b,s=fixture();s[old]['address']=s[audit.SELECTED['esp32c3'][old]]['address']='0x42001000'
   with self.assertRaisesRegex(ValueError,'outside IRAM'):audit.check_init(b,s,'source')
 def test_source_symbols_for_other_chip_rejected(self):
  b,s=fixture('esp32c3');s['__opensensor_init_package']=symbol(0x42008000)
  with self.assertRaisesRegex(ValueError,'Unexpected initialization'):audit.check_init(b,s,'source')
 def test_vendor_requires_code_and_data_ownership(self):
  for chip in audit.SELECTED:
   for index in range(len(audit.SELECTED[chip])+len(ownership.DATA)):
    b,s=fixture(chip,'vendor');b['allocations']['libphy.a']['inputs'][index]['member']='wrong.o'
    with self.assertRaisesRegex(ValueError,'lacks member ownership'):audit.check_init(b,s,'vendor')
 def test_vendor_rejects_any_source_symbol(self):
  for name in audit.ALL_SOURCE_NAMES:
   b,s=fixture('esp32c3','vendor');s[name]=symbol(0x42008000)
   with self.assertRaisesRegex(ValueError,'Unexpected initialization'):audit.check_init(b,s,'vendor')
 def test_rom_version_must_start_zero_as_a_single_byte(self):
  for field,value in [('symbol_size_bytes',4),('body_sha256','0'*64),('executable',True),('allocated',False)]:
   b,s=fixture();s['__opensensor_init_rom_version'][field]=value
   with self.assertRaisesRegex(ValueError,'ROM version state'):audit.check_init(b,s,'source')
 def test_init_transition_requires_previous_source_stages(self):
  b,s=fixture()
  for flags in ({},{'api_source':True},{'feature_source':True}):
   with self.assertRaisesRegex(ValueError,'requires (full lifecycle|complete API)'):lifecycle.check_lifecycle(b,s,'lifecycle','0'*64,init_source=True,**flags)

class EarlierApiTransition(unittest.TestCase):
 def test_explicit_transition_checks_new_body_and_default_is_strict(self):
  from test_audit_phy_api import fixture as api_fixture
  for chip in audit.SELECTED:
   b,s=api_fixture(chip);extra_b,extra=fixture(chip)
   b['allocations']['libphy.a']['inputs']=[r for r in b['allocations']['libphy.a']['inputs'] if r['member']!='phy_init.o'];s.update(extra)
   with self.assertRaisesRegex(ValueError,'Retained API helper'):api.check_api(b,s,'source')
   api.check_api(b,s,'source',init_source=True)
   s[audit.SELECTED[chip]['ram1_phy_wakeup_init' if chip=='esp32c3' else 'ram_phy_wakeup_init']]=None
   with self.assertRaisesRegex(ValueError,'Missing allocated function'):api.check_api(b,s,'source',init_source=True)
if __name__=='__main__':unittest.main()
