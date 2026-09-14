import unittest
import audit_phy_rx_controls as audit
from test_audit_phy_init import symbol,append_input
DEPENDENCIES=['rxiq_get_mis','rxiq_cover_mg_mp','rfcal_rxiq','get_rfcal_rxiq_data','pbus_rx_dco_cal','set_rx_gain_cal_iq','rx_chan_dc_sort','set_rx_gain_cal_dc']
def fixture(chip='esp32c3',mode='source'):
 b={'chip':chip,'allocations':{'libphy.a':{'inputs':[]}}};s={}
 for i,(old,new) in enumerate(audit.SELECTED.items()):
  a=0x42002000+i*64;s[old]=symbol(a);s[new]=symbol(a) if mode=='source' else None
  if mode=='vendor':append_input(b,'phy_rx_cal.o','.text.'+old,a,32)
 for i,name in enumerate(DEPENDENCIES):
  a=0x42003000+i*64;s[name]=symbol(a);append_input(b,'phy_rx_cal.o','.text.'+name,a,32)
 return b,s
class Tests(unittest.TestCase):
 def test_both_stages(self):
  for chip in ('esp32c3','esp32s3'):
   for mode in ('source','vendor'):audit.check_controls(*fixture(chip,mode),mode)
 def test_unknown_stage(self):
  with self.assertRaises(ValueError):audit.check_controls(*fixture(),'auto')
 def test_aliases(self):
  for name in audit.SELECTED:
   b,s=fixture();s[name]['address']='0x42000000'
   with self.assertRaises(ValueError):audit.check_controls(b,s,'source')
 def test_all_original_sections(self):
  for name in list(audit.SELECTED)+['rfrx_sat_rst.part.0']:
   for prefix in ('.text.','.literal.'):
    b,s=fixture();append_input(b,'phy_rx_cal.o',prefix+name)
    with self.assertRaises(ValueError):audit.check_controls(b,s,'source')
 def test_body_extent_and_kind(self):
  for name in audit.SELECTED.values():
   for field,value in [('allocated',False),('executable',False),('body_contained',False),('type','STT_OBJECT'),('symbol_size_bytes',0)]:
    b,s=fixture();s[name][field]=value
    with self.assertRaises(ValueError):audit.check_controls(b,s,'source')
 def test_vendor_overlap(self):
  b,s=fixture();append_input(b,'wrong.o','.text',0x42002001,12)
  with self.assertRaises(ValueError):audit.check_controls(b,s,'source')
 def test_retained_dependencies(self):
  for name in DEPENDENCIES:
   b,s=fixture();s[name]['address']='0x42009900'
   with self.assertRaises(ValueError):audit.check_controls(b,s,'source')
 def test_vendor_cannot_have_source(self):
  b,s=fixture(mode='vendor');s[next(iter(audit.SELECTED.values()))]=symbol(0x42004000)
  with self.assertRaises(ValueError):audit.check_controls(b,s,'vendor')
 def test_vendor_wrong_owner(self):
  b,s=fixture(mode='vendor');b['allocations']['libphy.a']['inputs'][0]['member']='wrong.o'
  with self.assertRaises(ValueError):audit.check_controls(b,s,'vendor')
if __name__=='__main__':unittest.main()
