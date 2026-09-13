import copy
import hashlib
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
    def test_c3_force_tests_full_register(self):
        o=oracle('esp32c3');base=default_case(0);base[1]=1
        expected=o.run(base)
        for argument in (2,255,256,257,0x10000,0x80000000,0xffffffff):
            c=base.copy();c[1]=argument
            self.assertEqual(o.run(c),expected)
        ev=events(expected[1])
        self.assertEqual([e[0] for e in ev],[7,8,7,8])
        self.assertEqual([e[1] for e in ev],[0x6000610c]*2+[0x60006104]*2)

    def test_c3_disable_gate_skips_delay(self):
        for gate in (0,1,0xfffffffd):
            c=default_case(0);c[22]=gate
            ev=events(oracle('esp32c3').run(c)[1])
            self.assertEqual([e[0] for e in ev],[7,8,7,8,7])
            self.assertEqual(ev[-1][1],0x6002600c)

    def test_c3_delay_effects_and_fresh_mmio_reads(self):
        c=default_case(0);c[8]=1
        ev=events(oracle('esp32c3').run(c)[1])
        self.assertEqual([e[0] for e in ev],[7,8,7,8,7,9,7,8,7,8,9,7,8])
        self.assertEqual([e[1] for e in ev if e[0]==9],[1,2])
        self.assertEqual([e[2] for e in ev if e[0]==7 and e[1]==0x6001c02c],
                         [0xdaa55aac,0x32a55abc,0x68ffff39])
        self.assertEqual(ev[-1][2],0x687fff39)

    def test_debug_read_order_and_individual_table_loads(self):
        for chip in FIXTURE['chips']:
            c=default_case(1);c[5]=63
            ev=events(oracle(chip).run(c)[1])
            self.assertEqual([e[0] for e in ev[:6]],
                             [1,1,4,5,1,6] if chip=='esp32c3' else [1,1,1,4,5,6])
            self.assertEqual([e[1] for e in ev if e[0]==4],list(range(6)))
            self.assertEqual([e[2] for e in ev if e[0]==5],list(range(6)))
            self.assertEqual([e[2] for e in ev if e[0]==6],list(range(6)))

    def test_debug_keeps_captured_mode_and_gain_after_helper_mutation(self):
        for chip in FIXTURE['chips']:
            c=default_case(1);c[6]=63
            ev=events(oracle(chip).run(c)[1])
            calls=[e for e in ev if e[0]==6]
            self.assertEqual(calls[2][3:5],[0xf5,0xfc91])
            self.assertEqual(calls[3][3],0xfc91)

    def test_index_can_overlap_captured_data(self):
        # C3 index65 puts +a3 in the high byte of the selected halfword.
        c=default_case(1);c[2]=65
        ev=events(oracle('esp32c3').run(c)[1])
        halfword=[e for e in ev if e[0]==1 and e[1]==2][0]
        self.assertEqual(halfword[2],0xa2)
        self.assertEqual(halfword[3]>>8,65)
        # S3 index246 selects the halfword beginning at the index byte +20c.
        c[2]=246
        ev=events(oracle('esp32s3').run(c)[1])
        halfword=[e for e in ev if e[0]==1 and e[1]==2][0]
        self.assertEqual(halfword[2],0x20c)
        self.assertEqual(halfword[3]&255,246)

    def test_debug_pointer_offset_abi_and_wrapping(self):
        expected={'esp32c3':0xfff8012c,'esp32s3':0x12c}
        for chip in FIXTURE['chips']:
            c=default_case(1);c[4]=0xffff0001
            calls=[e for e in events(oracle(chip).run(c)[1]) if e[0]==6]
            self.assertEqual(calls[4][3],expected[chip])
            c[4]=0xffffffff
            calls=[e for e in events(oracle(chip).run(c)[1]) if e[0]==6]
            self.assertEqual(calls[4][3],0x11c if chip=='esp32c3' else 0x8011c)

    def test_work_direct_stop_then_fresh_table_for_each_callback(self):
        for chip in FIXTURE['chips']:
            c=default_case(2);c[5]=63
            ev=events(oracle(chip).run(c)[1])
            self.assertEqual(ev[0],[10,1,0,0,0,0,0,0,0])
            self.assertEqual([e[0] for e in ev],[10,4,5,6,4,5,6,4,5,6])
            self.assertEqual([e[1] for e in ev if e[0]==4],[1,2,3])
            self.assertTrue(all(e[3:]==[0]*6 for e in ev if e[0]==6))

    def test_save_alternates_read_and_param_store(self):
        for chip in FIXTURE['chips']:
            c=default_case(3);c[8]=1
            ev=events(oracle(chip).run(c)[1]);offset=0x328 if chip=='esp32c3' else 0x2ac
            self.assertEqual([e[0] for e in ev],[7,2]*6)
            for i in range(6):
                read,write=ev[2*i:2*i+2]
                self.assertEqual(read[1:3],[0x600060e0+4*i,c[14+i]^(1<<i)])
                self.assertEqual(write[1:4],[4,offset+4*i,read[2]])

    def test_pbus_all_twelve_jump_table_stages(self):
        expected={
            'esp32c3':[0x300,0x05040300,0xd06,0x0f0e0d06,0x1210,0x14131210,
                       0x1815,0x1a191815,0x221b,0x2423221b,0x2725,0x29282725],
            'esp32s3':[0x300,0x06040300,0xe07,0x110f0e07,0x1412,0x16151412,
                       0x1a17,0x1d1b1a17,0x251e,0x2826251e,0x2b29,0x2d2c2b29],
        }
        for chip in FIXTURE['chips']:
            c=default_case(4);c[12:]=[0]*12
            ev=events(oracle(chip).run(c)[1])
            selectors=[e for e in ev if e[0]==8 and 0x600060e0<=e[1]<=0x600060f4]
            self.assertEqual([e[1] for e in selectors],[0x600060e0+4*(i//2) for i in range(12)])
            self.assertEqual([e[2] for e in selectors],expected[chip])
            self.assertEqual([e[0] for e in ev[-12:]],[7,2]*6)

    def test_pbus_constant_copy_and_chip_specific_patches(self):
        words={}
        for chip in FIXTURE['chips']:
            ev=events(oracle(chip).run(default_case(4))[1])
            words[chip]=[e[2] for e in ev if e[0]==8 and e[1]==0x600060cc]
            self.assertEqual(len(words[chip]),42 if chip=='esp32c3' else 46)
            self.assertEqual(words[chip][:4],[0x709ff,0x1713ff,0xf50000,0xf60000])
        self.assertEqual(words['esp32c3'][27:35],
                         [0x403ff,0x14fdff,0x1801ff,0x4801ff,0xf00000,0xf10000,0xf20000,0xf40000])
        self.assertEqual(words['esp32s3'][30:38],
                         [0x403ff,0x14f9ff,0x1801ff,0x4831ff,0xf00000,0xf10000,0xf20000,0xf40000])

    def test_pbus_control_reread_survives_dynamic_changes(self):
        for chip in FIXTURE['chips']:
            c=default_case(4);c[8]=0x80000001
            ev=events(oracle(chip).run(c)[1])
            writes=[i for i,e in enumerate(ev) if e[0]==8 and e[1]==0x600060cc]
            for i in writes:
                self.assertEqual([e[0] for e in ev[i:i+5]],[8,7,8,7,8])
                self.assertNotEqual(ev[i+2][2],ev[i+3][2])

    def test_s3_padding_is_not_an_instruction(self):
        o=oracle('esp32s3')
        self.assertNotIn(0x4203ac51,o.program)
        self.assertEqual(o.program[0x4203ac52][1:],('addi',['a9','a1','96']))
        o.run(default_case(4))


class RejectUnsupportedEvidence(unittest.TestCase):
    def test_unknown_instruction(self):
        data=copy.deepcopy(FIXTURE['chips']['esp32c3'])
        data['functions'][0]['instructions'][0]=data['functions'][0]['instructions'][0].replace('lui','unknown')
        with self.assertRaisesRegex(ValueError,'Unsupported instruction'):
            oracle('esp32c3',data).run(default_case(0))

    def test_code_hash(self):
        data=copy.deepcopy(FIXTURE['chips']['esp32s3']);data['functions'][0]['body_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'Code hash'): oracle('esp32s3',data)

    def test_instruction_bytes(self):
        data=copy.deepcopy(FIXTURE['chips']['esp32s3'])
        data['functions'][0]['instructions'][0]=data['functions'][0]['instructions'][0].replace('004136','004137')
        with self.assertRaisesRegex(ValueError,'Instruction bytes'): oracle('esp32s3',data)

    def test_missing_reachable_instruction(self):
        data=copy.deepcopy(FIXTURE['chips']['esp32s3']);data['functions'][3]['instructions'].pop(4)
        with self.assertRaisesRegex(ValueError,'Unrecorded nonzero code'): oracle('esp32s3',data)

    def test_missing_literal(self):
        data=copy.deepcopy(FIXTURE['chips']['esp32s3']);data['literals']={}
        with self.assertRaisesRegex(ValueError,'Unrecorded literal'):
            oracle('esp32s3',data).run(default_case(1))

    def test_unknown_mmio(self):
        data=copy.deepcopy(FIXTURE['chips']['esp32s3']);data['literals']['0x4203aa40']='0x600060dc'
        with self.assertRaisesRegex(ValueError,'Unmapped read'):
            oracle('esp32s3',data).run(default_case(3))

    def test_constant_hash(self):
        data=copy.deepcopy(FIXTURE['chips']['esp32c3']);data['regions'][1]['data_hex']='00'*60
        with self.assertRaisesRegex(ValueError,'Region hash'): oracle('esp32c3',data)

    def test_jump_target_into_padding(self):
        data=copy.deepcopy(FIXTURE['chips']['esp32s3']);region=data['regions'][0]
        raw=bytearray.fromhex(region['data_hex']);raw[-4:]=(0x4203ac51).to_bytes(4,'little')
        region['data_hex']=raw.hex();region['sha256']=hashlib.sha256(raw).hexdigest()
        with self.assertRaisesRegex(ValueError,'Unknown branch target'): oracle('esp32s3',data)

    def test_unknown_callback_slot(self):
        data=copy.deepcopy(FIXTURE['chips']['esp32s3'])
        data['functions'][0]['instructions']=[line.replace('a8, a8, 68','a8, a8, 72')
                                               for line in data['functions'][0]['instructions']]
        with self.assertRaisesRegex(ValueError,'Unknown callback slot'):
            oracle('esp32s3',data).run(default_case(1))

    def test_unknown_memcpy_boundary(self):
        data=copy.deepcopy(FIXTURE['chips']['esp32s3']);data['symbols']['memcpy']['address']='0x40000000'
        with self.assertRaisesRegex(ValueError,'Unknown callback target'):
            oracle('esp32s3',data).run(default_case(4))

    def test_unknown_direct_stop_boundary(self):
        data=copy.deepcopy(FIXTURE['chips']['esp32c3']);data['symbols']['stop_tx_tone']['address']='0x40000000'
        with self.assertRaisesRegex(ValueError,'Unknown callback target'):
            oracle('esp32c3',data).run(default_case(2))

    def test_s3_force_has_no_selected_original(self):
        with self.assertRaisesRegex(ValueError,'Invalid case'):
            oracle('esp32s3').run(default_case(0))

    def test_invalid_header_and_mutation_bits(self):
        for c in ([0]*23,[0]*25):
            with self.assertRaisesRegex(ValueError,'Invalid case words'): oracle('esp32c3').run(c)
        for field in (5,6,11):
            c=default_case(1);c[field]=64
            with self.assertRaises(ValueError): oracle('esp32c3').run(c)


if __name__=='__main__':
    unittest.main()
