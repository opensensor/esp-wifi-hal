import copy,json,unittest
from pathlib import Path
import verify
DATA=json.loads(Path(__file__).with_name('original-instructions.json').read_text())
def rows(trace):return [trace[i:i+8] for i in range(0,len(trace),8)]
class DebugContract(unittest.TestCase):
    def oracle(self,chip):return verify.Oracle(chip,DATA[chip])
    def test_iq_signed_width_and_order(self):
        for chip in DATA:
            for packed,selector,expected in [(0x420,0,[240,224]),(0x420,1,[16,224]),(0x81f,0,[0,31]),(0x81f,1,[224,31])]:
                c=verify.default_case(0);c[1:3]=packed,selector
                result,trace=self.oracle(chip).run(c)
                self.assertEqual(result,0)
                self.assertEqual(rows(trace),[[1,0x200003,0,expected[0],0,0,0,0],[1,0x200003,1,expected[1],0,0,0,0]])
    def test_selector_high_bits_differ(self):
        for chip in DATA:
            c=verify.default_case(0);c[1:3]=0x420,256
            self.assertEqual(rows(self.oracle(chip).run(c)[1])[0][3],16 if chip=='esp32c3' else 240)
    def test_high_packed_bits_do_not_affect_outputs(self):
        for chip in DATA:
            c=verify.default_case(0);c[1:3]=0x420,1;o=self.oracle(chip);expected=o.run(c)
            for bit in range(12,32):
                c[1]=0x420|(1<<bit);self.assertEqual(o.run(c),expected)
    def test_bias_order_cleanup_and_raw_return(self):
        for chip in DATA:
            c=verify.default_case(1);c[3]=0xdeadbeef
            result,t=self.oracle(chip).run(c);r=rows(t)
            self.assertEqual(result,c[3]);self.assertEqual([x[0] for x in r],[4,5,6]*5)
            self.assertEqual([x[2:] for x in r if x[0]==6],[[106,0,2,1,1,1],[106,0,7,3,2,1],[3,0,0,0,0,0],[106,0,2,1,1,0],[106,0,7,3,2,0]])
    def test_every_callback_reloads_mutated_table(self):
        for chip in DATA:
            c=verify.default_case(2);c[5]=4095;c[7]=1
            _,t=self.oracle(chip).run(c);r=rows(t)
            self.assertEqual([x[1] for x in r if x[0]==4],list(range(1,13)))
            self.assertEqual([(x[1]-0x71000000)//0x1000 for x in r if x[0]==6],list(range(1,13)))
    def test_voltage_zero_bias_skips_narrowing_and_cleans_up(self):
        for chip in DATA:
            c=verify.default_case(2);c[3:5]=0,0xdeadbeef
            result,t=self.oracle(chip).run(c)
            self.assertEqual(result,0xdeadbeef);calls=[x for x in rows(t) if x[0]==6]
            self.assertEqual(len(calls),12);self.assertEqual(calls[-3][2:],[107,0,9,7,7,0]);self.assertEqual(calls[-2][2:],[4,1,0,0,0,0]);self.assertEqual(calls[-1][2:],[0]*6)
    def test_voltage_signed_wrapping_arithmetic(self):
        for chip in DATA:
            for bias,sample,expected in [(1024,900,3375),(3,0xffffffff,64256),(0xffffffff,0x800000,0),(0x80000000,0x7fffffff,0),(2,1,1920)]:
                c=verify.default_case(2);c[3:5]=bias,sample
                self.assertEqual(self.oracle(chip).run(c)[0],expected)
    def test_composed_and_opaque_bias_share_voltage_suffix(self):
        for chip in DATA:
            c=verify.default_case(2);o=self.oracle(chip);composed=o.run(c);c[6]=0;opaque=o.run(c)
            self.assertEqual(composed[0],opaque[0]);self.assertEqual(rows(composed[1])[16:],rows(opaque[1])[1:])
    def test_void_callback_clobbers_do_not_replace_return(self):
        for chip in DATA:
            for seed in [0,1,0xffffffff,0x80000000]:
                c=verify.default_case(2);c[8]=seed
                self.assertEqual(self.oracle(chip).run(c)[0],3375)
    def test_reject_changed_code(self):
        e=copy.deepcopy(DATA['esp32s3']);e['functions'][0]['code_hex']='ff'+e['functions'][0]['code_hex'][2:]
        with self.assertRaisesRegex(ValueError,'Code hash'):verify.Oracle('esp32s3',e)
    def test_reject_changed_instruction_bytes(self):
        e=copy.deepcopy(DATA['esp32c3']);f=e['functions'][0];p=f['instructions'][0].split();p[1]='00000000';f['instructions'][0]=' '.join(p)
        with self.assertRaisesRegex(ValueError,'Instruction bytes'):verify.Oracle('esp32c3',e)
    def test_reject_unknown_opcode(self):
        e=copy.deepcopy(DATA['esp32s3']);f=e['functions'][0];f['instructions'][0]=f['instructions'][0].replace('entry','unknown')
        with self.assertRaisesRegex(ValueError,'Unsupported'):verify.Oracle('esp32s3',e)
    def test_reject_missing_instruction(self):
        e=copy.deepcopy(DATA['esp32s3']);e['functions'][0]['instructions'].pop()
        with self.assertRaises(ValueError):verify.Oracle('esp32s3',e)
    def test_reject_missing_or_changed_literal(self):
        for changed in [False,True]:
            e=copy.deepcopy(DATA['esp32s3'])
            if changed:e['literals']={k:'0x12345678' for k in e['literals']}
            else:e['literals'].clear()
            with self.assertRaisesRegex(ValueError,'literal'):verify.Oracle('esp32s3',e).run(verify.default_case(1))
    def test_reject_unknown_direct_helper(self):
        e=copy.deepcopy(DATA['esp32c3']);f=e['functions'][2]
        f['instructions']=[line.rsplit(' ',1)[0]+' 42000000' if ' jal ' in line else line for line in f['instructions']]
        with self.assertRaisesRegex(ValueError,'Unknown helper'):verify.Oracle('esp32c3',e).run(verify.default_case(2))
    def test_reject_invalid_case_domains(self):
        for chip in DATA:
            o=self.oracle(chip)
            for c in ([0]*15,[-1]+[0]*15,[3]+[0]*15,[0]*15+[1]):
                with self.assertRaises(ValueError):o.run(c)
            for i,value in [(5,4096),(6,2),(7,2),(9,1)]:
                c=verify.default_case(2);c[i]=value
                with self.assertRaises(ValueError):o.run(c)
if __name__=='__main__':unittest.main()
