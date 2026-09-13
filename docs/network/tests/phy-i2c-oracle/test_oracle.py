import copy
import json
from pathlib import Path
import unittest
from verify import Oracle,default_case

FIXTURE=json.loads(Path(__file__).with_name('original-instructions.json').read_text())


def oracle(chip,data=None):
    return Oracle(chip,data if data is not None else FIXTURE['chips'][chip])


def events(chip,case):
    result,trace=oracle(chip).run(case)
    if result!=0:raise AssertionError('Void result must be normalized to zero')
    return [trace[i:i+9] for i in range(0,len(trace),9)]


def calls(ev):return [e for e in ev if e[0]==6]


class OriginalBehavior(unittest.TestCase):
    def test_c3_data_store_widths_and_constants(self):
        ev=events('esp32c3',default_case(0))
        self.assertEqual([e[0] for e in ev],[2]*7)
        self.assertEqual([e[1:4] for e in ev],
                         [[1,0xbd,27],[2,0xbe,0x877],[4,0xc0,0x5f080aa4],
                          [4,0xc4,0x7f05740a],[4,0xc8,0x3f02f000],[4,0xcc,0x410ff3a8],[1,0xd0,38]])

    def test_s3_data_revision_and_unsorted_store_order(self):
        for revision in (0,1,2,255):
            c=default_case(0);c[4]=revision;ev=events('esp32s3',c)
            self.assertEqual(ev[2][:4],[1,1,0x20d,revision])
            writes=[e for e in ev if e[0]==2]
            self.assertTrue(all(e[1]==1 for e in writes))
            self.assertEqual([e[2] for e in writes],
                             [0xbd,0xbe,0xbf,0xc1,0xc4,0xc5,0xc6,0xc7,0xc8,0xc9,0xca,0xcb,
                              0xcc,0xcd,0xce,0xc0,0xcf,0xc2,0xc3,0xd0])
            data={e[2]:e[3] for e in writes}
            self.assertEqual((data[0xbf],data[0xc0]),(7,148) if revision==1 else (8,164))
            self.assertEqual([data[k] for k in (0xce,0xcf)],[148,68])

    def test_bias_argument_narrowing_differs(self):
        for argument in (0,1,2,255,256,257,0x80000000,0xffffffff):
            c=default_case(1);c[1]=argument
            c3=events('esp32c3',c);s3=calls(events('esp32s3',c))
            self.assertEqual(c3[0][0],9 if argument&1 else 10)
            self.assertEqual(s3[0][6],252 if argument&255 else 119)

    def test_c3_bias_direct_callback_can_change_cache(self):
        c=default_case(1);c[20]=1;c[22]=77
        ev=events('esp32c3',c)
        self.assertEqual(ev[0][0],9);self.assertEqual(ev[1][:4],[1,1,0x9f,77])
        self.assertEqual([e[1] for e in calls(ev)],[0x1b4,0x1bc])
        self.assertEqual(calls(ev)[0][6],77)

    def test_c3_bias_signed16_subtraction_and_byte_store(self):
        for raw,written in [(0,60),(74,60),(75,60),(255,240),(256,241),
                            (32782,255),(32783,60),(65535,60),(0xa5a50080,113)]:
            c=default_case(1);c[14]=raw
            ev=events('esp32c3',c)
            self.assertEqual([e[3] for e in ev if e[0]==2 and e[2] in (0x9f,0xa0)],[written,written])

    def test_c3_bias_preserves_table_param_slot_store_order(self):
        ev=events('esp32c3',default_case(1));at=next(i for i,e in enumerate(ev) if e[:3]==[2,1,0x9f])
        self.assertEqual([e[0] for e in ev[at+1:at+6]],[4,1,5,2,6])
        self.assertEqual(calls(ev)[-1][3:],[97,0,5,6,6,1])

    def test_s3_bias_reads_revision_after_callback_and_second_slot(self):
        c=default_case(1);c[20]=1;c[22]=1
        ev=events('esp32s3',c)
        self.assertEqual([e[0] for e in ev],[4,5,6,4,5,1,6])
        self.assertEqual(ev[-2][:4],[1,1,0x20d,0])
        self.assertEqual(ev[-1][3:7],[106,0,1,124])

    def test_pll_initial_writes_and_saved_bytes_differ(self):
        for chip in FIXTURE['chips']:
            ev=events(chip,default_case(2));cb=calls(ev)
            self.assertEqual([e[3:] for e in cb[:3]],
                             [[102,0,9,3,2,3],[102,0,9,5,4,2],[102,0,10,1,0,1]])
            writes=[e[2:4] for e in ev if e[0]==2]
            self.assertEqual(writes,[[0xd1,128],[0xd2,120],[0x31d,33],[0x31e,255]]
                             if chip=='esp32c3' else [[0xd1,128],[0xd2,120],[0x2a1,33]])

    def test_pll_table_slot_store_order_differs(self):
        for chip in FIXTURE['chips']:
            ev=events(chip,default_case(2));at=next(i for i,e in enumerate(ev) if e[0]==6 and e[1]==(0x1ac if chip=='esp32c3' else 0x188))
            self.assertEqual([e[0] for e in ev[at+1:at+5]],
                             [4,2,5,6] if chip=='esp32c3' else [4,5,2,6])

    def test_pll_gate_observes_read_callback_mutation(self):
        for chip in FIXTURE['chips']:
            c=default_case(2);c[20]=1<<(6 if chip=='esp32c3' else 4);c[22]=1
            ev=events(chip,c)
            self.assertFalse(any(e[0]==6 and e[1]==(0x1bc if chip=='esp32c3' else 0x198)
                                 and e[3:]==[102,0,5,7,7,0] for e in ev))
            self.assertEqual([e[3] for e in ev if e[0]==1],[1])

    def test_init_callbacks_all_reload_table_including_high_mutation_bit(self):
        for chip in FIXTURE['chips']:
            c=default_case(3);c[18:20]=[0xffffffff,0xffffffff];ev=events(chip,c)
            self.assertEqual(len(calls(ev)),33)
            self.assertEqual([e[1] for e in ev if e[0]==4],list(range(33)))
            self.assertEqual([e[2] for e in ev if e[0]==5],list(range(33)))

    def test_init_fixed_chip_specific_values_and_hosts(self):
        for chip in FIXTURE['chips']:
            cb=calls(events(chip,default_case(3)))
            self.assertEqual(cb[11][3:7],[103,1,55,85] if chip=='esp32c3' else [103,0,55,0])
            self.assertEqual(cb[-2][3:7],[98,1,11,104] if chip=='esp32c3' else [98,1,11,72])

    def test_c3_init_caches_three_values_before_callbacks(self):
        c=default_case(3);c[11:14]=[253,49,57];c[20]=1;c[22]=1
        ev=events('esp32c3',c);cb=calls(ev)
        self.assertEqual([e[2] for e in ev[:3]],[0x16d,0x16e,0x16c])
        values={e[5]:e[6] for e in cb if e[3]==103 and e[1]==0x1b4}
        self.assertEqual([values[k] for k in (28,29,22,23,30,31)],[48,59,1,1,56,60])

    def test_s3_init_wraps_underflow_before_unsigned_floor(self):
        for raw,expected in [(0,246),(1,247),(9,255),(10,5),(14,5),(15,5),(16,6),(255,245)]:
            c=default_case(3);c[12]=raw
            cb=calls(events('esp32s3',c));r29=[e for e in cb if e[3:6]==[103,0,29]][0]
            self.assertEqual(r29[6],expected)

    def test_s3_init_capture_at_thirteenth_call_and_fresh_pair_reads(self):
        c=default_case(3);c[12]=20;c[20]=1<<12;c[22]=1
        ev=events('esp32s3',c);cb=calls(ev)
        at=next(i for i,e in enumerate(ev) if e==cb[12])
        self.assertEqual(ev[at-1][:3],[1,1,0x16d])
        values={e[5]:e[6] for e in cb if e[3]==103 and e[1]==0x190}
        self.assertEqual([values[k] for k in (4,5,28,29)],[11,10,21,10])

    def test_s3_bias_padding_excluded(self):
        o=oracle('esp32s3');self.assertNotIn(0x4203f021,o.program);self.assertIn(0x4203f022,o.program)


class RejectUnsupportedEvidence(unittest.TestCase):
    def test_unknown_instruction(self):
        data=copy.deepcopy(FIXTURE['chips']['esp32c3'])
        data['functions'][0]['instructions'][0]=data['functions'][0]['instructions'][0].replace('lui','unknown')
        with self.assertRaisesRegex(ValueError,'Unsupported instruction'):oracle('esp32c3',data).run(default_case(0))

    def test_code_hash(self):
        data=copy.deepcopy(FIXTURE['chips']['esp32s3']);data['functions'][0]['body_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'Code hash'):oracle('esp32s3',data)

    def test_instruction_bytes(self):
        data=copy.deepcopy(FIXTURE['chips']['esp32s3'])
        data['functions'][0]['instructions'][0]=data['functions'][0]['instructions'][0].replace('004136','004137')
        with self.assertRaisesRegex(ValueError,'Instruction bytes'):oracle('esp32s3',data)

    def test_missing_reachable_instruction(self):
        data=copy.deepcopy(FIXTURE['chips']['esp32s3']);data['functions'][0]['instructions'].pop(4)
        with self.assertRaisesRegex(ValueError,'Unrecorded nonzero code'):oracle('esp32s3',data)

    def test_missing_literal(self):
        data=copy.deepcopy(FIXTURE['chips']['esp32s3']);data['literals']={}
        with self.assertRaisesRegex(ValueError,'Unrecorded literal'):oracle('esp32s3',data).run(default_case(0))

    def test_unknown_parameter_address(self):
        data=copy.deepcopy(FIXTURE['chips']['esp32s3']);data['literals']['0x42010d5c']='0x60000000'
        with self.assertRaisesRegex(ValueError,'Non-stack store'):oracle('esp32s3',data).run(default_case(0))

    def test_unknown_slot(self):
        data=copy.deepcopy(FIXTURE['chips']['esp32s3'])
        data['functions'][1]['instructions']=[line.replace('0x190','0x194') for line in data['functions'][1]['instructions']]
        with self.assertRaisesRegex(ValueError,'Unknown callback slot'):oracle('esp32s3',data).run(default_case(1))

    def test_missing_direct_bias_boundary(self):
        data=copy.deepcopy(FIXTURE['chips']['esp32c3']);data['symbols']['bias_dreg_i2c_set']['address']='0x40000000'
        with self.assertRaisesRegex(ValueError,'Unknown callback target'):oracle('esp32c3',data).run(default_case(1))

    def test_missing_direct_part_boundary(self):
        data=copy.deepcopy(FIXTURE['chips']['esp32c3']);data['symbols']['bias_dreg_i2c_set.part.0']['address']='0x40000000'
        c=default_case(1);c[1]=0
        with self.assertRaisesRegex(ValueError,'Unknown callback target'):oracle('esp32c3',data).run(c)

    def test_invalid_header(self):
        for c in ([0]*23,[0]*25):
            with self.assertRaisesRegex(ValueError,'Invalid case words'):oracle('esp32c3').run(c)
        for field in (0,23):
            c=default_case(0);c[field]=4
            with self.assertRaisesRegex(ValueError,'Invalid case'):oracle('esp32c3').run(c)


if __name__=='__main__':unittest.main()
