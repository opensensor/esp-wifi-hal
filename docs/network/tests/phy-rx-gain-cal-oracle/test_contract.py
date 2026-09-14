import copy,hashlib,itertools,json,unittest
from pathlib import Path
import verify_contract as v
from machine import decode,require,CONDITIONAL
HERE=Path(__file__).resolve().parent
class Tests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.e={c:json.loads((HERE/(c+'-instructions.json')).read_text()) for c in ('esp32c3','esp32s3')}
 def base(self,chip,kind=0):return next(copy.deepcopy(c) for c in v.cases(chip) if c['kind']==kind and (kind==0 or c['start']==0 and c['end']==3))
 def check(self,chip,c):
  a=v.Gain(chip,self.e[chip]);b=v.Gain(chip,self.e[chip]);x=a.run(c);self.assertEqual(x,b.run(c,True));return x
 def test_fixture_hashes(self):
  m=json.loads((HERE/'manifest.json').read_text())
  for name,digest in m['tool_sha256'].items():self.assertEqual(hashlib.sha256((HERE/name).read_bytes()).hexdigest(),digest)
  for chip,row in m['chips'].items():
   for suffix in ('baseline','instructions'):self.assertEqual(hashlib.sha256((HERE/(chip+'-'+suffix+'.json')).read_bytes()).hexdigest(),row[suffix+'_sha256'])
 def test_original_coverage_and_proof(self):
  r=json.loads((HERE/'expected-results.json').read_text());self.assertEqual(r['esp32c3']['uncovered_pcs'],['0x42042180']);self.assertEqual(r['esp32c3']['uncovered_edges'],[['0x4204217c',False]])
  self.assertEqual(r['esp32s3']['uncovered_pcs'],[]);self.assertEqual(r['esp32s3']['uncovered_edges'],[]);self.assertEqual(v.iq_range_proof(),dict(unclamped_min=-16,unclamped_max=44,phase_final_max=[24,44]))
 def test_bytes_cannot_change(self):
  e=copy.deepcopy(self.e['esp32c3']);e['functions'][0]['code_hex']='00'+e['functions'][0]['code_hex'][2:]
  with self.assertRaises(ValueError):decode(e)
 def test_instruction_cannot_change(self):
  e=copy.deepcopy(self.e['esp32s3']);e['functions'][0]['instructions'][0]=e['functions'][0]['instructions'][0].replace('entry','invented')
  with self.assertRaises(ValueError):decode(e)
 def test_invalid_operation(self):
  c=self.base('esp32c3');c['kind']=2
  with self.assertRaises(ValueError):v.Gain('esp32c3',self.e['esp32c3']).run(c)
 def test_bounded_count_and_status_domain(self):
  for chip in self.e:
   for updates in [dict(count=10),dict(count=0),dict(start=3),dict(end=5),dict(policy=0,start=0,end=1)]+([dict(middle_count=6)] if chip=='esp32s3' else []):
    c=self.base(chip,1);c.update(updates)
    with self.assertRaises(ValueError):v.Gain(chip,self.e[chip]).run(c)
 def test_zero_count_skips_samples(self):
  for chip in self.e:
   c=self.base(chip,1);c.update(policy=1,start=0,end=1,count=0);t=self.check(chip,c);self.assertFalse(any(r[:2]==['call','one_step'] for r in t))
 def test_seven_channels_and_paired_layout(self):
  for chip in self.e:
   c=self.base(chip,1);c.update(policy=0,start=2,end=3);t=self.check(chip,c)
   self.assertEqual([r[3] for r in t if r[:2]==['call','channel']],[14,2,4,6,8,10,12,14]);calls=[r for r in t if r[:2]==['call','one_step']];self.assertEqual(len(calls),7 if chip=='esp32s3' else 21)
   status=next(r for r in t if r[0]=='status_input');self.assertEqual(len(status)-1,14 if chip=='esp32s3' else 42)
 def test_signed_low_halfword_packing(self):
  for chip in self.e:
   c=self.base(chip,1);c.update(policy=1,start=0,end=1,count=3,coefficients=[[1,0x8000]],mutate=False);t=self.check(chip,c)
   stores=[r for r in t if r[:3]==['write',v.IQ,4]];self.assertEqual(stores[0][3],0xffff8000)
 def test_s3_scalar_narrowing(self):
  c=self.base('esp32s3');c.update(policy=0x100,logging=0x100,frequency=0x12348001);t=self.check('esp32s3',c);self.assertFalse(any(r[:2]==['call','i2c_read'] for r in t));self.assertFalse(any(r[:2]==['call','log'] for r in t));start=next(r for r in t if r[:2]==['call','start_tone']);self.assertEqual(start[4],0xffff8001)
 def test_c3_retains_full_scalar(self):
  c=self.base('esp32c3');c.update(policy=0x100,logging=0x100,frequency=0x12348001);t=self.check('esp32c3',c);self.assertTrue(any(r[:2]==['call','i2c_read'] for r in t));self.assertTrue(any(r[:2]==['call','log'] for r in t));start=next(r for r in t if r[:2]==['call','start_tone']);self.assertEqual(start[4],0x12348001)
 def test_unused_tenth_argument(self):
  c=self.base('esp32s3',1);a=self.check('esp32s3',c);c['unused']^=0xffffffff;self.assertEqual(a,self.check('esp32s3',c))
 def test_parameter_channel_write_only_c3(self):
  for chip in self.e:
   c=self.base(chip,1);t=self.check(chip,c);self.assertEqual(['write',v.PARAM+0x1f2,1,14] in t,chip=='esp32c3')
 def test_callback_cache_negative_control(self):
  class Cached(v.Gain):
   def target(self,kind):return 0x71000000+self.slots[kind]
  for chip in self.e:
   c=self.base(chip);c['table_mutation']=True
   with self.assertRaises(ValueError):Cached(chip,self.e[chip]).run(c,True)
 def test_alignment_rejected(self):
  a=v.Gain('esp32c3',self.e['esp32c3']);a.init(self.base('esp32c3'))
  with self.assertRaises(ValueError):a.read(v.IQ+1,2)
 def test_aliased_mutating_buffers(self):
  for chip in self.e:
   for alias in range(4):
    c=self.base(chip,1);c.update(alias=alias,mutate=True,policy=0,start=0,end=3);self.check(chip,c)
 def test_rx_controls_restore_order(self):
  for chip in self.e:
   c=self.base(chip,1);c.update(policy=1,start=0,end=0);t=self.check(chip,c);calls=[r for r in t if r[0]=='call'];self.assertEqual([r[1] for r in calls[-3:]],['i2c_write','rx_force','tx_force']);self.assertEqual(calls[-3][-1],c['saved']);self.assertEqual(calls[-2][-1],0);self.assertEqual(calls[-1][-1],0)
if __name__=='__main__':unittest.main()
