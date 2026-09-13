import copy
import json
from pathlib import Path
import unittest
import verify
DATA=json.loads(Path(__file__).with_name('original-instructions.json').read_text())
def events(trace):return [trace[i:i+5] for i in range(0,len(trace),5)]
class Contract(unittest.TestCase):
    def test_idle_hosts_are_only_read_between_critical_calls(self):
        for chip,e in DATA.items():
            self.assertEqual(events(verify.Oracle(chip,e).run(verify.default_case(0))[1]),
                [[9,0,0,0,0],[7,0x6000e000,0,0,0],[7,0x6000e004,0,0,0],[9,0,0,0,0]])
    def test_reset_writes_exact_command_and_polls_hosts_in_order(self):
        for chip,e in DATA.items():
            c=verify.default_case(0);c[2:8]=[0xffffffff,1<<25,2,1,0,0]
            t=events(verify.Oracle(chip,e).run(c)[1])
            self.assertEqual(t,[[9,0,0,0,0],[7,0x6000e000,0xffffffff,0,0],[8,0x6000e000,1<<26,0,0],
                [7,0x6000e000,1<<25,0,0],[7,0x6000e000,1<<25,0,0],[7,0x6000e000,0,0,0],
                [7,0x6000e004,1<<25,0,0],[8,0x6000e004,1<<26,0,0],[7,0x6000e004,1<<25,0,0],
                [7,0x6000e004,0,0,0],[9,0,0,0,0]])
    def test_reads_observe_critical_entry_effect(self):
        for chip,e in DATA.items():
            c=verify.default_case(0);c[11]=1<<25
            t=events(verify.Oracle(chip,e).run(c)[1]);self.assertEqual(sum(row[0]==8 for row in t),2)
    def test_channel_argument_width_differs_by_chip(self):
        for chip,e in DATA.items():
            c=verify.default_case(1);c[1]=257;c[8]=0
            t=events(verify.Oracle(chip,e).run(c)[1]);enabled=chip=='esp32s3'
            self.assertEqual(t,[[7,0x6001c400,0,0,0],[8,0x6001c400,0x2000 if enabled else 0x6000,0,0],
                [1,1,0xe4 if enabled else 0x98,0x81 if enabled else 0x7e,0],[9,1,0xffffff81 if enabled else 0x7e,0,0]])
    def test_power_signed_and_masks_preserve_unselected_bits(self):
        for chip,e in DATA.items():
            c=verify.default_case(1);c[1]=1;c[8]=0xffffffff;c[9]=0x80
            t=events(verify.Oracle(chip,e).run(c)[1]);self.assertEqual(t[1][2],0xffffbfff);self.assertEqual(t[-1][2],0xffffff80)
    def test_interpolation_rounds_toward_zero_and_wraps_result(self):
        o=verify.Oracle('esp32s3',DATA['esp32s3']);c=verify.default_case(2);c[1]=2;c[12:14]=[10,255]
        self.assertEqual(o.run(c)[0],8)
        c[12:14]=[255,10];self.assertEqual(o.run(c)[0],1)
        c[1]=12;c[14]=254;self.assertEqual(o.run(c),(0,[3,1,2,254,0]))
    def test_interpolation_read_order_and_raw_channel_alias(self):
        o=verify.Oracle('esp32s3',DATA['esp32s3']);c=verify.default_case(2)
        for channel,indexes in [(1,[0,1]),(257,[0,1]),(7,[2,1]),(11,[2,1]),(12,[2]),(0,[2])]:
            c[1]=channel;t=events(o.run(c)[1]);self.assertEqual([r[2] for r in t],indexes)
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
    def test_rejects_unknown_helper(self):
        e=copy.deepcopy(DATA['esp32c3']);e['symbols']['phy_set_most_tpw']['address']='0x40000000'
        with self.assertRaisesRegex(ValueError,'Unknown helper'):verify.Oracle('esp32c3',e).run(verify.default_case(1))
    def test_rejects_bad_case_domain(self):
        for chip,e in DATA.items():
            o=verify.Oracle(chip,e)
            for c in ([0]*15,[-1]+[0]*15,[3]+[0]*15,[0]*15+[1]):
                with self.assertRaises(ValueError):o.run(c)
    def test_rejects_unbounded_synthetic_poll_count(self):
        c=verify.default_case(0);c[4]=9
        with self.assertRaisesRegex(ValueError,'case domain'):verify.Oracle('esp32c3',DATA['esp32c3']).run(c)
if __name__=='__main__':unittest.main()
