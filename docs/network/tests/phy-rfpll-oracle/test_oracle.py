import copy,json,unittest
from pathlib import Path
import verify as v
DATA=json.loads(Path(__file__).with_name('original-instructions.json').read_text())
def events(t,kind):return [t[i:i+12] for i in range(0,len(t),12) if t[i]==kind]
class RfPllOracle(unittest.TestCase):
 def run_case(self,chip,op,**changes):
  c=v.default_case(op)
  for key,value in changes.items():c[int(key[1:])]=value
  return v.Oracle(chip,DATA[chip]).run(c)
 def test_restart_order(self):
  for chip in DATA:
   _,t=self.run_case(chip,0);self.assertEqual([e[5:8] for e in events(t,6)],[[6,6,1],[5,5,0],[5,5,1],[6,6,0]])
 def test_sdm_reloads_buffer_after_callback(self):
  for chip in DATA:
   _,t=self.run_case(chip,1,w21=v.MASK);reads=events(t,1);self.assertEqual([e[1] for e in reads],[0x300000,0x300001,0x300002]);self.assertNotEqual(reads[0][3],0x34)
 def test_selector_three_differs(self):
  got=[]
  for chip in DATA:
   _,t=self.run_case(chip,3,w1=2484,w2=3,w3=0);got.append([e[3] for e in events(t,2)])
  self.assertEqual(got,[[37,0,0],[50,204,204]])
 def test_c3_selector_wraps_low_byte(self):
  for chip in DATA:
   self.assertEqual(self.run_case(chip,3,w2=1),self.run_case(chip,3,w2=257))
 def test_s3_offset_narrows(self):
  self.assertEqual(self.run_case('esp32s3',3,w3=v.MASK),self.run_case('esp32s3',3,w3=65535))
  self.assertNotEqual(self.run_case('esp32c3',3,w3=v.MASK),self.run_case('esp32c3',3,w3=65535))
 def test_wait_delays_before_first_read(self):
  for chip in DATA:
   _,t=self.run_case(chip,2,w17=0);self.assertEqual(t[:3],[10,0,20]);self.assertEqual(len(events(t,6)),1);self.assertFalse(events(t,12))
 def test_hundredth_success_has_no_timeout(self):
  for chip in DATA:
   _,t=self.run_case(chip,2,w17=99);self.assertEqual(len(events(t,6)),100);self.assertFalse(events(t,12))
 def test_timeout_exactly_100_reads(self):
  for chip in DATA:
   _,t=self.run_case(chip,2,w17=100);self.assertEqual(len(events(t,6)),100);self.assertEqual(len(events(t,10)),100);self.assertEqual(events(t,12),[[12]+[0]*11])
 def test_nonzero_raw_poll_return(self):
  for chip in DATA:
   _,t=self.run_case(chip,2,w17=0,w18=0x80000000);self.assertEqual(len(events(t,6)),1)
 def test_equal_offset_has_no_mmio(self):
  for chip in DATA:
   _,t=self.run_case(chip,4,w1=4,w2=0,w30=9);self.assertEqual(len(events(t,1)),1);self.assertFalse(events(t,7));self.assertFalse(events(t,2))
 def test_offset_updates_all_85_entries(self):
  for chip in DATA:
   _,t=self.run_case(chip,4);writes=events(t,8);self.assertEqual(len(writes),340);self.assertEqual([e[2]&255 for e in writes[::4]],list(range(1,254,3)));self.assertEqual(len(events(t,7)),340);self.assertEqual(events(t,2)[-1][2],2)
 def test_write_cap_keeps_c3_high_word(self):
  for chip,want in [('esp32c3',0x123456),('esp32s3',0x56)]:
   _,t=self.run_case(chip,5,w1=0x12345678);self.assertEqual(events(t,6)[1][7],want)
 def test_read_cap_adds_then_narrows(self):
  for chip in DATA:
   result,_=self.run_case(chip,6,w5=0x1ff,w6=1);self.assertEqual(result,0x2ff)
 def test_opaque_initial_cap_return(self):
  for chip in DATA:
   _,t=self.run_case(chip,7,w23=0,w10=0xffff8000);clamp=next(e for e in events(t,6) if e[1]&0xfff==0x28);self.assertEqual(clamp[2],0xffff8002)
 def test_special_cap_stops_loop_and_restores_saved(self):
  for chip in DATA:
   _,t=self.run_case(chip,7,w25=1,w2=1,w23=0,w24=0xabcd0000)
   writes=events(t,9) if chip=='esp32c3' else [e for e in events(t,6) if e[1]&0xfff==0x20c]
   if chip=='esp32c3':writes=[e for e in writes if e[1]==5]
   self.assertEqual(len(writes),1);self.assertEqual(writes[0][2],0xabcd);self.assertEqual(events(t,12)[0][5],1)
 def test_debug_has_six_integer_arguments(self):
  for chip in DATA:
   _,t=self.run_case(chip,7);e=events(t,12)[0];self.assertEqual(e[1:8],[1,4,200,204,1,1,0])
 def test_failed_search_restores_initial_after_ten_attempts(self):
  for chip in DATA:
   result,t=self.run_case(chip,7,w14=v.MASK,w15=v.MASK);self.assertEqual(result,0);self.assertEqual(events(t,12)[0][5],10);self.assertEqual(len([e for e in events(t,6) if e[1]&0xfff==0x28]),10)
 def test_init_no_valid_cap_restores_initial(self):
  for chip in DATA:
   result,t=self.run_case(chip,8,w14=v.MASK,w15=v.MASK);self.assertEqual(result,(200<<16)|200);self.assertEqual(len([e for e in events(t,10) if e[1]==0]),21)
 def test_sw_frequency_path_preserves_full_return(self):
  for chip in DATA:
   result,t=self.run_case(chip,11,w29=32,w11=0x1234096c);self.assertEqual(result,0x1234096c);self.assertEqual(events(t,10)[0][1:5],[2,12,3,1]);self.assertFalse(events(t,9))
 def test_misc_pointer_and_eight_argument_contract(self):
  for chip in DATA:
   _,t=self.run_case(chip,12);e=events(t,10)[0];self.assertEqual(e[1:5],[3,0,1,0x310000]);self.assertEqual(e[8:10],[9,0]);self.assertEqual(len(events(t,13)),1)
 def test_s3_channel_change_sets_hardware_bit(self):
  _,same=self.run_case('esp32s3',13,w1=1,w23=0);_,different=self.run_case('esp32s3',13,w1=2,w23=0);self.assertFalse(events(same,7));self.assertEqual(events(different,8)[0][1:3],[0x6001c130,0x98761234|0x1000])
 def test_channel_analog_updates_state_after_helper(self):
  for chip in DATA:
   _,t=self.run_case(chip,15,w23=0,w1=255);self.assertEqual(t[-12:-8],[2,0x2001f2,1,255]);self.assertEqual(events(t,9)[0][2],v.MASK if chip=='esp32s3' else 255)
 def test_table_generation_changes_without_caching(self):
  for chip in DATA:
   _,t=self.run_case(chip,0,w19=v.MASK);self.assertEqual([e[1] for e in events(t,4)],[0,1,2,3]);self.assertEqual([e[2] for e in events(t,5)],[0,1,2,3])
 def test_voltage_stub_returns_zero(self):self.assertEqual(self.run_case('esp32s3',17),(0,[]))
 def test_bad_case_domains(self):
  o=v.Oracle('esp32c3',DATA['esp32c3'])
  for c in [[],[-1]*48,[0]*47]:
   with self.assertRaises(ValueError):o.run(c)
  for axis,value in [(0,17),(17,101),(37,3),(38,2),(39,1)]:
   c=v.default_case(0);c[axis]=value
   with self.assertRaises(ValueError):o.run(c)
 def test_unknown_opcode(self):
  e=copy.deepcopy(DATA['esp32c3']);f=e['functions'][0];parts=f['instructions'][0].split();parts[2]='invented';f['instructions'][0]=' '.join(parts)
  with self.assertRaisesRegex(ValueError,'Unsupported'):v.Oracle('esp32c3',e)
 def test_corrupt_body(self):
  e=copy.deepcopy(DATA['esp32s3']);e['functions'][0]['code_hex']='ff'+e['functions'][0]['code_hex'][2:]
  with self.assertRaisesRegex(ValueError,'Code hash'):v.Oracle('esp32s3',e)
 def test_corrupt_instruction_bytes(self):
  e=copy.deepcopy(DATA['esp32c3']);f=e['functions'][0];parts=f['instructions'][0].split();parts[1]='f'*len(parts[1]);f['instructions'][0]=' '.join(parts)
  with self.assertRaisesRegex(ValueError,'Instruction bytes'):v.Oracle('esp32c3',e)
 def test_overlapping_instruction(self):
  e=copy.deepcopy(DATA['esp32c3']);e['functions'][0]['instructions'].append(e['functions'][0]['instructions'][0])
  with self.assertRaisesRegex(ValueError,'Overlapping'):v.Oracle('esp32c3',e)
 def test_format_bytes(self):
  e=copy.deepcopy(DATA['esp32s3']);e['strings'][0]['text']='bad'
  with self.assertRaisesRegex(ValueError,'Format bytes'):v.Oracle('esp32s3',e)
if __name__=='__main__':unittest.main()
