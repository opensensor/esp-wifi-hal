import copy,json,unittest
from pathlib import Path
import verify
DATA=json.loads(Path(__file__).with_name('original-instructions.json').read_text())
def rows(trace):return [trace[i:i+8] for i in range(0,len(trace),8)]
class FeatureContract(unittest.TestCase):
    def oracle(self,chip):return verify.Oracle(chip,DATA[chip])
    def test_backup_argument_width_pointer_and_result(self):
        for chip in DATA:
            c=verify.default_case(0);c[1:3]=0x80000101,0x3fc81234
            result,trace=self.oracle(chip).run(c)
            self.assertEqual(result,c[12]);self.assertEqual(rows(trace),[[9,0,0x80000101 if chip=='esp32c3' else 1,0x3fc81234,0,0,0,0]])
    def test_frequency_backup_return_is_void(self):
        for chip in DATA:
            c=verify.default_case(1);c[1:3]=256,4
            result,trace=self.oracle(chip).run(c)
            self.assertEqual(result,0);self.assertEqual(rows(trace),[[9,1,256 if chip=='esp32c3' else 0,4,0,0,0,0]])
    def test_c3_power_store_precedes_channel_read_and_direct_gain(self):
        c=verify.default_case(2);c[1]=0x123480;c[11]=1
        self.assertEqual(rows(self.oracle('esp32c3').run(c)[1]),[[2,1,0x98,128,0,0,0,0],[1,1,0x1f2,7^0x5b,0,0,0,0],[9,2,7^0x5b,0,0,0,0,0]])
    def test_s3_power_caches_table_before_store(self):
        c=verify.default_case(2);c[1]=0x123480;c[11]=1
        self.assertEqual(rows(self.oracle('esp32s3').run(c)[1]),[[4,0,0,0,0,0,0,0],[2,1,0x98,128,0,0,0,0],[5,0x264,0,0,0,0,0,0],[1,1,0x1f2,7^0x5b,0,0,0,0],[6,0x71000264,7^0x5b,0,0,0,0,0]])
    def test_mode_raw_argument_narrowing(self):
        for chip in DATA:
            c=verify.default_case(3);c[1:3]=256,256;c[3]=0
            t=rows(self.oracle(chip).run(c)[1]);calls=[r for r in t if r[0]==6]
            self.assertEqual([r[5] for r in calls],[63]*8 if chip=='esp32c3' else [0x81]*4+[0x7e]*4)
            self.assertEqual([r[4] for r in calls],[4,5,12,13,6,7,14,15]);self.assertTrue(all(r[3]==(1 if chip=='esp32c3' else 0) for r in calls))
    def test_disabled_state_is_reloaded_after_each_callback(self):
        for chip in DATA:
            c=verify.default_case(3);c[9:11]=255,255
            t=rows(self.oracle(chip).run(c)[1]);calls=[r for r in t if r[0]==6]
            self.assertEqual([r[5] for r in calls],[129,220,55,146,126,37,126,37])
            self.assertEqual([(r[1]-0x71000000)//0x1000 for r in calls],list(range(8)))
    def test_first_callback_load_order_differs(self):
        for chip in DATA:
            t=rows(self.oracle(chip).run(verify.default_case(3))[1]);kinds=[r[0] for r in t]
            self.assertEqual(kinds[:10],[4,2,2,5,7,8,7,8,1,6] if chip=='esp32c3' else [2,2,7,8,7,8,4,1,5,6])
    def test_enabled_computation_clamps_and_is_read_once(self):
        for chip in DATA:
            for raw,value in [(0,49),(1,50),(13,63),(255,63)]:
                c=verify.default_case(3);c[1]=1;c[3]=raw;c[9:11]=255,255
                t=rows(self.oracle(chip).run(c)[1]);self.assertEqual([r[5] for r in t if r[0]==6],[value]*8)
                self.assertEqual([r[2] for r in t if r[0]==1],[0x166])
    def test_register_width_order_and_unselected_bits(self):
        for chip in DATA:
            for enabled,narrow,bits in [(0,0,0),(1,0,16),(1,1,20)]:
                c=verify.default_case(3);c[1:3]=enabled,narrow;c[7:9]=0xffffffff,0xffffffff
                t=rows(self.oracle(chip).run(c)[1]);writes=[r for r in t if r[0]==8]
                self.assertEqual([(r[1],r[2]) for r in writes],[(0x6002600c,(0xffffffff&~0x1c)|bits),(0x6001c030,0xffffffff if not enabled else 0xffffffdf)])
    def test_reject_changed_code(self):
        e=copy.deepcopy(DATA['esp32s3']);e['functions'][0]['code_hex']='00'+e['functions'][0]['code_hex'][2:]
        with self.assertRaisesRegex(ValueError,'Code hash'):verify.Oracle('esp32s3',e)
    def test_reject_changed_instruction_bytes(self):
        e=copy.deepcopy(DATA['esp32c3']);f=e['functions'][0];p=f['instructions'][0].split();p[1]='00000000';f['instructions'][0]=' '.join(p)
        with self.assertRaisesRegex(ValueError,'Instruction bytes'):verify.Oracle('esp32c3',e)
    def test_reject_unknown_opcode(self):
        e=copy.deepcopy(DATA['esp32s3']);f=e['functions'][0];f['instructions'][0]=f['instructions'][0].replace('entry','unknown')
        with self.assertRaisesRegex(ValueError,'Unsupported'):verify.Oracle('esp32s3',e)
    def test_reject_missing_instruction(self):
        e=copy.deepcopy(DATA['esp32s3']);e['functions'][3]['instructions'].pop()
        with self.assertRaises(ValueError):verify.Oracle('esp32s3',e)
    def test_reject_missing_literal(self):
        e=copy.deepcopy(DATA['esp32s3']);e['literals'].clear()
        with self.assertRaisesRegex(ValueError,'literal'):verify.Oracle('esp32s3',e).run(verify.default_case(0))
    def test_reject_unknown_helper(self):
        e=copy.deepcopy(DATA['esp32c3']);e['symbols']['ram1_wifi_set_tx_gain']['address']='0x40000000'
        with self.assertRaisesRegex(ValueError,'Unknown helper'):verify.Oracle('esp32c3',e).run(verify.default_case(2))
    def test_reject_invalid_case_domains(self):
        for chip in DATA:
            o=self.oracle(chip)
            for c in ([0]*15,[-1]+[0]*15,[4]+[0]*15,[0]*15+[1]):
                with self.assertRaises(ValueError):o.run(c)
            for index,value in [(3,256),(9,256),(11,8),(14,1)]:
                c=verify.default_case(3);c[index]=value
                with self.assertRaises(ValueError):o.run(c)
if __name__=='__main__':unittest.main()
