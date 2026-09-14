import copy,json,unittest
from pathlib import Path
import verify as v
DATA=json.loads(Path(__file__).with_name('original-instructions.json').read_text())
def events(t,kind):return [t[i:i+8] for i in range(0,len(t),8) if t[i]==kind]
class TrackingOracle(unittest.TestCase):
 def run_case(self,chip='esp32c3',op=0,**changes):
  c=v.default_case(op)
  for key,value in changes.items():c[int(key[1:])]=value
  return v.Oracle(chip,DATA[chip]).run(c)
 def test_immediate_idle_has_no_delay(self):
  for chip in DATA:
   status,t=self.run_case(chip,w17=0,w30=0x12345678);self.assertEqual(status,0);self.assertEqual(t,[7,0x6000e168,0x12345678,0,0,0,0,0])
 def test_busy_then_idle_delays_once(self):
  for chip in DATA:
   status,t=self.run_case(chip,w17=3);self.assertEqual(status,0);self.assertEqual(len(events(t,7)),4);self.assertEqual(events(t,10),[[10,0,50,0,0,0,0,0]])
 def test_permanent_busy_only_records_prefix(self):
  for chip in DATA:
   status,t=self.run_case(chip,w17=v.MASK);self.assertEqual(status,1);self.assertEqual(len(events(t,7)),64);self.assertFalse(events(t,10))
 def test_ulp_set_keeps_raw_word_for_callback(self):
  for chip in DATA:
   _,t=self.run_case(chip,1,w7=0xdeadbeef);self.assertEqual([e[3] for e in events(t,2)],[239,239]);self.assertEqual(events(t,6)[1][2:6],[97,0,6,0xdeadbeef])
 def test_ulp_set_chip_argument_width(self):
  for chip,count,value in [('esp32c3',3,0x12345678),('esp32s3',1,0x78)]:
   _,t=self.run_case(chip,1,w1=256,w2=0x12345678);self.assertEqual(len(events(t,6)),count)
   if chip=='esp32s3':self.assertEqual(events(t,6)[0][5],value)
 def test_ulp_division_rounds_toward_zero(self):
  for chip in DATA:
   for difference,want in [(-7,-1),(-5,0),(7,0),(8,1)]:
    _,t=self.run_case(chip,2,w19=(difference&65535)<<16,w20=0);self.assertEqual(events(t,6)[0][2],want&v.MASK)
 def test_ulp_compares_signed_halfword_before_byte_write(self):
  for chip in DATA:
   _,t=self.run_case(chip,2,w6=256,w25=0,w16=0);self.assertEqual(events(t,2)[0][3],0);self.assertEqual(events(t,9)[0][1:4],[1,0,0])
 def test_pll_threshold_signed_return(self):
  for chip in DATA:
   for distance in (0,9,0x80000000,v.MASK):
    _,t=self.run_case(chip,3,w4=distance);self.assertFalse(events(t,2))
 def test_pll_busy_guard_stops_after_abs(self):
  for chip in DATA:
   _,t=self.run_case(chip,3,w27=1);self.assertFalse(events(t,2));self.assertEqual(len(events(t,6)),1)
 def test_pll_busy_cleanup_surrounds_work(self):
  for chip,busy in [('esp32c3',0x321),('esp32s3',0x2a4)]:
   _,t=self.run_case(chip,3);writes=events(t,2);self.assertEqual(writes[0][1:4],[0x200000+busy,1,1]);self.assertEqual(writes[-1][1:4],[0x200000+busy,1,0]);self.assertEqual(writes[1][1],0x200004+busy)
 def test_s3_pll_debug_has_extra_masked_read(self):
  for chip in DATA:
   _,a=self.run_case(chip,3,w1=0);_,b=self.run_case(chip,3,w1=1);self.assertEqual(len(events(b,6))-len(events(a,6)),int(chip=='esp32s3'));self.assertEqual(events(b,12)[0][1],1)
 def test_power_baseline_mode_branch(self):
  for chip,offsets in [('esp32c3',(0x20c,0x20e,0x210)),('esp32s3',(0x206,0x208,0x2c4))]:
   for radio,mode,index in [(0,1,0),(1,16,1),(0,16,2),(1,1,2),(2,1,2)]:
    _,t=self.run_case(chip,4,w1=radio,w25=mode);self.assertEqual(next(e[1] for e in events(t,1) if e[2]==2),0x200000+offsets[index])
 def test_power_first_abs_read_order_differs(self):
  for chip,want in [('esp32c3',[1,1,4,1,5,6]),('esp32s3',[1,1,1,4,5,6])]:
   _,t=self.run_case(chip,4,w1=0);self.assertEqual([t[i] for i in range(0,48,8)],want)
 def test_power_apply_false_never_programs(self):
  for chip in DATA:
   _,t=self.run_case(chip,4,w2=0);self.assertFalse(events(t,2));self.assertFalse(events(t,12))
 def test_power_callback_return_narrowing_differs(self):
  for chip,want in [('esp32c3',True),('esp32s3',False)]:
   _,t=self.run_case(chip,4,w1=0,w11=256,w26=0);self.assertEqual(bool(events(t,2)),want)
 def test_offset_complete_only_reads_flags(self):
  for chip in DATA:
   _,t=self.run_case(chip,5,w28=1<<22);self.assertEqual(t,[1,0x200120,4,1<<22,0,0,0,0])
 def test_offset_voltage_threshold(self):
  for chip in DATA:
   for voltage,count in [(3299,2),(3300,0),(v.MASK,0)]:
    _,t=self.run_case(chip,5,w8=voltage);self.assertEqual(len(events(t,6)),count);self.assertEqual(events(t,2)[0][3]>>16,voltage&65535)
 def test_offset_reloads_flags_after_helper_mutation(self):
  for chip in DATA:
   _,t=self.run_case(chip,5,w15=1);reads=[e for e in events(t,1) if e[1]==0x200120];self.assertNotEqual(reads[0][3],reads[-1][3]);self.assertEqual(events(t,2)[-1][3],reads[-1][3]|1<<22)
 def test_rfcal_pointer_and_final_state(self):
  _,t=self.run_case('esp32c3',6);self.assertEqual(events(t,10)[0][1:6],[4,0x200124,15,32,0]);self.assertEqual(events(t,2)[-1][1:4],[0x200214,2,100])
 def test_s3_wrappers_narrow_arguments(self):
  for op,radio in [(7,0),(8,1)]:
   _,t=self.run_case('esp32s3',op,w1=257,w2=258,w16=0);self.assertEqual(events(t,6)[0][2:5],[radio,1,2])
 def test_table_mutation_loads_fresh_targets(self):
  for chip in DATA:
   _,t=self.run_case(chip,1,w14=v.MASK);self.assertEqual([e[1] for e in events(t,4)],[0,1,2]);self.assertEqual([e[2] for e in events(t,5)],[0,1,2])
 def test_nested_wait_reaches_busy_boundary(self):
  for chip in DATA:
   _,a=self.run_case(chip,3,w16=0);_,b=self.run_case(chip,3,w16=15);self.assertFalse(events(a,7));self.assertTrue(events(b,7))
 def test_invalid_case_shape_and_domains(self):
  o=v.Oracle('esp32c3',DATA['esp32c3'])
  for c in [[],[0]*31,[-1]*32]:
   with self.assertRaises(ValueError):o.run(c)
  for index,value in [(0,7),(16,16),(17,64),(31,1)]:
   c=v.default_case(0);c[index]=value
   with self.assertRaises(ValueError):o.run(c)
 def test_unknown_opcode(self):
  e=copy.deepcopy(DATA['esp32c3']);f=e['functions'][0];parts=f['instructions'][0].split();parts[2]='invented';f['instructions'][0]=' '.join(parts)
  with self.assertRaisesRegex(ValueError,'Unsupported'):v.Oracle('esp32c3',e)
 def test_modified_body(self):
  e=copy.deepcopy(DATA['esp32s3']);e['functions'][0]['code_hex']='ff'+e['functions'][0]['code_hex'][2:]
  with self.assertRaisesRegex(ValueError,'Code hash'):v.Oracle('esp32s3',e)
 def test_modified_instruction_bytes(self):
  e=copy.deepcopy(DATA['esp32c3']);f=e['functions'][0];parts=f['instructions'][0].split();parts[1]='f'*len(parts[1]);f['instructions'][0]=' '.join(parts)
  with self.assertRaisesRegex(ValueError,'Instruction bytes'):v.Oracle('esp32c3',e)
 def test_instruction_overlap(self):
  e=copy.deepcopy(DATA['esp32c3']);e['functions'][0]['instructions'].append(e['functions'][0]['instructions'][0])
  with self.assertRaisesRegex(ValueError,'Overlapping'):v.Oracle('esp32c3',e)
 def test_unknown_chip(self):
  with self.assertRaises(ValueError):v.Oracle('esp32',DATA['esp32c3'])
 def test_wrong_function_names(self):
  e=copy.deepcopy(DATA['esp32s3']);e['functions'][0]['name']='wrong'
  with self.assertRaisesRegex(ValueError,'Unexpected function names'):v.Oracle('esp32s3',e)
 def test_format_bytes_are_checked(self):
  e=copy.deepcopy(DATA['esp32s3']);e['strings'][0]['text']='wrong'
  with self.assertRaisesRegex(ValueError,'Format bytes'):v.Oracle('esp32s3',e)
if __name__=='__main__':unittest.main()
