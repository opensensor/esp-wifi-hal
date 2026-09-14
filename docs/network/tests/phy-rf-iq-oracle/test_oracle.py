import copy,json,unittest
from verify import Oracle,cases,HERE,NAMES,MMIO,difference
from machine import decode,require,signed
E=json.loads((HERE/'original-instructions.json').read_text())
def base():return [1,14,0x12348001,0x123401,1,0xabcdef12,0x12345678,1,0,0,0,0,0,0,0,0,0,0,0x13579bdf,0]
def events(o,c):t=o.run(c);return [t[i:i+8] for i in range(0,len(t),8)]
class Tests(unittest.TestCase):
 def test_bad_hash(self):
  e=copy.deepcopy(E['esp32c3']);e['functions'][0]['body_sha256']='0'*64
  with self.assertRaises(ValueError):decode(e)
 def test_unknown_instruction(self):
  e=copy.deepcopy(E['esp32s3']);e['functions'][0]['instructions'][0]=e['functions'][0]['instructions'][0].replace('entry','unknown')
  with self.assertRaises(ValueError):decode(e)
 def test_uninitialized_read(self):
  o=Oracle('esp32c3',E['esp32c3']);o.run(base())
  with self.assertRaises(ValueError):o.read(0x102345,1)
 def test_bounded_rejects_outlier(self):
  c=base();c[19]=1;c[10]=128
  with self.assertRaises(ValueError):Oracle('esp32c3',E['esp32c3']).run(c)
 def test_constant_converges_in_two(self):
  for chip in E:
   c=base();c[10:18]=[31,225]*4;o=Oracle(chip,E[chip]);ev=events(o,c);self.assertEqual(o.sample_index,2);self.assertEqual(ev[-1][1],(31<<6)|33)
 def test_four_sample_negative_tie(self):
  for chip in E:
   c=base();c[9]=4;c[10:18]=[255,254,0,255,255,254,0,255];o=Oracle(chip,E[chip]);ev=events(o,c);self.assertEqual(o.sample_index,4);self.assertEqual(ev[-1][1],63)
 def test_phase_failure_delays_convergence(self):
  for chip in E:
   c=base();c[10:18]=[0,0,0,10,0,20,0,20];o=Oracle(chip,E[chip]);ev=events(o,c);self.assertEqual(o.sample_index,4);self.assertEqual(ev[-1][1],20)
 def test_signed_full_width_callback(self):
  for chip in E:
   for mode,n in [(1,2),(2,4),(3,2),(4,4)]:
    c=base();c[9]=mode;o=Oracle(chip,E[chip]);o.run(c);self.assertEqual(o.sample_index,n)
 def test_table_reloaded_between_checks(self):
  for chip in E:
   ev=events(Oracle(chip,E[chip]),base());targets=[v[1] for v in ev if v[0]==9];self.assertEqual(len(targets),2);self.assertEqual(targets[1]-targets[0],0x1000)
 def test_chip_narrowing_and_log_enable(self):
  for chip in E:
   c=base();c[4]=256;ev=events(Oracle(chip,E[chip]),c);start=next(v for v in ev if v[0]==3)
   self.assertEqual(start[2:4],[0xffff8001,1] if chip=='esp32s3' else c[2:4]);self.assertEqual(any(v[0]==6 for v in ev),chip=='esp32c3')
 def test_output_mmio_alias_copies_ordered_bytes(self):
  for chip in E:
   c=base();c[0]=0;c[8]=1;c[10:12]=[0x12,0x34];ev=events(Oracle(chip,E[chip]),c);writes=[v for v in ev if v[0]==2];self.assertEqual([(v[1],v[2],v[3]) for v in writes[-2:]],[(MMIO,1,0x12),(MMIO+1,1,0x34)])
 def test_private_correction_pointer_order(self):
  for chip in E:
   c=base();c[0]=0;ev=events(Oracle(chip,E[chip]),c);call=next(v for v in ev if v[0]==4);self.assertEqual(call[2:4],[0x500100,0x500101])
if __name__=='__main__':unittest.main()
