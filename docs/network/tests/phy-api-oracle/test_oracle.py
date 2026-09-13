import copy
import json
from pathlib import Path
import unittest
import verify

DATA=json.loads(Path(__file__).with_name('original-instructions.json').read_text())
def events(trace):return [trace[i:i+5] for i in range(0,len(trace),5)]

class Contract(unittest.TestCase):
    def test_wakeup_reads_gate_after_helper(self):
        for chip,e in DATA.items():
            o=verify.Oracle(chip,e);c=verify.default_case(0);c[2]=0x20;c[7]=1;c[9]=0
            _,trace=o.run(c);t=events(trace)
            self.assertEqual(t[0],[9,0,0,0,0]);self.assertEqual(t[1],[1,4,0x120,0,0])
            self.assertIn([9,1,0,0,0],t)
            c[2]=0;c[9]=0x20
            self.assertEqual(events(o.run(c)[1]),[[9,0,0,0,0],[1,4,0x120,0x20,0]])
    def test_callback_uses_current_table_and_channel_then_reloads_word(self):
        for chip,e in DATA.items():
            o=verify.Oracle(chip,e);c=verify.default_case(0);c[7]=6;c[8]=3;c[11]=0x80000081;c[13]=0xf4
            t=events(o.run(c)[1]);slot=0xd8 if chip=='esp32c3' else 0xcc
            self.assertEqual(t[3:7],[[4,2,0,0,0],[1,1,0x1f2,0xf4,0],[5,slot,2,0,0],[6,slot,2,0xf4,0]])
            self.assertEqual(t[-2:],[[1,4,0x120,0x80000081,0],[2,4,0x120,0x800000a1,0]])
    def test_shutdown_order_and_conditional_measurement(self):
        o=verify.Oracle('esp32c3',DATA['esp32c3']);c=verify.default_case(1);c[7]=24
        self.assertEqual(events(o.run(c)[1]),[[1,1,0x31f,0,0],[9,3,0,0,0],[9,4,0,0,0],[2,1,0x320,1,0]])
        c[4]=128
        self.assertEqual(events(o.run(c)[1]),[[1,1,0x31f,128,0],[9,4,0,0,0],[2,1,0x320,1,0]])
        self.assertEqual(events(verify.Oracle('esp32s3',DATA['esp32s3']).run(c)[1]),[[9,4,0,0,0]])
    def test_seed_preserves_high_25_bits_and_access_width(self):
        o=verify.Oracle('esp32s3',DATA['esp32s3']);c=verify.default_case(3);c[1]=0xffffffad;c[6]=0x87654321
        self.assertEqual(events(o.run(c)[1]),[[7,0x6001c400,0x87654321,0,0],[8,0x6001c400,0x8765432d,0,0]])
    def test_calibration_versions(self):
        for chip,value in [('esp32c3',1232),('esp32s3',711)]:
            self.assertEqual(verify.Oracle(chip,DATA[chip]).run(verify.default_case(2)),(value,[]))
    def test_rejects_changed_code_hash(self):
        e=copy.deepcopy(DATA['esp32s3']);e['functions'][0]['code_hex']='00'+e['functions'][0]['code_hex'][2:]
        with self.assertRaisesRegex(ValueError,'Code hash'):verify.Oracle('esp32s3',e)
    def test_rejects_changed_instruction_bytes(self):
        e=copy.deepcopy(DATA['esp32c3']);f=e['functions'][0];line=f['instructions'][0].split();line[1]='0000';f['instructions'][0]=' '.join(line)
        with self.assertRaisesRegex(ValueError,'Instruction bytes'):verify.Oracle('esp32c3',e)
    def test_rejects_missing_instruction(self):
        e=copy.deepcopy(DATA['esp32s3']);e['functions'][0]['instructions'].pop()
        with self.assertRaises(ValueError):verify.Oracle('esp32s3',e)
    def test_rejects_unknown_opcode(self):
        e=copy.deepcopy(DATA['esp32c3']);f=e['functions'][0];f['instructions'][0]=f['instructions'][0].replace('addi','unknown')
        with self.assertRaisesRegex(ValueError,'Unsupported'):verify.Oracle('esp32c3',e)
    def test_rejects_missing_literal(self):
        e=copy.deepcopy(DATA['esp32s3']);e['literals'].clear()
        with self.assertRaisesRegex(ValueError,'literal'):verify.Oracle('esp32s3',e).run(verify.default_case(0))
    def test_rejects_unknown_callback_slot(self):
        e=copy.deepcopy(DATA['esp32s3'])
        # A changed slot operand is rejected when executed, even though this
        # test deliberately leaves the original code-byte evidence intact.
        f=e['functions'][0]
        index=next(i for i,s in enumerate(f['instructions']) if 'l32i a8, a8, 204' in s)
        f['instructions'][index]=f['instructions'][index].replace('204','208')
        with self.assertRaisesRegex(ValueError,'Unknown table slot'):verify.Oracle('esp32s3',e).run(verify.default_case(0))
    def test_rejects_bad_case_domain(self):
        for chip,e in DATA.items():
            o=verify.Oracle(chip,e)
            for mutation in ([0]*15,[-1]+[0]*15,[4]+[0]*15):
                with self.assertRaises(ValueError):o.run(mutation)

if __name__=='__main__':unittest.main()
