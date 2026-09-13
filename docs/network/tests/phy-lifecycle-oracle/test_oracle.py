import copy
import json
from pathlib import Path
import unittest
from verify import Oracle, default_case

FIXTURE = json.loads(Path(__file__).with_name('original-instructions.json').read_text())


def oracle(chip, data=None):
    return Oracle(chip, data if data is not None else FIXTURE['chips'][chip])


def events(trace):
    return [trace[i:i+9] for i in range(0,len(trace),9)]


class OriginalBehavior(unittest.TestCase):
    def test_power_argument_semantics_differ(self):
        for chip in FIXTURE['chips']:
            o=oracle(chip)
            for arg in (0,1,2,255,256,257,0xffffffff):
                c=default_case(0);c[1],c[10]=arg,0
                _,trace=o.run(c)
                expected=((arg&1)<<22) if chip=='esp32c3' else (0xc00000 if arg&255 else 0)
                self.assertEqual(events(trace)[-1][2],expected)

    def test_c3_init_optional_callback_precedes_mmio(self):
        c=default_case(1);c[1],c[2],c[16],c[21]=1,4,64,0x80000001
        _,trace=oracle('esp32c3').run(c);ev=events(trace)
        self.assertEqual([e[0] for e in ev[:4]],[4,5,3,6])
        self.assertEqual(ev[2][1:4],[1,25,10])
        self.assertEqual(ev[3][3:9],[105,0,6,3,0,10])
        self.assertEqual(ev[-2][1:3],[0x60040058,c[10]^c[21]])

    def test_c3_init_skips_unused_invalid_index(self):
        for index in (5,255,0xffffffff):
            c=default_case(1);c[1],c[2]=0,index
            _,trace=oracle('esp32c3').run(c)
            self.assertEqual([e[0] for e in events(trace)],[7,8]*4)

    def test_s3_init_ignores_arguments_and_rereads_registers(self):
        c=default_case(1);c[14]=0x80000001
        expected=oracle('esp32s3').run(c)
        c[1],c[2]=0xffffffff,0xffffffff
        self.assertEqual(oracle('esp32s3').run(c),expected)
        ev=events(expected[1]);self.assertEqual([e[0] for e in ev],[7,8]*5)
        self.assertEqual([e[1] for e in ev[::2]],
                         [0x60008034,0x60008904,0x60008904,0x60008850,0x60008850])
        self.assertNotEqual(ev[3][2],ev[4][2])

    def test_xpd_always_sets_flag_but_only_first_call_powers_down(self):
        for chip in FIXTURE['chips']:
            o=oracle(chip)
            for flag in (0,1,255):
                c=default_case(2);c[9]=flag
                _,trace=o.run(c);ev=events(trace)
                self.assertEqual([e[0] for e in ev],[1,7,8,2] if flag==0 else [1,2])
                self.assertEqual(ev[-1][1:4],[1,0x31f if chip=='esp32c3' else 0x2a2,1])

    def test_s3_code_uses_all_three_dynamic_reads(self):
        c=default_case(3);c[10],c[14]=0x12345678,1
        result,trace=oracle('esp32s3').run(c);ev=events(trace)
        self.assertEqual(result,0x7f)
        self.assertEqual([e[2] for e in ev],
                         [0x12345679,0x13345679,0x1334567b,0x1234567b,0x1234567f])

    def test_c3_temp_power_truncates_and_sign_extends_low_byte(self):
        o=oracle('esp32c3')
        for delta,mode,expected in [(5,0,0),(6,0,1),(-4,0,0xffffffff),(-4,1,0),
                                    (-5,1,0xffffffff),(4,1,1),(512,1,0xffffff80)]:
            c=default_case(4);c[1],c[3]=delta&0xffffffff,mode
            self.assertEqual(o.run(c),(expected,[]))

    def test_s3_temp_power_signed_low_byte_threshold_and_unsigned_return(self):
        o=oracle('esp32s3')
        for delta,expected in [(4,0),(5,1),(-4,255),(-49,244),(-52,242),
                               (-1024,0),(-1020,1),(1280,0)]:
            c=default_case(4);c[1]=delta&0xffffffff
            self.assertEqual(o.run(c),(expected,[]))
            c[3]=0xffffffff
            self.assertEqual(o.run(c),(expected,[]))

    def test_temp_difference_wraps_to_signed_halfword(self):
        for chip in FIXTURE['chips']:
            c=default_case(4);c[1],c[2]=0x80000002,0x7ffffffe
            other=default_case(4);other[1]=4
            self.assertEqual(oracle(chip).run(c),oracle(chip).run(other))

    def test_c3_get_init_reloads_state_after_direct_measure(self):
        c=default_case(5);c[1],c[2]=0,0;c[16]=15;c[17]=17
        _,trace=oracle('esp32c3').run(c);ev=events(trace)
        self.assertEqual(ev[0],[9,0,0,0,0,0,0,0,0])
        self.assertEqual(ev[1][1:4],[1,0x204,17])
        self.assertEqual(ev[2][1:4],[2,0x20c,0x8000])
        writes=[e[2:4] for e in ev if e[0]==2]
        self.assertEqual(writes,[[0x210,0x8000],[0x96,0x8000],[0x94,0x7fff],[0x214,0x7fff]])

    def test_s3_get_init_narrows_second_flag_and_ignores_first(self):
        c=default_case(5);c[1],c[2]=0xffffffff,256;c[16]=7;c[17]=0
        _,trace=oracle('esp32s3').run(c);ev=events(trace)
        self.assertEqual([e[0] for e in ev[:3]],[4,5,6])
        self.assertEqual(ev[1][1],0x258)
        self.assertEqual([e[2:4] for e in ev if e[0]==2],
                         [[0x2c4,0xffff],[0x2c6,0xfedc],[0x96,0xffff],[0x94,0xfedc]])


class RejectUnsupportedEvidence(unittest.TestCase):
    def test_unknown_instruction(self):
        data=copy.deepcopy(FIXTURE['chips']['esp32c3'])
        data['functions'][0]['instructions'][0]=data['functions'][0]['instructions'][0].replace('lui','unknown')
        with self.assertRaisesRegex(ValueError,'Unsupported instruction'):
            oracle('esp32c3',data).run(default_case(0))

    def test_code_hash(self):
        data=copy.deepcopy(FIXTURE['chips']['esp32s3']);data['functions'][0]['body_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'Code hash'):
            oracle('esp32s3',data)

    def test_missing_reachable_instruction(self):
        data=copy.deepcopy(FIXTURE['chips']['esp32s3']);data['functions'][3]['instructions'].pop(4)
        with self.assertRaisesRegex(ValueError,'Unrecorded nonzero code'):
            oracle('esp32s3',data)

    def test_unrecorded_literal(self):
        data=copy.deepcopy(FIXTURE['chips']['esp32s3']);data['literals']={}
        with self.assertRaisesRegex(ValueError,'Unrecorded literal'):
            oracle('esp32s3',data).run(default_case(0))

    def test_unknown_mmio(self):
        data=copy.deepcopy(FIXTURE['chips']['esp32s3'])
        data['literals']['0x4203c030']='0x60008854'
        with self.assertRaisesRegex(ValueError,'Unmapped read'):
            oracle('esp32s3',data).run(default_case(0))

    def test_missing_direct_measure_boundary(self):
        data=copy.deepcopy(FIXTURE['chips']['esp32c3'])
        data['symbols']['__opensensor_tsens_outer']['address']='0x40000000'
        with self.assertRaisesRegex(ValueError,'Unknown callback target'):
            oracle('esp32c3',data).run(default_case(5))

    def test_unknown_callback_slot(self):
        data=copy.deepcopy(FIXTURE['chips']['esp32s3'])
        data['functions'][5]['instructions']=[s.replace('a10, a8, 0x258','a10, a8, 0x25c')
                                               for s in data['functions'][5]['instructions']]
        with self.assertRaisesRegex(ValueError,'Unknown callback slot'):
            oracle('esp32s3',data).run(default_case(5))

    def test_c3_rom_code_is_not_mislabeled_as_source_target(self):
        with self.assertRaisesRegex(ValueError,'Invalid case'):
            oracle('esp32c3').run(default_case(3))

    def test_invalid_active_init_index(self):
        c=default_case(1);c[1],c[2]=1,5
        with self.assertRaisesRegex(ValueError,'outside five-row domain'):
            oracle('esp32c3').run(c)

    def test_sixth_attribute_row(self):
        data=copy.deepcopy(FIXTURE['chips']['esp32c3']);data['attribute_bytes'] += [0]*6
        with self.assertRaisesRegex(ValueError,'Expected five attribute rows'):
            oracle('esp32c3',data)

    def test_invalid_header(self):
        for case in ([0]*21,[0]*23):
            with self.assertRaisesRegex(ValueError,'Invalid case words'):
                oracle('esp32c3').run(case)


if __name__ == '__main__':
    unittest.main()
