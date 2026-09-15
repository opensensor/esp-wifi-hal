import copy,json,unittest
import verify

class Contracts(unittest.TestCase):
 def case(self,kind=0,mode=0,pair=(0,0),policy=1):
  return dict(kind=kind,args=[0,0,verify.OUT,0,0,0] if not kind else [0x10001,verify.OUT,verify.OUT+8,0x180,0x180,mode],
    selector=16,offset=123,seed=0,registers=[1,2],policy=policy,returns=[0x87654321]*48,
    effects=[[i+10,i+20,0x76540012,i,i%4,(pair[0]&65535)|((pair[1]&65535)<<16)] for i in range(48)])
 def original(self,chip,c):
  e=json.loads((verify.ROOT/(chip+'-instructions.json')).read_text());a=verify.Original(chip,e,c);a.run();return a
 def calls(self,a,name):return [r for r in a.trace if r[:2]==['call',name]]
 def test_four_round_stop_and_seven_round_exhaustion(self):
  for chip in ('esp32c3','esp32s3'):
   for policy,rounds,count in ((1,4,20),(2,7,34),(3,7,38)):
    a=self.original(chip,self.case(policy=policy));self.assertEqual(len(self.calls(a,'txiq_get_mis_pwr')),rounds*2);self.assertEqual(a.calls,count)
 def test_negative_callback_word_allows_stop(self):
  for chip in ('esp32c3','esp32s3'):
   c=self.case(policy=4);c['returns']=[0x80000000]*48;a=self.original(chip,c)
   self.assertEqual(len(self.calls(a,'txiq_get_mis_pwr')),8)
 def test_sample_read_and_intermediate_byte_order(self):
  for chip in ('esp32c3','esp32s3'):
   a=self.original(chip,self.case());reads=[r[2][1] for r in a.trace if r[:2]==['read',2] and r[2][0]=='sample']
   self.assertEqual(reads[:4],[0,1,0,1] if chip=='esp32s3' else [1,0,0,1])
   i=next(i for i,r in enumerate(a.trace) if r[:3]==['write',1,['out',1]])
   self.assertEqual(a.trace[i+1 if chip=='esp32s3' else i-1][:3],['read',1,['out',0]])
 def test_final_stores_ignore_last_set_returns(self):
  for chip in ('esp32c3','esp32s3'):
   a=self.original(chip,self.case());calls=self.calls(a,'txiq_set_reg');writes=[r for r in a.trace if r[0]=='write' and r[2][0]=='out'][-2:]
   expected=[[0,calls[-2][2][0]&255],[1,calls[-1][2][0]&255]]
   self.assertEqual([[r[2][1],r[3]] for r in writes],expected if chip=='esp32s3' else expected[::-1])
 def test_signed_ratios_and_zero_denominator_guards(self):
  for chip in ('esp32c3','esp32s3'):
   for pair,first,second in [((0,0),0,0),((1,0),192,128),((0,1),64,128),((-32768,32767),128,128)]:
    a=self.original(chip,self.case(pair=pair));writes=[r for r in a.trace if r[0]=='write' and r[2][0]=='out']
    self.assertEqual([r[3] for r in writes[:2]],[first,second])
 def test_full_c3_set_returns_and_s3_narrowing(self):
  a=self.original('esp32c3',self.case(policy=1));b=self.original('esp32s3',self.case(policy=1))
  self.assertEqual(self.calls(a,'txiq_set_reg')[-2][2][0],0x87654321)
  self.assertEqual(self.calls(b,'txiq_set_reg')[-2][2][0],0x21)
 def test_saved_writer_survives_read_callback_mutation(self):
  for chip in ('esp32c3','esp32s3'):
   a=self.original(chip,self.case(1,mode=1));calls=[r for r in a.trace if r[0]=='call']
   self.assertEqual(calls[2][1],'pbus_read2');self.assertEqual(calls[3][1],'pbus_write2')
   self.assertEqual(calls[3][2],[1,1,0x4323])
 def test_chip_mode_and_argument_narrowing(self):
  for chip in ('esp32c3','esp32s3'):
   a=self.original(chip,self.case(1,mode=257));calls=[r for r in a.trace if r[0]=='call'];s3=chip=='esp32s3'
   self.assertEqual(calls[1][2],[1,2,1 if s3 else 0x10001])
   self.assertEqual(any(r[1].startswith('pbus_read') for r in calls),s3)
   atten=self.calls(a,'get_power_atten')[0][2]
   self.assertEqual(atten,[128,0xffffff80,56,224,0] if s3 else [384,384,30,0x7654,0])
 def test_mode_two_loopback_and_txdc_order(self):
  for chip in ('esp32c3','esp32s3'):
   a=self.original(chip,self.case(1,mode=2));calls=[r for r in a.trace if r[0]=='call'];loop=[r for r in calls if r[1].startswith('loopback')]
   self.assertEqual([r[2] for r in loop],[[1],[0]])
   self.assertEqual(calls[3][:2],['call','txdc_cal_v70'])
   self.assertFalse(any(r[1].startswith('dco') for r in calls))
 def test_coefficient_clamps_and_saved_register_restore(self):
  for chip in ('esp32c3','esp32s3'):
   for pair,value in [((0,0),0),((127,127),(15<<6)|31),((-128,-128),(((-15)&31)<<6)|((-31)&63))]:
    a=self.original(chip,self.case(1,mode=2,pair=pair))
    writes=[r for r in a.trace if r[:3]==['write',2,['out',8]]];self.assertEqual([r[3] for r in writes],[value])
    read=[r[3] for r in a.trace if r[:3]==['read',4,['reg',0x60006040]]]
    write=[r[3] for r in a.trace if r[:3]==['write',4,['reg',0x60006040]]];self.assertEqual(read,write)
 def test_invalid_buffers_and_calls_fail(self):
  a=self.original('esp32c3',self.case())
  for address,width in ((0x10fefe,4),(a.stack+1,2)):
   with self.assertRaises(ValueError):a.stack_buffer(address,width,2)
  with self.assertRaises(ValueError):a.read(0xabcdef00,4)
  with self.assertRaises(ValueError):a.dispatch(0xabcdef00,lambda n:[],{},0)
 def test_instruction_corruption_fails(self):
  e=json.loads((verify.ROOT/'esp32c3-instructions.json').read_text())
  for field,value in [('body_sha256','0'*64),('instructions',['42042de8: ff450793 unknown'])]:
   x=copy.deepcopy(e);x['functions'][0][field]=value
   with self.assertRaises(ValueError):verify.machine.decode(x)
 def test_xtensa_signed_division_and_zero_rejection(self):
  a=self.original('esp32s3',self.case());a.program={0:(3,'quos',['a2','a3','a4']),3:(5,'retw.n',[])}
  r=a.registers();r['a3']=(-7)&verify.M;r['a4']=3
  self.assertEqual(a.execute(0,r,0),(-2)&verify.M)
  r['a4']=0
  with self.assertRaises(ValueError):a.execute(0,r,0)

if __name__=='__main__':unittest.main()
