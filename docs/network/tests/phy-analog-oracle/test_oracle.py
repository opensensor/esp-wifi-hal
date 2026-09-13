import copy,json,unittest
from pathlib import Path
import verify as v
DATA=json.loads(Path(__file__).with_name('original-instructions.json').read_text())
def events(trace,kind):return [trace[i:i+8] for i in range(0,len(trace),8) if trace[i]==kind]
class AnalogOracle(unittest.TestCase):
 def run_case(self,chip='esp32c3',op=1,**changes):
  c=v.default_case(op)
  for key,value in changes.items():c[int(key.removeprefix('w'))]=value
  return v.Oracle(chip,DATA[chip]).run(c)
 def test_measurement_preserves_raw_return(self):
  for chip in DATA:
   result,t=self.run_case(chip,0,w2=0xdeadbeef,w11=0x12345678);self.assertEqual(result,0xdeadbeef);self.assertEqual(len(events(t,6)),10)
 def test_chip_selector_three_differs(self):
  for chip,want in [('esp32c3',13),('esp32s3',11)]:
   _,t=self.run_case(chip,0,w1=259);self.assertEqual(events(t,6)[2][-1],want)
 def test_selector_narrowing_and_default(self):
  for chip in DATA:
   for selector,want in [(0,11),(257,7),(258,6),(256,11),(0xffffffff,11)]:
    _,t=self.run_case(chip,0,w1=selector);self.assertEqual(events(t,6)[2][-1],want)
 def test_cleanup_follows_read_and_delay(self):
  for chip in DATA:
   _,t=self.run_case(chip,0);k=[t[i] for i in range(0,len(t),8)];self.assertEqual(k.count(11),1)
   calls=events(t,6);self.assertEqual(calls[-3][2:7],[106,0,5,5,0]);self.assertEqual(calls[-2][2:],[97,0,8,2,2,0]);self.assertEqual(calls[-1][2:],[106,0,4,0,0,0])
 def test_callback_table_reloads(self):
  for chip in DATA:
   _,t=self.run_case(chip,0,w7=1023);self.assertEqual([e[1] for e in events(t,4)],list(range(10)))
 def test_already_calibrated_only_reads_flags(self):
  for chip in DATA:
   result,t=self.run_case(chip,w3=0x91800000);self.assertEqual(result,0);self.assertEqual(t,[1,0x200120,4,0x91800000,0,0,0,0])
 def test_control_flags_do_not_bypass(self):
  for chip in DATA:
   _,t=self.run_case(chip,w3=1<<24);self.assertEqual(len(events(t,2)),10)
 def test_calibration_output_order_and_values(self):
  for chip,second in [('esp32c3',43),('esp32s3',32)]:
   _,t=self.run_case(chip,w9=0);writes=events(t,2)
   self.assertEqual([e[1] for e in writes],list(range(0x200166,0x20016f))+[0x200120])
   self.assertEqual([e[3] for e in writes[:9]],[42,34,43,11,14,22,17,second,17])
 def test_default_mode_uses_190_and_410(self):
  for chip in DATA:
   _,t=self.run_case(chip,w4=0,w9=0);self.assertEqual([e[3] for e in events(t,2)[:5]],[42,34,34,11,11])
 def test_c3_zero_divisors_follow_div(self):
  _,t=self.run_case(w5=0,w6=0,w9=0);self.assertEqual([e[3] for e in events(t,2)[1:5]],[34,2,11,2])
 def test_divisors_cached_before_mutating_helper(self):
  a=self.run_case(w9=0)[1];b=self.run_case(w9=0,w10=1)[1]
  self.assertEqual([e[3] for e in events(a,2)[:9]],[e[3] for e in events(b,2)[:9]])
  self.assertNotEqual(events(a,2)[-1][3],events(b,2)[-1][3])
 def test_opaque_and_nested_measurement(self):
  for chip in DATA:
   _,a=self.run_case(chip,w9=0);_,b=self.run_case(chip,w9=1)
   self.assertEqual(events(a,2),events(b,2));self.assertEqual(len(events(a,6)),0);self.assertEqual(len(events(b,6)),10)
 def test_soft_double_order(self):
  for chip in DATA:
   _,t=self.run_case(chip,w9=0);self.assertEqual([e[1] for e in events(t,12)],[0,1,2,3,1,2,3])
 def test_soft_double_original_return_reused(self):
  for chip in DATA:
   _,t=self.run_case(chip,w9=0,w12=127,w13=0x12345678,w14=0x87654321)
   calls=events(t,12);self.assertEqual(calls[1][2:4],[0x12345678,0x87654321]);self.assertEqual(calls[4][2:4],[0x12345678,0x87654321])
 def test_soft_double_divisor_difference(self):
  for chip,want in [('esp32c3',156.0),('esp32s3',197.6)]:
   _,t=self.run_case(chip,w9=0);call=events(t,12)[4];self.assertEqual(call[4]|call[5]<<32,v.float_bits(want))
 def test_narrow_then_signed_clamp(self):
  for raw,want in [(0,2),(1,2),(2,2),(63,63),(64,63),(32767,63),(32768,2),(65535,2),(65538,2)]:
   _,t=self.run_case(w9=0,w12=127,w13=raw,w14=0);writes=events(t,2);self.assertEqual(writes[5][3],want);self.assertEqual(writes[7][3],want)
 def test_final_flag_preserves_soft_callback_mutation(self):
  for chip in DATA:
   _,t=self.run_case(chip,w9=0,w15=1);self.assertEqual(events(t,2)[-1][3],(1<<24)|(1<<23))
 def test_invalid_case_shape(self):
  o=v.Oracle('esp32c3',DATA['esp32c3'])
  for c in [[],[0]*15,[0]*17,[-1]*16]:
   with self.assertRaises(ValueError):o.run(c)
 def test_invalid_case_domains(self):
  for index,value in [(0,2),(4,256),(5,65536),(6,65536),(7,1024),(8,1024),(9,2),(10,2),(12,128),(15,128)]:
   c=v.default_case(1);c[index]=value
   with self.assertRaises(ValueError):v.Oracle('esp32c3',DATA['esp32c3']).run(c)
 def test_unknown_opcode(self):
  e=copy.deepcopy(DATA['esp32c3']);e['functions'][0]['instructions'][0]=e['functions'][0]['instructions'][0].replace('addi','invented')
  with self.assertRaisesRegex(ValueError,'Unsupported'):v.Oracle('esp32c3',e)
 def test_modified_body(self):
  e=copy.deepcopy(DATA['esp32s3']);e['functions'][0]['code_hex']='ff'+e['functions'][0]['code_hex'][2:]
  with self.assertRaisesRegex(ValueError,'Code hash'):v.Oracle('esp32s3',e)
 def test_modified_instruction_bytes(self):
  e=copy.deepcopy(DATA['esp32c3']);f=e['functions'][0];parts=f['instructions'][0].split();parts[1]='ffff';f['instructions'][0]=' '.join(parts)
  with self.assertRaisesRegex(ValueError,'Instruction bytes'):v.Oracle('esp32c3',e)
 def test_instruction_overlap(self):
  e=copy.deepcopy(DATA['esp32c3']);e['functions'][0]['instructions'].append(e['functions'][0]['instructions'][0])
  with self.assertRaisesRegex(ValueError,'Overlapping'):v.Oracle('esp32c3',e)
 def test_unknown_chip(self):
  with self.assertRaises(ValueError):v.Oracle('esp32',DATA['esp32c3'])
 def test_wrong_function_names(self):
  e=copy.deepcopy(DATA['esp32s3']);e['functions'][0]['name']='wrong'
  with self.assertRaisesRegex(ValueError,'Unexpected functions'):v.Oracle('esp32s3',e)
if __name__=='__main__':unittest.main()
