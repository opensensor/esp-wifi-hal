import copy,json,unittest
from pathlib import Path
from verify import Oracle,cases,MMIO
from machine import decode
E=json.loads((Path(__file__).parent/'original-instructions.json').read_text())
class Tests(unittest.TestCase):
 def test_byte_tamper(self):
  for chip,e in E.items():
   e=copy.deepcopy(e);e['functions'][0]['code_hex']='00'+e['functions'][0]['code_hex'][2:]
   with self.assertRaises(ValueError):decode(e)
 def test_instruction_tamper(self):
  e=copy.deepcopy(E['esp32c3']);line=e['functions'][0]['instructions'][0];parts=line.split();parts[2]='unknown';e['functions'][0]['instructions'][0]=' '.join(parts)
  with self.assertRaises(ValueError):decode(e)
 def test_unknown_entry(self):
  c=next(cases('esp32c3'));c[0]=123
  with self.assertRaises(ValueError):Oracle('esp32c3',E['esp32c3']).run(c)
 def test_unbounded_completion(self):
  c=next(cases('esp32c3'));c[4]=513
  with self.assertRaises(ValueError):Oracle('esp32c3',E['esp32c3']).run(c)
 def test_readonly_tamper(self):
  e=copy.deepcopy(E['esp32s3']);e['readonly'][0]['bytes']='00'+e['readonly'][0]['bytes'][2:]
  with self.assertRaises(ValueError):Oracle('esp32s3',e).run(next(cases('esp32s3')))
 def test_reset_narrowing(self):
  traces=[]
  for chip in E:
   c=next(cases(chip));c[1]=256;traces.append(Oracle(chip,E[chip]).run(c))
  self.assertNotEqual(*traces)
 def test_immediate_completion_preserves_count(self):
  for chip in E:
   c=next(cases(chip));c[0]=2;c[4]=0;c[8]=65535;o=Oracle(chip,E[chip]);o.run(c);self.assertEqual(o.get(o.param+o.count,2),65535)
 def test_counter_wrap(self):
  for chip in E:
   c=next(cases(chip));c[0]=2;c[4]=2;c[5]=69;c[6]=0;c[8]=65535;o=Oracle(chip,E[chip]);o.run(c);self.assertEqual(o.get(o.param+o.count,2),1)
 def test_check_never_clears_saturation_flag(self):
  for chip in E:
   c=next(cases(chip));c[0]=3;c[5]=70;c[6]=0;o=Oracle(chip,E[chip]);o.run(c);self.assertEqual(o.get(o.param+o.flag,1),(c[3]+o.flag*17)&255)
if __name__=='__main__':unittest.main()
