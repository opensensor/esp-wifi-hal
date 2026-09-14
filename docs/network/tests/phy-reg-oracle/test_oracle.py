import copy,json,unittest
from pathlib import Path
import verify as v
E=json.loads(Path(__file__).with_name('original-instructions.json').read_text())
def rows(trace):return [trace[i:i+8] for i in range(0,len(trace),8)]
class RegisterOracle(unittest.TestCase):
    def run_case(self,chip,kind,**axes):
        c=v.default_case(kind)
        for i,value in axes.items():c[int(i)]=value&v.MASK
        return v.Oracle(chip,E[chip]).run(c)
    def test_body_hash(self):
        for chip in E:
            e=copy.deepcopy(E[chip]);e['functions'][0]['code_hex']='00'+e['functions'][0]['code_hex'][2:]
            with self.assertRaisesRegex(ValueError,'Code hash'):v.Oracle(chip,e)
    def test_instruction_bytes(self):
        e=copy.deepcopy(E['esp32s3']);e['functions'][0]['instructions'][0]=e['functions'][0]['instructions'][0].replace('004136','004137')
        with self.assertRaisesRegex(ValueError,'bytes differ'):v.Oracle('esp32s3',e)
    def test_duplicate_instruction(self):
        e=copy.deepcopy(E['esp32c3']);e['functions'][0]['instructions'].append(e['functions'][0]['instructions'][0])
        with self.assertRaisesRegex(ValueError,'Overlapping'):v.Oracle('esp32c3',e)
    def test_unknown_opcode(self):
        e=copy.deepcopy(E['esp32c3']);e['functions'][0]['instructions'][0]=e['functions'][0]['instructions'][0].replace('lui','invented')
        with self.assertRaisesRegex(ValueError,'Unsupported'):v.Oracle('esp32c3',e)
    def test_missing_literal(self):
        e=copy.deepcopy(E['esp32s3']);e['literals']={}
        with self.assertRaisesRegex(ValueError,'Unknown literal'):v.Oracle('esp32s3',e).run(v.default_case(0))
    def test_wrong_parameter_extent(self):
        e=copy.deepcopy(E['esp32s3']);e['symbols']['phy_param']['size_bytes']=848
        with self.assertRaisesRegex(ValueError,'extent'):v.Oracle('esp32s3',e)
    def test_unknown_call_rejected(self):
        e=copy.deepcopy(E['esp32s3']);delay=e['symbols']['ets_delay_us']['address']
        for a,value in e['literals'].items():
            if value==delay:e['literals'][a]='0x40000001'
        with self.assertRaisesRegex(ValueError,'Unknown callback'):v.Oracle('esp32s3',e).run(v.default_case(15))
    def test_case_domain(self):
        for axis,value in [(0,16),(16,4),(22,1)]:
            c=v.default_case(0);c[axis]=value
            with self.assertRaisesRegex(ValueError,'domain'):v.Oracle('esp32c3',E['esp32c3']).run(c)
    def test_pbus_copy_interleaved(self):
        for chip in E:
            _,t=self.run_case(chip,0);r=rows(t);self.assertEqual([x[0] for x in r],[1,8]*6)
            self.assertEqual([x[1] for x in r[1::2]],[0x600060e0+i*4 for i in range(6)])
    def test_pbus_fresh_state_after_write(self):
        for chip in E:self.assertNotEqual(self.run_case(chip,0)[1],self.run_case(chip,0,**{'9':v.MASK})[1])
    def test_discarded_read_retained(self):
        for chip,kind,address in [('esp32c3',1,0x6001d06c),('esp32c3',3,0x6001c068),('esp32s3',3,0x6001c068)]:
            r=rows(self.run_case(chip,kind)[1]);i=next(i for i,x in enumerate(r) if x[:2]==[7,address]);self.assertEqual(r[i+1][:2],[8,address])
    def test_agc_order(self):
        for chip in E:
            for kind,addresses in [(5,[0x6001c01c,0x6001c034,0x6001c080]),(6,[0x6001c080,0x6001c01c,0x6001c034])]:
                self.assertEqual([x[1] for x in rows(self.run_case(chip,kind)[1]) if x[0]==8],addresses)
    def test_s3_digital_gain_byte_order(self):
        r=rows(self.run_case('esp32s3',1,**{'16':1})[1]);self.assertEqual([x[1]-0x300001 for x in r if x[0]==1],[1,0,2,3,5,4,6,7,9,8,10,11,13,12]);self.assertTrue(all(x[2]==1 for x in r if x[0]==1))
    def test_noise_floor_chip_difference(self):
        self.assertEqual(self.run_case('esp32s3',13),(0,[]));self.assertEqual(len(self.run_case('esp32c3',13)[1]),16)
    def test_iq_return_register_widths(self):
        for kind in (9,10):
            self.assertEqual(self.run_case('esp32c3',kind,**{'1':-128,'2':0})[0],(-31)&v.MASK)
            self.assertEqual(self.run_case('esp32s3',kind,**{'1':-128,'2':0})[0],225)
        self.assertEqual(self.run_case('esp32c3',10,**{'1':-3,'2':1})[0],(-2)&v.MASK)
        self.assertEqual(self.run_case('esp32s3',10,**{'1':-3,'2':1})[0],254)
    def test_mode_narrowing_is_per_function(self):
        self.assertEqual(self.run_case('esp32s3',8,**{'1':256}),self.run_case('esp32s3',8,**{'1':0}))
        self.assertNotEqual(self.run_case('esp32c3',8,**{'1':256}),self.run_case('esp32c3',8,**{'1':0}))
        self.assertEqual(self.run_case('esp32s3',12,**{'1':257}),self.run_case('esp32s3',12,**{'1':0}))
        self.assertNotEqual(self.run_case('esp32s3',12,**{'1':257}),self.run_case('esp32s3',12,**{'1':1}))
    def test_two_delays_with_fresh_read(self):
        for chip in E:
            r=rows(self.run_case(chip,15,**{'14':v.MASK})[1]);self.assertEqual([x[0] for x in r],[7,8,10,7,8,10]);self.assertEqual([x[2] for x in r if x[0]==10],[1,1]);self.assertNotEqual(r[1][2],r[3][2])
    def test_callback_table_reload_and_chip_order(self):
        for chip,events in [('esp32c3',[4,1,5,6,4,1,5,6]),('esp32s3',[4,5,1,6])]:
            r=[x for x in rows(self.run_case(chip,7,**{'12':v.MASK,'13':v.MASK})[1]) if x[0] in (1,4,5,6)]
            self.assertEqual([x[0] for x in r],events)
            if chip=='esp32c3':self.assertNotEqual(r[3][1],r[7][1])
    def test_opaque_and_executed_internal_calls(self):
        for chip in E:
            normal=rows(self.run_case(chip,4)[1]);opaque=rows(self.run_case(chip,4,**{'15':0})[1]);self.assertGreater(len(normal),len(opaque));self.assertEqual([x for x in normal if x[0]==9],[x for x in opaque if x[0]==9])
    def test_disabled_frequency_does_not_program_offsets(self):
        for chip in E:
            r=rows(self.run_case(chip,14,**{'1':0})[1]);self.assertFalse(any(x[1] in (0x60006064,0x60006068) for x in r));self.assertEqual(len(r),12)
if __name__=='__main__':unittest.main()
