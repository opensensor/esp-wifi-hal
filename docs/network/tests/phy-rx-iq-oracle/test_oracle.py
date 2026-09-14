import copy,json,unittest
from pathlib import Path
from machine import decode,Machine,MASK
from verify import Oracle,cases,divide
E=json.loads(Path(__file__).with_name('original-instructions.json').read_text())
def rows(trace):return [trace[i:i+8] for i in range(0,len(trace),8)]
class Tests(unittest.TestCase):
 def test_byte_hash(self):
  for chip,e in E.items():
   d=copy.deepcopy(e);d['functions'][0]['code_hex']='ff'+d['functions'][0]['code_hex'][2:]
   with self.assertRaises(ValueError):decode(d)
 def test_decoded_byte_corruption(self):
  d=copy.deepcopy(E['esp32c3']);d['functions'][0]['instructions'][0]=d['functions'][0]['instructions'][0].replace('7179','7178')
  with self.assertRaises(ValueError):decode(d)
 def test_unsupported_opcode(self):
  d=copy.deepcopy(E['esp32s3']);d['functions'][1]['instructions']=[s.replace('mul16s','invented') for s in d['functions'][1]['instructions']]
  with self.assertRaises(ValueError):decode(d)
 def test_function_set(self):
  for e in E.values():
   d=copy.deepcopy(e);d['functions'].pop()
   with self.assertRaises(ValueError):decode(d)
 def test_wide_return(self):
  for chip in E:
   m=Machine();m.chip=chip;r=m.registers();m.clobber(r,(0x89abcdef,0xfedcba98));base=10 if chip=='esp32s3' else 0
   self.assertEqual((r[f'a{base}'],r[f'a{base+1}']),(0x89abcdef,0xfedcba98))
   m.clobber(r,7);self.assertEqual(r[f'a{base+1}'],0xdeadbeef)
 def test_signed_low16_multiply(self):
  o=Oracle('esp32s3',E['esp32s3']);o.program={0:(3,'mul16s',['a2','a3','a4']),3:(5,'retw.n',[])}
  for a,b in [(0x1234ffff,0x55550002),(0x99998000,0x33338000),(0x88887fff,0xabcd8000)]:
   o.steps=0;r=o.registers();r['a3']=a;r['a4']=b
   left=int.from_bytes((a&65535).to_bytes(2,'little'),'little',signed=True);right=int.from_bytes((b&65535).to_bytes(2,'little'),'little',signed=True)
   self.assertEqual(o.execute(0,r,0),(left*right)&MASK)
 def test_concat_shift(self):
  for op in ('ssl','ssr'):
   o=Oracle('esp32s3',E['esp32s3']);o.program={0:(3,op,['a5']),3:(6,'src',['a2','a3','a4']),6:(8,'retw.n',[])}
   for shift in range(32):
    o.steps=0;r=o.registers();r['a3']=0x12345678;r['a4']=0x9abcdef0;r['a5']=shift
    if op=='ssl':expected=((r['a3']<<shift)|(r['a4']>>(32-shift)))&MASK
    else:expected=((r['a3']<<(32-shift))|(r['a4']>>shift))&MASK
    self.assertEqual(o.execute(0,r,0),expected)
 def test_unsigned_maximum(self):
  o=Oracle('esp32s3',E['esp32s3']);o.program={0:(3,'maxu',['a2','a3','a4']),3:(5,'retw.n',[])}
  for a,b in [(0,1),(0xffffffff,1),(0x80000000,0x7fffffff),(7,7)]:
   o.steps=0;r=o.registers();r['a3']=a;r['a4']=b;self.assertEqual(o.execute(0,r,0),max(a,b))
 def test_division_sign_and_unmodeled_limits(self):
  self.assertEqual(divide(-17,3),-5);self.assertEqual(divide(17,-3),-5);self.assertEqual(divide(-17,-3),5)
  for n,d in [(1,0),(-(1<<63),-1)]:
   with self.assertRaises(ValueError):divide(n,d)
 def test_zero_and_negative_denominator(self):
  for chip in E:
   o=Oracle(chip,E[chip]);c=list(next(cases(chip)));c[3:7]=[0]*4
   divisions=[r for r in rows(o.run(c)) if r[0]==4];self.assertEqual([r[3:5] for r in divisions],[[1,0],[1,0]])
   c[3:7]=[0x80000000,0,0,0x80000000]
   self.assertEqual([r[3:5] for r in rows(o.run(c)) if r[0]==4],[[0,0x80000000]]*2)
 def test_logging_narrowing(self):
  for chip in E:
   c=list(next(cases(chip)));c[2]=256
   self.assertEqual(any(r[0]==6 for r in rows(Oracle(chip,E[chip]).run(c))),chip=='esp32c3')
 def test_alias_logging_reread(self):
  for chip in E:
   c=list(next(cases(chip)));c[10]=2
   r=rows(Oracle(chip,E[chip]).run(c));writes=[(i,x) for i,x in enumerate(r) if x[0]==2];reads=[(i,x) for i,x in enumerate(r) if x[0]==1 and x[1]==0x60006164]
   self.assertEqual(len(writes),2);self.assertEqual(len(reads),1);self.assertGreater(reads[0][0],writes[1][0]);self.assertEqual(reads[0][1][3]&65535,writes[0][1][3]|(writes[1][1][3]<<8))
 def test_two_rounds_and_callback_reload(self):
  for chip in E:
   c=list(next(cases(chip)));c[0]=1
   r=rows(Oracle(chip,E[chip]).run(c));self.assertEqual(sum(x[0]==7 for x in r),2);self.assertEqual(sum(x[0]==3 for x in r),6)
   callbacks=[x[1] for x in r if x[0]==5];self.assertEqual(len(callbacks),4);self.assertEqual(len(set(a//4096 for a in callbacks)),4)
 def test_clamp_and_output_alias(self):
  for chip in E:
   clamps=set()
   for c in cases(chip):
    if c[0]!=1:continue
    writes=[r for r in rows(Oracle(chip,E[chip]).run(c)) if r[0]==2 and r[1]!=0x500000 and r[1]!=0x500001]
    for row in writes:
     v=row[3] if row[3]<128 else row[3]-256;self.assertTrue(-31<=v<=31);clamps.add(v)
    if c[10]==1:self.assertEqual(writes[-2][1],writes[-1][1])
   self.assertTrue({-31,31}<=clamps)
if __name__=='__main__':unittest.main()
