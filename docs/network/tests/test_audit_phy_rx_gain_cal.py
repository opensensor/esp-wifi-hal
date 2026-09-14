import unittest
import audit_phy_rx_gain_cal as audit
from test_audit_phy_init import symbol,append_input

def fixture(chip='esp32c3',mode='source'):
 b={'chip':chip,'allocations':{'libphy.a':{'inputs':[]}}};s={}
 for i,(old,new) in enumerate(audit.SELECTED[chip].items()):
  a=0x42002000+i*64;s[old]=symbol(a);s[new]=symbol(a) if mode=='source' else None
  if mode=='vendor':append_input(b,'phy_rx_cal.o','.text.'+old,a,32)
 for i,name in enumerate(audit.RETAINED[chip]):
  a=0x42003000+i*64;s[name]=symbol(a);append_input(b,'phy_rx_cal.o','.text.'+name,a,32)
 return b,s
class Tests(unittest.TestCase):
 def test_both_chips_and_stages(self):
  for chip in audit.SELECTED:
   for mode in ('source','vendor'):audit.check_rx_gain_cal(*fixture(chip,mode),mode)
 def test_stage(self):
  with self.assertRaises(ValueError):audit.check_rx_gain_cal(*fixture(),'auto')
 def test_aliases(self):
  for chip in audit.SELECTED:
   for old in audit.SELECTED[chip]:
    b,s=fixture(chip);s[old]['address']='0x42009900'
    with self.assertRaises(ValueError):audit.check_rx_gain_cal(b,s,'source')
 def test_body_extent_and_kind(self):
  for name in audit.SELECTED['esp32c3'].values():
   for field,value in [('allocated',False),('executable',False),('body_contained',False),('type','STT_OBJECT'),('symbol_size_bytes',0)]:
    b,s=fixture();s[name][field]=value
    with self.assertRaises(ValueError):audit.check_rx_gain_cal(b,s,'source')
 def test_original_sections(self):
  for chip in audit.SELECTED:
   for name in audit.SELECTED[chip]:
    for prefix in ('.text.','.literal.'):
     b,s=fixture(chip);append_input(b,'phy_rx_cal.o',prefix+name)
     with self.assertRaises(ValueError):audit.check_rx_gain_cal(b,s,'source')
 def test_source_overlap(self):
  b,s=fixture();append_input(b,'wrong.o','.text',0x42002001,12)
  with self.assertRaises(ValueError):audit.check_rx_gain_cal(b,s,'source')
 def test_c3_entire_member_absent(self):
  for section in ('.rodata','.data','.text.unselected'):
   b,s=fixture();append_input(b,'phy_rx_cal.o',section)
   with self.assertRaises(ValueError):audit.check_rx_gain_cal(b,s,'source')
 def test_c3_strings_absent(self):
  b,s=fixture();b['excluded_mergeable_string_inputs']=[dict(member='phy_rx_cal.o',reported_input_bytes=4)]
  with self.assertRaises(ValueError):audit.check_rx_gain_cal(b,s,'source')
 def test_s3_spur_dependencies(self):
  for name in audit.RETAINED['esp32s3']:
   b,s=fixture('esp32s3');s[name]['address']='0x42009900'
   with self.assertRaises(ValueError):audit.check_rx_gain_cal(b,s,'source')
 def test_vendor_owner(self):
  b,s=fixture(mode='vendor');b['allocations']['libphy.a']['inputs'][0]['member']='wrong.o'
  with self.assertRaises(ValueError):audit.check_rx_gain_cal(b,s,'vendor')
 def test_vendor_rejects_source(self):
  b,s=fixture(mode='vendor');s[next(iter(audit.SELECTED['esp32c3'].values()))]=symbol(0x42008000)
  with self.assertRaises(ValueError):audit.check_rx_gain_cal(b,s,'vendor')
 def test_prior_transitions_remain_explicit(self):
  import importlib
  for stage,check in [('rx_controls','check_controls'),('rx_iq','check_iq'),('rf_iq','check_rf_iq'),('rx_dc','check_rx_dc'),('dc_search','check_dc_search')]:
   module=importlib.import_module('audit_phy_'+stage);make=importlib.import_module('test_audit_phy_'+stage).fixture
   for chip in ('esp32c3','esp32s3'):
    b,s=make(chip)
    for name in audit.SELECTED[chip]:s[name]['address']='0x42009900'
    with self.assertRaises(ValueError):getattr(module,check)(b,s,'source')
    getattr(module,check)(b,s,'source',rx_gain_cal_source=True)
 def test_prior_transition_preserves_spur_ownership(self):
  import audit_phy_dc_search as old
  from test_audit_phy_dc_search import fixture as make
  for name in audit.RETAINED['esp32s3']:
   b,s=make('esp32s3');s[name]['address']='0x42009900'
   with self.assertRaises(ValueError):old.check_dc_search(b,s,'source',rx_gain_cal_source=True)
if __name__=='__main__':unittest.main()
