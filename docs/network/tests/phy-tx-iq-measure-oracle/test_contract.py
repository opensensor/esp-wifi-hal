import json,unittest,hashlib
from pathlib import Path
import verify,machine
ROOT=Path(__file__).resolve().parent
class Contract(unittest.TestCase):
 def run_case(self,chip,kind,args,samples=None,limits=None,effects=None):
  c=dict(kind=kind,args=[v&verify.M for v in args],registers=[0xaabbccdd,0x12345678],samples=[v&verify.M for v in (samples or [200]*6)],limits=[v&verify.M for v in (limits or [4]*6)],effects=effects or [[0xb1234567,0xfedcba98,0xabcd,0x1234,i%2] for i in range(32)],log_address=0x3c00a3b8 if chip=='esp32c3' else 0x3c004e73)
  e=json.loads((ROOT/(chip+'-instructions.json')).read_text());a,b=verify.Original(chip,e,c),verify.Model(chip,e,c);a.run();b.run();self.assertEqual([a.trace,a.final()],[b.trace,b.final()]);return a
 def calls(self,a,name):return [v[2] for v in a.trace if v[:2]==['call',name]]
 def test_sample_alias_and_narrowing(self):
  for chip in ('esp32c3','esp32s3'):
   a=self.run_case(chip,0,[1,2,3,verify.OUT,verify.OUT],[0x12345678,0xabcdefff,0,0,0,0]);writes=[v for v in a.trace if v[0]=='write' and v[1]==2]
   self.assertEqual([v[-1] for v in writes],[0x5678,0xefff]);self.assertEqual(a.get(verify.OUT,2),0xefff)
 def test_register_reread_after_sampling(self):
  for chip in ('esp32c3','esp32s3'):
   a=self.run_case(chip,0,[1,2,3,verify.OUT,verify.OUT+2]);reads=[v for v in a.trace if v[:3]==['read',4,['reg',verify.REGS[0]]]];self.assertEqual([v[-1] for v in reads],[0xaabbccdd,0xb1234567])
 def test_signed_offset_narrowing_differs(self):
  rows=[self.run_case(chip,0,[0,0,0x10000,verify.OUT,verify.OUT+2]) for chip in ('esp32c3','esp32s3')]
  first=[next(v[-1] for v in a.trace if v[0]=='write') for a in rows];self.assertNotEqual(*first)
 def test_s3_extra_delay_and_argument_widths(self):
  c=self.run_case('esp32c3',1,[0x12345678,0x1234ff80,0x132,0x12340004,0],[200]*6)
  s=self.run_case('esp32s3',1,[0x12345678,0x1234ff80,0x132,0x12340004,0],[200]*6)
  self.assertEqual(self.calls(c,'ets_delay_us'),[]);self.assertEqual(self.calls(s,'ets_delay_us'),[[2]])
  self.assertEqual(self.calls(s,'start_tx_tone_step')[0],[1,0x5678,128,0,0,0]);self.assertEqual(self.calls(s,'get_power_db'),[[4]])
 def test_debug_low_byte_on_s3(self):
  c=self.run_case('esp32c3',1,[128,40,50,4,256]);s=self.run_case('esp32s3',1,[128,40,50,4,256]);self.assertEqual(len(self.calls(c,'phy_printf')),1);self.assertEqual(self.calls(s,'phy_printf'),[])
 def test_c3_live_callback_table(self):
  effects=[[0,0,0,0,(i//2)%2] for i in range(32)]
  a=self.run_case('esp32c3',1,[128,40,50,4,0],[216]*6,[4]*6,effects)
  pointers=[v[-1] for v in a.trace if v[:3]==['read',4,['table']]];self.assertEqual(set(pointers),set(verify.TABLES))
  self.assertTrue(all(v[2][1:]==[20,(-20)&verify.M] for v in a.trace if v[0]=='call' and v[1].startswith('limit')))
 def test_s3_no_limit_callback(self):
  a=self.run_case('esp32s3',1,[128,40,50,4,0],[216]*6);self.assertFalse(any(v[0]=='call' and v[1].startswith('limit') for v in a.trace))
 def test_six_attempt_limit(self):
  for chip in ('esp32c3','esp32s3'):
   a=self.run_case(chip,1,[128,40,50,4,0],[216]*6,[4]*6);self.assertEqual(len(self.calls(a,'get_power_db')),6);self.assertEqual(a.trace[-1],['return',64])
 def test_convergence_after_first_attempt(self):
  for chip in ('esp32c3','esp32s3'):
   a=self.run_case(chip,1,[128,40,50,4,1],[240,208,0,0,0,0],[10]*6);self.assertEqual(len(self.calls(a,'get_power_db')),2);self.assertEqual(a.trace[-1],['return',50])
 def test_backoff_before_logging(self):
  for chip in ('esp32c3','esp32s3'):
   a=self.run_case(chip,1,[128,40,50,4,1],[216,220,0,0,0,0],[4,4,-20,-20,-20,-20]);logs=self.calls(a,'phy_printf');self.assertEqual(logs[1][:2],[1,20])
 def test_log_format_and_original_integrity(self):
  for chip in ('esp32c3','esp32s3'):
   e=json.loads((ROOT/(chip+'-instructions.json')).read_text());row=e['logs'][0];raw=bytes.fromhex(row['bytes']);self.assertEqual(raw,b'%d, atten=%d, pwr=%d, %d, %d\n\0');self.assertEqual(hashlib.sha256(raw).hexdigest(),row['sha256']);machine.decode(e)
if __name__=='__main__':unittest.main()
