import copy,json,unittest
from pathlib import Path
import verify as v
FIXTURE=json.loads(Path(__file__).with_name('original-instructions.json').read_text())
def events(trace,kind=None):
 rows=[trace[i:i+16] for i in range(0,len(trace),16)]
 return rows if kind is None else [r for r in rows if r[0]==kind]
class InitializationOracle(unittest.TestCase):
 def run_case(self,chip,kind,**changes):
  c=v.default_case(kind)
  for key,value in changes.items():c[int(key)]=value
  return v.Oracle(chip,FIXTURE[chip]).run(c)
 def test_all_original_instructions_decode(self):
  for chip,count in [('esp32c3',1178),('esp32s3',1075)]:self.assertEqual(len(v.Oracle(chip,FIXTURE[chip]).program),count)
 def test_code_bytes_and_hash_checked(self):
  for chip in FIXTURE:
   e=copy.deepcopy(FIXTURE[chip]);f=e['functions'][0];f['code_hex']='00'+f['code_hex'][2:]
   with self.assertRaisesRegex(ValueError,'Code hash'):v.Oracle(chip,e)
 def test_instruction_encoding_must_match_body(self):
  e=copy.deepcopy(FIXTURE['esp32s3']);f=e['functions'][0];words=f['instructions'][0].split();words[1]='000000';f['instructions'][0]=' '.join(words)
  with self.assertRaisesRegex(ValueError,'Instruction bytes'):v.Oracle('esp32s3',e)
 def test_unknown_opcode_rejected(self):
  e=copy.deepcopy(FIXTURE['esp32c3']);f=e['functions'][0];f['instructions'][0]=f['instructions'][0].replace('addi','invented',1)
  with self.assertRaisesRegex(ValueError,'Unsupported instruction'):v.Oracle('esp32c3',e)
 def test_readonly_hash_and_extent_checked(self):
  for chip in FIXTURE:
   for field,value in [('size_bytes',0),('sha256','0'*64)]:
    e=copy.deepcopy(FIXTURE[chip]);e['readonly'][0][field]=value
    with self.assertRaisesRegex(ValueError,'Readonly hash'):v.Oracle(chip,e)
 def test_unknown_function_rejected(self):
  with self.assertRaisesRegex(ValueError,'Unknown function'):self.run_case('esp32c3',99)
 def test_state_extent_checked(self):
  e=copy.deepcopy(FIXTURE['esp32s3']);e['symbols']['phy_param']['size_bytes']=848
  with self.assertRaisesRegex(ValueError,'Parameter extent'):v.Oracle('esp32s3',e)
 def test_c3_rom_version_is_stored_as_byte(self):
  for version,count in [(0,34),(1,28),(255,28),(256,34),(257,28)]:
   _,trace=self.run_case('esp32c3',0,**{'22':version});writes=events(trace,2)
   self.assertEqual(len([r for r in writes if 0x70000000<=r[1]<0x70400000]),count)
   self.assertEqual([r[3] for r in writes if r[1]==0x230000],[version&255])
 def test_s3_callback_table_uses_returned_pointer(self):
  _,trace=self.run_case('esp32s3',0,**{'13':v.MASK});patches=[r for r in events(trace,2) if 0x70000000<=r[1]<0x70400000]
  self.assertEqual(len(patches),30);self.assertTrue(all(r[1]<0x70001000 for r in patches))
  self.assertFalse([r for r in events(trace,1) if r[1]==0x220000])
 def test_c3_reloads_global_before_patch_groups(self):
  _,trace=self.run_case('esp32c3',0,**{'13':v.MASK})
  self.assertEqual(len([r for r in events(trace,1) if r[1]==0x220000]),2)
 def test_save_word_is_reloaded_for_each_byte(self):
  _,trace=self.run_case('esp32c3',4,**{'8':0,'9':255,'10':v.MASK})
  reads=[r for r in events(trace,1) if r[1]==0x200000]
  self.assertEqual(len(reads),4);self.assertTrue(all(r[2]==4 for r in reads));self.assertNotEqual(reads[0][3],reads[1][3])
 def test_mode_narrowing_differs_between_chips(self):
  for chip,address in [('esp32c3',0x31000c),('esp32s3',0x200000)]:
   _,trace=self.run_case(chip,4,**{'2':256});self.assertEqual(events(trace,2)[0][1],address)
 def test_recovery_preserves_read_write_order(self):
  for chip,expected in [('esp32c3',[(1,0x3100e6),(2,0x2000da),(1,0x3100e8),(2,0x2000dc)]),('esp32s3',[(1,0x3100e6),(1,0x3100e8),(2,0x2000da),(2,0x2000dc)])]:
   _,trace=self.run_case(chip,5);self.assertEqual([(r[0],r[1]) for r in events(trace) if r[0] in (1,2)],expected)
 def test_checksum_valid_and_invalid(self):
  for chip in FIXTURE:
   for damage in (0,1,0x80000000,v.MASK):
    result,_=self.run_case(chip,8,**{'2':1,'16':damage,'17':0});self.assertEqual(result,int(damage!=0))
 def test_checksum_update_emits_four_bytes(self):
  for chip,size in [('esp32c3',848),('esp32s3',740)]:
   result,trace=self.run_case(chip,8,**{'2':0,'17':0});self.assertEqual(result,0)
   self.assertEqual([r[1] for r in events(trace,2)][-4:],list(range(0x310000+size+12,0x310000+size+16)))
 def test_package_read_is_bounded_to_three_bits(self):
  for package in range(8):
   result,trace=self.run_case('esp32s3',14,**{'23':(package<<21)|0x801fffff});self.assertEqual(result,package)
   self.assertEqual([(r[1],r[2]) for r in events(trace,1)],[(0x60007050,4)])
 def test_local_libc_copy_has_memory_only_effects(self):
  o=v.Oracle('esp32s3',FIXTURE['esp32s3']);c=v.default_case(13);c[12]=c[13]=v.MASK;o.run(c)
  self.assertEqual(o.calls,0);self.assertFalse(events(o.trace,7))
  before=o.get(o.param+229,1);o.copy(0x507000,o.real(0x240000),14)
  self.assertEqual([o.get(0x507000+i,1) for i in range(14)],[o.get(o.real(0x240000)+i,1) for i in range(14)])
  self.assertEqual(o.get(o.param+229,1),before);self.assertEqual(o.calls,0)
 def test_rf_table_payload_is_observed(self):
  for chip in FIXTURE:
   _,trace=self.run_case(chip,1)
   rows=events(trace,11);self.assertTrue(rows)
   self.assertIn([11,0x502000,8,0,1,0,1,0,1,0,1,0,0,0,0,0],rows)
 def test_rf_table_byte_corruption_changes_effects(self):
  import hashlib
  for chip in FIXTURE:
   e=copy.deepcopy(FIXTURE[chip]);row=e['readonly'][0];b=bytearray.fromhex(row['bytes']);b[-1]^=1
   row['bytes']=b.hex();row['sha256']=hashlib.sha256(b).hexdigest()
   self.assertNotEqual(v.Oracle(chip,e).run(v.default_case(1)),self.run_case(chip,1))
 def test_default_parameter_buffer_is_observed(self):
  for chip in FIXTURE:
   _,trace=self.run_case(chip,11,**{'1':1})
   rows=[r for r in events(trace,11) if 0x505000<=r[1]<0x505080]
   self.assertEqual(sum(r[2] for r in rows),77)
   self.assertEqual(rows[0][3],0 if chip=='esp32s3' else 2)
 def test_check_ignores_only_initialization_pointer(self):
  for chip in FIXTURE:
   first=self.run_case(chip,8,**{'20':0,'17':0})
   for alias in (1,2):self.assertEqual(first,self.run_case(chip,8,**{'20':alias,'17':0}))
   self.assertNotEqual(first,self.run_case(chip,8,**{'3':0,'17':0,'16':1}))
 def test_closed_child_result_ranges(self):
  for chip in FIXTURE:
   for selector in (0,1,45,46,255,v.MASK):
    _,trace=self.run_case(chip,11,**{'18':selector})
    for row in events(trace,4):
     if row[1] in (6,8,14):self.assertLess(row[2],{6:46,8:2,14:8}[row[1]])
if __name__=='__main__':unittest.main()
