import copy,hashlib,json,unittest
from pathlib import Path
import verify as v
DATA=json.loads(Path(__file__).with_name('original-instructions.json').read_text())
def events(t,k):return [t[i:i+12] for i in range(0,len(t),12) if t[i]==k]
class HardwareFrequencyOracle(unittest.TestCase):
 def run_case(self,chip,op,**changes):
  c=v.default_case(op)
  for key,value in changes.items():c[int(key[1:])]=value
  return v.Oracle(chip,DATA[chip]).run(c)[1]
 def test_busy_wait_preserves_each_poll(self):
  for chip in DATA:
   t=self.run_case(chip,0,w29=v.MASK);self.assertEqual(len(events(t,7)),33);self.assertFalse(events(t,10));self.assertTrue(all(e[2]&0x80000000 for e in events(t,7)[:-1]));self.assertFalse(events(t,7)[-1][2]&0x80000000)
 def test_disable_delay_follows_register_write(self):
  for chip in DATA:
   t=self.run_case(chip,1);self.assertEqual([e[0] for e in [t[i:i+12] for i in range(0,len(t),12)]],[7,8,10]);self.assertEqual(t[24:27],[10,0,2]);self.assertEqual(t[14],t[2]|0x02000000)
 def test_enable_clears_only_hardware_disable_bit(self):
  for chip in DATA:
   t=self.run_case(chip,2);self.assertEqual(t[14],t[2]&0xfdffffff);self.assertEqual(len(t),24)
 def test_frequency_memory_load_order_differs(self):
  c3=self.run_case('esp32c3',3);s3=self.run_case('esp32s3',3);self.assertEqual([c3[0],c3[12]],[1,7]);self.assertEqual([s3[0],s3[12]],[7,1])
 def test_frequency_memory_wraps_index_and_reloads_control(self):
  for chip in DATA:
   t=self.run_case(chip,3,w1=255,w26=0x12345678);writes=events(t,8);self.assertEqual([e[2]&255 for e in writes[::4]],[253,254,255]);self.assertEqual(len(events(t,7)),9);self.assertEqual([e[2]&0x200 for e in writes[2::4]],[0x200]*3);self.assertEqual([e[2]&0x200 for e in writes[3::4]],[0]*3)
 def test_ninth_argument_supplies_enable_bits(self):
  for chip in DATA:
   t=self.run_case(chip,4,w27=54,w40=0);self.assertEqual(next(e[2] for e in events(t,8) if e[1]==0x6000e164),1)
 def test_first_host_bank_s3_reads_mmio_before_buffer(self):
  for chip in DATA:
   t=self.run_case(chip,4,w8=1);idx=next(i for i in range(0,len(t),12) if t[i]==7 and t[i+1]==0x6000e100)
   self.assertEqual(t[idx+(12 if chip=='esp32s3' else -12)],1)
 def test_later_register_bank_load_order_differs(self):
  for chip in DATA:
   t=self.run_case(chip,4,w8=16);idx=next(i for i in range(0,len(t),12) if t[i]==7 and t[i+1]==0x6000e0f4)
   self.assertEqual(t[idx+(12 if chip=='esp32s3' else -24):idx+(12 if chip=='esp32s3' else -24)+3],[1,0x30080e,1])
 def test_zero_count_still_programs_control_and_enable_mask(self):
  for chip in DATA:
   t=self.run_case(chip,4,w8=0);self.assertEqual(len(events(t,8)),2);self.assertEqual(events(t,8)[-1][1:3],[0x6000e164,0]);self.assertFalse(events(t,1))
 def test_s3_count_is_low_byte(self):
  self.assertEqual(self.run_case('esp32s3',4,w8=257),self.run_case('esp32s3',4,w8=1));self.assertEqual(self.run_case('esp32s3',7,w8=256),self.run_case('esp32s3',7,w8=0))
 def test_c3_nonterminating_count_is_outside_bounded_harness(self):
  for op in (4,7):
   with self.assertRaisesRegex(ValueError,'count exceeds'):self.run_case('esp32c3',op,w8=256)
 def test_out_of_range_data_selectors_do_not_write_byte_lanes(self):
  for chip in DATA:
   t=self.run_case(chip,4,w8=1,w27=16,w40=2);self.assertFalse(any(e[1] in [0x6000e0c8,0x6000e0cc,0x6000e114,0x6000e118] for e in events(t,8)))
 def test_cap_memory_preserves_signed_high_bits_without_clamping(self):
  for chip in DATA:
   t=self.run_case(chip,5,w1=0x8000,w25=(0x6000e0c0*0x1021)&v.MASK);writes=events(t,8);self.assertEqual(len(writes),340);self.assertEqual(writes[1][1:3],[0x6000e148,0xfff80000]);self.assertEqual([e[2]&255 for e in writes[::4]],list(range(0,255,3)))
 def test_initialization_done_flag_skips_calls(self):
  for chip in DATA:self.assertEqual(self.run_case(chip,6,w10=32),[1,0x200120,4,32]+[0]*8)
 def test_initialization_programs_85_entries_and_three_reference_frequencies(self):
  for chip in DATA:
   t=self.run_case(chip,6);calls=events(t,10);self.assertEqual([e[3] for e in calls if e[1]==2],[2437,2400,2464]);self.assertEqual([e[2] for e in events(t,9) if e[1]==3],list(range(85)));snap=[e for e in events(t,11) if e[1]==0x310010];self.assertEqual(snap[0][3],0x87c8);self.assertEqual(snap[64][3],0x87f0)
 def test_initialization_flag_and_offset_store_order_differs(self):
  for chip in DATA:
   t=self.run_case(chip,6);end=[e[1] for e in events(t,2)[-2:]];self.assertEqual(end,[0x200120,0x2000e2] if chip=='esp32s3' else [0x2000e2,0x200120])
 def test_s3_initial_cap_write_uses_callback(self):
  t=self.run_case('esp32s3',6);self.assertEqual(events(t,6)[0][1]&0xfff,0x20c);self.assertFalse(any(e[1]==1 for e in events(t,10)))
 def test_data_collection_runs_callbacks_even_for_zero_count(self):
  for chip in DATA:
   t=self.run_case(chip,7,w8=0);self.assertEqual(len(events(t,6)),4);self.assertEqual(events(t,6)[-1][2:4],[0x200158,6]);self.assertFalse(events(t,2))
 def test_tenth_row_preserves_chip_flag(self):
  for chip,value in [('esp32c3',1),('esp32s3',0)]:
   t=self.run_case(chip,7);writes=events(t,2);self.assertEqual(next(e[3] for e in writes if e[1]==0x300009),value);self.assertEqual(next(e[3] for e in writes if e[1]==0x301409),4)
 def test_data_collection_preserves_output_write_order_with_aliasing(self):
  for chip in DATA:
   t=self.run_case(chip,7,w8=1,w28=1);self.assertEqual([e[3] for e in events(t,2)],[0,1,99,0,15,15,0,0,1])
 def test_wrapper_passes_all_nine_arguments_to_both_helpers(self):
  for chip in DATA:
   t=self.run_case(chip,8);calls=events(t,9);self.assertEqual([e[1] for e in calls],[7,4]);self.assertEqual(calls[0][2:11],[0x320000+i*0x400 for i in range(7)]+[10,0x321c00]);self.assertEqual(calls[0][2:11],calls[1][2:11])
 def test_channel_switch_stops_after_three_failed_observations(self):
  for chip in DATA:
   t=self.run_case(chip,10,w30=0,w31=0,w32=0);self.assertEqual(len([e for e in events(t,10) if e[1]==0]),3);self.assertEqual(len([e for e in events(t,7) if e[1]==0x6000e170]),3);self.assertEqual(events(t,10)[-1][1],3);self.assertEqual(events(t,2)[-1][2],2)
 def test_channel_switch_accepts_first_matching_observation(self):
  for chip in DATA:
   t=self.run_case(chip,10);self.assertEqual(len([e for e in events(t,10) if e[1]==0]),1)
 def test_channel_offset_argument_widths(self):
  for chip in DATA:
   t=self.run_case(chip,10,w2=65535,w3=256);self.assertEqual(events(t,10)[0][1:5],[6,v.MASK if chip=='esp32s3' else 65535,0 if chip=='esp32s3' else 256,0x2000e2])
 def test_callback_generations_and_state_are_reloaded(self):
  for chip in DATA:
   t=self.run_case(chip,7,w21=v.MASK);self.assertEqual([e[1] for e in events(t,4)],[0,1,2,3])
 def test_malformed_table_bytes_hash_and_ownership_rejected(self):
  for chip in DATA:
   for field,value in [('sha256','0'*64),('bytes','00'*36),('address','0x100000'),('function','unknown')]:
    e=copy.deepcopy(DATA[chip]);e['jump_tables'][0][field]=value
    with self.assertRaises(ValueError):v.Oracle(chip,e)
 def test_consistent_table_hash_cannot_escape_owner(self):
  for chip in DATA:
   e=copy.deepcopy(DATA[chip]);t=e['jump_tables'][0];t['targets'][0]='0x100000';raw=b''.join(int(a,0).to_bytes(4,'little') for a in t['targets']);t['bytes']=raw.hex();t['sha256']=hashlib.sha256(raw).hexdigest()
   with self.assertRaisesRegex(ValueError,'escapes owner'):v.Oracle(chip,e)
 def test_instruction_bytes_and_missing_code_are_rejected(self):
  for chip in DATA:
   for change in ('bytes','missing'):
    e=copy.deepcopy(DATA[chip]);f=e['functions'][0]
    if change=='bytes':f['code_hex']='00'+f['code_hex'][2:]
    else:f['instructions'].pop()
    with self.assertRaises(ValueError):v.Oracle(chip,e)
 def test_bad_case_domain(self):
  for chip in DATA:
   for axis,value in [(0,11),(28,4),(34,2),(40,4),(41,1)]:
    with self.assertRaises(ValueError):self.run_case(chip,0,**{'w'+str(axis):value})
if __name__=='__main__':unittest.main()
