import copy,hashlib,json,unittest
from unittest.mock import patch
from verify_contract import Search,HERE,COEFF,OUT,STATUS,signed,Machine

def case(kind):return dict(kind=kind,coeff=[256]*4,state=[0,0],estimates=[[0,0,35]],samples=0x12348001,delay=0x12340007,logs=[0,0],policy=0,mode=1,table_mutation=True)
def machine(chip):return Search(chip,json.loads((HERE/(chip+'-instructions.json')).read_text()))
class Tests(unittest.TestCase):
 def test_pinned_inputs_and_tools(self):
  m=json.loads((HERE/'manifest.json').read_text())
  for name,value in m['tool_sha256'].items():self.assertEqual(hashlib.sha256((HERE/name).read_bytes()).hexdigest(),value)
  for chip,row in m['chips'].items():
   for suffix,key in [('instructions','instructions_sha256'),('baseline','baseline_sha256')]:self.assertEqual(hashlib.sha256((HERE/(chip+'-'+suffix+'.json')).read_bytes()).hexdigest(),row[key])
 def test_every_original_branch_is_required(self):
  for row in json.loads((HERE/'expected-results.json').read_text()).values():
   self.assertEqual(row['instructions'],row['covered_instructions']);self.assertEqual(row['edges'],row['covered_edges']);self.assertEqual(row['uncovered_pcs'],[]);self.assertEqual(row['uncovered_edges'],[])
 def test_general_two_pairs_early_exit(self):
  for chip in ['esp32c3','esp32s3']:
   m=machine(chip);c=case(0);c['coeff']=[10,20,-1,-2];m.run(c)
   self.assertEqual(m.estimates,2);self.assertEqual([m.get(COEFF+i*2,2) for i in range(4)],[10,20,256,256])
 def test_general_bounded_exhaustion(self):
  for chip in ['esp32c3','esp32s3']:
   m=machine(chip);c=case(0);c['estimates']=[[100,100,56]];m.run(c);self.assertEqual(m.estimates,16)
 def test_one_step_exhaustion_keeps_last_written_update(self):
  for chip in ['esp32c3','esp32s3']:
   m=machine(chip);c=case(1);c['estimates']=[[16,0,35]];m.run(c)
   self.assertEqual(m.estimates,8);self.assertEqual(m.get(COEFF,2),144);self.assertNotEqual(m.get(COEFF,2),128);self.assertEqual(m.get(STATUS,1),0)
 def test_status_success_and_signed_final_clamp(self):
  for chip in ['esp32c3','esp32s3']:
   m=machine(chip);c=case(1);c['coeff']=[-1,1024,0,0];m.run(c)
   self.assertEqual(m.get(STATUS,1),1);self.assertEqual([m.get(COEFF+i*2,2) for i in range(2)],[0,511])
 def test_mode_dependent_budget(self):
  for chip in ['esp32c3','esp32s3']:
   m=machine(chip);c=case(1);c.update(mode=2,estimates=[[0,0,56]]);m.run(c);self.assertEqual(m.estimates,32)
 def test_coarse_table_domain_rejected_outside_six_bytes(self):
  for chip in ['esp32c3','esp32s3']:
   for index in [6,7,255]:
    c=case(0);c.update(state=[index<<6,0],estimates=[[100,100,56]])
    for model in [False,True]:
     with self.assertRaisesRegex(ValueError,'Uninitialized'):machine(chip).run(c,model)
 def test_byte_narrowed_absolute_is_detected(self):
  for chip in ['esp32c3','esp32s3']:
   c=case(0);c['estimates']=[[256,0,56]];a=machine(chip);expected=a.run(c);b=machine(chip);absolute=b.absolute
   b.absolute=lambda value:signed(absolute(value),8)
   self.assertNotEqual(expected,b.run(c,True))
 def test_cached_callback_table_is_rejected(self):
  for chip in ['esp32c3','esp32s3']:
   b=machine(chip);b.target=lambda kind:0x71000000+b.slots[kind]
   with self.assertRaisesRegex(ValueError,'Cached'):b.run(case(0),True)
 def test_signed_word_overflow_matters(self):
  for chip in ['esp32c3','esp32s3']:
   c=case(0);c.update(coeff=[32767,32768,0,0],estimates=[[50,-50,56]])
   expected=machine(chip).run(c)
   with patch('verify_contract.s16',lambda x:x):self.assertNotEqual(expected,machine(chip).run(c,True))
 def test_only_halfword_alignment_required(self):
  for chip in ['esp32c3','esp32s3']:
   c=case(1);c['alias']=1;c['mutate']=True
   a=machine(chip);self.assertEqual(a.run(c),machine(chip).run(c,True));self.assertEqual(a.coeff%4,2)
 def test_source_opcodes_slti_and_sgtz(self):
  class Tiny(Machine):
   def __init__(self,op,value,immediate=0,chip='esp32c3'):
    self.chip=chip;self.steps=0;self.visited=set();self.program={0:(4,op,['a0','a0']+([str(immediate)] if op=='slti' else [])),4:(8,'ret',[])};self.read=self.write=self.get=lambda *args:0
  values=[0,1,2,0x7fffffff,0x80000000,0xfffff800,0xffffffff]
  for value in values:
   t=Tiny('sgtz',value);r=t.registers();r['a0']=value;self.assertEqual(t.execute(0,r,0),int(signed(value)>0))
   for immediate in range(-2048,2048):
    t=Tiny('slti',value,immediate);r=t.registers();r['a0']=value;self.assertEqual(t.execute(0,r,0),int(signed(value)<immediate))
 def test_invalid_slti_and_wrong_arch_rejected(self):
  class Tiny(Machine):pass
  for chip,value in [('esp32c3',2048),('esp32c3',-2049),('esp32s3',0)]:
   t=Tiny();t.chip=chip;t.steps=0;t.visited=set();t.read=t.write=t.get=lambda *args:0;t.program={0:(4,'slti',['a0','a0',str(value)])}
   with self.assertRaisesRegex(ValueError,'Invalid signed immediate'):t.execute(0,t.registers(),0)
 def test_ignored_minimum_argument_is_canonicalized(self):
  for chip in ['esp32c3','esp32s3']:
   a=machine(chip);a.init(case(1));a.enter(1,0x10fe00);a.call('minimum',[a.samples,1,a.scratch]);expected=a.trace
   a.init(case(1));a.enter(1,0x10fe00);a.call('minimum',[a.samples,0xdeadbeef,a.scratch]);self.assertEqual(expected,a.trace)
if __name__=='__main__':unittest.main()
