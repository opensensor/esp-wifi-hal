import copy,json,unittest
import verify

class Contract(unittest.TestCase):
 def case(self,kind=0,atten=40):
  return dict(kind=kind,flags=0,atten=atten,seed=1,returns=[0x87654321,0xfedcba98,0,0,0,0,0],
              effects=[[0x55550000+i,atten,i%2,(i+1)%2,0x12345678+i] for i in range(7)])
 def original(self,chip,c):
  e=json.loads((verify.ROOT/(chip+'-instructions.json')).read_text());a=verify.Original(chip,e,c);a.run();return a
 def test_early_returns_have_no_helpers_or_writes(self):
  for chip in ('esp32c3','esp32s3'):
   for kind,bit in ((0,14),(1,11)):
    c=self.case(kind);c['flags']=1<<bit;a=self.original(chip,c)
    self.assertEqual(a.trace,[['read',4,['param',288],1<<bit]])
 def test_signed_byte_clamps_and_preserved_initial_value(self):
  for chip in ('esp32c3','esp32s3'):
   for byte,first,second in ((0,0,0),(19,19,0),(20,20,0),(21,21,1),(127,127,107),(128,0,0),(255,0,0)):
    c=self.case(atten=byte);c['effects'][0][1]=64;a=self.original(chip,c)
    calls=[r for r in a.trace if r[0]=='call']
    self.assertEqual(calls,[['call','rfcal_txiq',[0,verify.PARAM+0x124,verify.PARAM+0x14c,128,first,0]],
                            ['call','rfcal_txiq',[0,verify.SCRATCH,verify.PARAM+0x162,128,second,2]]])
    self.assertEqual(a.get(a.scratch,8),sum(((c['effects'][1][4]+i*257)&65535)<<(16*i) for i in range(4)))
 def test_bluetooth_chip_difference_wraps_and_reads_after_callbacks(self):
  for chip,expected in (('esp32c3',-128),('esp32s3',108)):
   c=self.case(1,1);c['effects'][3][1]=108;a=self.original(chip,c)
   call=next(r for r in a.trace if r[:2]==['call','rfcal_txiq'])
   self.assertEqual(call[2],[0,verify.PARAM+0x182,verify.PARAM+0x180,32,expected&verify.M,1])
 def test_full_word_restores_and_fresh_callback_slots(self):
  for chip in ('esp32c3','esp32s3'):
   c=self.case(1);a=self.original(chip,c);calls=[r for r in a.trace if r[0]=='call']
   self.assertEqual([r[1] for r in calls],['read0','read1','write2','write1','rfcal_txiq','write1','write2'])
   self.assertEqual(a.analog,c['returns'][:2])
 def test_final_flags_use_fresh_word_and_chip_order(self):
  for chip in ('esp32c3','esp32s3'):
   a=self.original(chip,self.case(1));i=next(i for i,r in enumerate(a.trace) if r[:3]==['write',4,['param',288]])
   self.assertEqual(a.trace[i][3],(0x55550004|(1<<11)))
   self.assertEqual(a.trace[i-1 if chip=='esp32c3' else i+1][:3],['read',4,['table']])
 def test_unknown_memory_and_uninitialized_stack_rejected(self):
  a=self.original('esp32c3',self.case())
  for address in (0xabcdef00,0x100000):
   with self.assertRaises(ValueError):a.read(address,4)
 def test_short_or_unaligned_scratch_rejected(self):
  a=self.original('esp32c3',self.case())
  for address,width in ((0x10fefc,8),(a.stack+1,8),(a.stack,2)):
   with self.assertRaises(ValueError):a.output(address,width)
 def test_code_corruption_and_unknown_opcode_rejected(self):
  e=json.loads((verify.ROOT/'esp32c3-instructions.json').read_text())
  for field,value in [('body_sha256','0'*64),('instructions',['4204303a: 1101 invalid'])]:
   x=copy.deepcopy(e);x['functions'][0][field]=value
   with self.assertRaises(ValueError):verify.machine.decode(x)
 def test_unknown_dispatch_rejected(self):
  a=self.original('esp32s3',self.case())
  with self.assertRaises(ValueError):a.dispatch(0xabcdef00,lambda n:[],{},0)

if __name__=='__main__':unittest.main()
