import copy
import json
from pathlib import Path
import struct
import unittest
from iram_verify import Oracle,default_case,CONFIG

FIXTURE=json.loads(Path(__file__).with_name('iram-original-instructions.json').read_text())


def oracle(chip,data=None):return Oracle(chip,data if data is not None else FIXTURE['chips'][chip])


def run(chip,case):
    result,trace=oracle(chip).run(case)
    return result,[trace[i:i+9] for i in range(0,len(trace),9)]


def calls(ev):return [e for e in ev if e[0]==6]


class OriginalIramBehavior(unittest.TestCase):
    def test_hostid_exhausts_low_byte_and_ignores_upper_bits(self):
        for chip in FIXTURE['chips']:
            for block in range(256):
                c=default_case(0);c[1]=0xa5a50000|block
                result,ev=run(chip,c)
                self.assertEqual(result,int(block in (98,99,100,103,107)))
                self.assertEqual([e[0] for e in ev],[7,8])
                self.assertEqual(ev[-1][1:3],[CONFIG,(c[18]&0xfffe000f)|0x1fe00])

    def test_read_preserves_raw_result_and_pause_token(self):
        for chip in FIXTURE['chips']:
            c=default_case(1);c[6]=0x81234567;c[9]=0xfedc1234
            result,ev=run(chip,c)
            self.assertEqual(result,c[9]);self.assertEqual(calls(ev)[-1][3],c[6])
            self.assertEqual([e[0] for e in ev],[4,5,6,9,4,5,6,4,5,6,4,5,6,10,4,5,6])

    def test_read_argument_narrowing_and_ignored_host(self):
        for chip in FIXTURE['chips']:
            c=default_case(1);c[1]=0x80000167;c[3]=0xffff0104;c[8]=0xdeadbeef
            expected=run(chip,c);cb=calls(expected[1])
            self.assertEqual(cb[-2][3:7],
                             [0x67,c[7],c[8],4] if chip=='esp32s3' else [c[1],c[7],c[8],c[3]])
            for host in (0,1,255,256,0xffffffff):
                c[2]=host;self.assertEqual(run(chip,c),expected)

    def test_read_reloads_table_after_each_opaque_callback(self):
        for chip in FIXTURE['chips']:
            c=default_case(1);c[13:15]=[0xffffffff]*2
            _,ev=run(chip,c)
            self.assertEqual([e[1] for e in ev if e[0]==4],list(range(5)))
            self.assertEqual([e[2] for e in calls(ev)],list(range(5)))

    def test_write_command_raw_c3_and_narrow_s3(self):
        c=default_case(2);c[1:5]=[0x80000167,99,0x12345604,0xabcd0181]
        for chip in FIXTURE['chips']:
            _,ev=run(chip,c);command=[e[2] for e in ev if e[0]==8][0]
            self.assertEqual(command,0x05810467 if chip=='esp32s3' else
                             (c[1]|(c[3]<<8)|(c[4]<<16)|0x05000000)&0xffffffff)

    def test_write_uses_raw_wrapping_host_address(self):
        for chip in FIXTURE['chips']:
            for host in (0,1,18,0x80000000,0xffffffff):
                c=default_case(2);c[8]=host
                _,ev=run(chip,c);address=((0x18003800+host)<<2)&0xffffffff
                self.assertEqual({e[1] for e in ev if e[0] in (7,8)},{address})

    def test_write_busy_poll_rereads_until_clear_before_exit(self):
        for chip in FIXTURE['chips']:
            for busy in range(8):
                c=default_case(2);c[23]=busy;c[19]=0x80000001
                _,ev=run(chip,c);reads=[e for e in ev if e[0]==7]
                self.assertEqual(len(reads),busy+1)
                self.assertEqual([bool(e[2]&0x02000000) for e in reads],[True]*busy+[False])
                self.assertEqual(ev[ev.index(reads[-1])+1][0],10)
                self.assertEqual(calls(ev)[-1][3],c[6])

    def test_init_snapshot_arrays_and_read_order(self):
        s3_order=[0xc0,0xbd,0xc1,0xc2,0xbe,0xbf,0xc3,0xc4,0xc7,0xc8,
                  0xc9,0xc6,0xca,0xc5,0xcb,0xcc,0xcf,0xd0,0xce,0xcd]
        for chip in FIXTURE['chips']:
            c=default_case(3);c[15]=1
            _,ev=run(chip,c)
            self.assertEqual(ev[0][0],9)
            self.assertEqual([e[2] for e in ev if e[0]==1],s3_order if chip=='esp32s3' else list(range(0xbd,0xd1)))
            snapshots=[struct.pack('<III',*e[2:5])[:10] for e in ev if e[0]==12]
            self.assertEqual(snapshots[0],bytes([107]*10))
            self.assertEqual(snapshots[1],bytes([1,2,3,4,5,6,7,8,10,11]))
            self.assertEqual(snapshots[2],bytes(((i*37)^c[5])&255 for i in range(0xbd,0xc7)))
            self.assertEqual(snapshots[3],bytes([98,98,98,98,98,98,99,100,100,103]))
            self.assertEqual(snapshots[4],bytes([3,8,10,9,4,0,1,8,4,2]))
            self.assertEqual(snapshots[5],bytes(((i*37)^c[5])&255 for i in range(0xc7,0xd1)))
            bulk=[e for e in ev if e[0]==11][0]
            self.assertEqual(bulk[3:5],[10,0])

    def test_init_first_mmio_write_relative_to_bulk_slot_differs(self):
        for chip in FIXTURE['chips']:
            _,ev=run(chip,default_case(3));first=next(i for i,e in enumerate(ev) if e[0]==7)
            self.assertEqual([e[0] for e in ev[first:first+5]],
                             [7,4,5,8,11] if chip=='esp32c3' else [7,8,4,5,11])

    def test_init_rereads_after_bulk_mutation_and_preserves_final_table_order(self):
        for chip in FIXTURE['chips']:
            c=default_case(3);c[7]=0x1234;c[21]=2;c[20]=0x80000001
            _,ev=run(chip,c);reads=[e for e in ev if e[0]==7];writes=[e for e in ev if e[0]==8]
            self.assertEqual(writes[0][2],0xa5a4123a)
            self.assertEqual(reads[1][2],0x25a4123b)
            self.assertEqual(writes[1][2],0x25a5fe0b)
            at=ev.index(reads[1])
            self.assertEqual([e[0] for e in ev[at:at+5]],
                             [7,8,4,5,6] if chip=='esp32c3' else [7,4,8,5,6])

    def test_init_sar2_only_for_full_zero_mask_return(self):
        for chip in FIXTURE['chips']:
            for result in (0,1,256,0x80000000,0xffffffff):
                c=default_case(3);c[10]=result;_,ev=run(chip,c)
                sar=[e for e in ev if e[0]==13 or (e[0]==6 and e[1]==0x23c)]
                self.assertEqual(len(sar),int(result==0))
                if sar:self.assertEqual(sar[0][1] if chip=='esp32c3' else sar[0][3],1400)
                self.assertEqual(ev[-1][0],10)

    def test_wakeup_needs_two_full_register_sixteens(self):
        for chip in FIXTURE['chips']:
            for first,second in ((16,16),(0,16),(16,0),(0x10010,16),(16,0x80000010)):
                c=default_case(4);c[11:13]=[first,second];_,ev=run(chip,c)
                self.assertEqual(sum(e[0]==14 for e in ev),int(first==second==16))
                self.assertEqual([e[3:6] for e in calls(ev)],
                                 [[103,0 if chip=='esp32s3' else 1,4],[103,0 if chip=='esp32s3' else 1,6]])

    def test_c3_bias_full_nonzero_and_local_part(self):
        for value in (0,1,2,256,0x80000000,0xffffffff):
            c=default_case(5);c[1]=value;_,ev=run('esp32c3',c)
            self.assertEqual([e[3:7] for e in calls(ev)],
                             [[106,0,0,204],[106,0,1,124]] if value else [[106,0,0,119],[106,0,1,119]])
        _,part=run('esp32c3',default_case(6));c=default_case(5);c[1]=1
        self.assertEqual(part,run('esp32c3',c)[1])

    def test_txcap_rate_bands_and_low_byte_narrowing(self):
        for rate,first,second in ((0,1,0x32),(3,1,0x32),(4,4,0x65),(8,4,0x65),(9,7,0x98),
                                  (255,7,0x98),(256,1,0x32),(0xffff0004,4,0x65)):
            c=default_case(7);c[2]=rate;_,ev=run('esp32s3',c);cb=calls(ev)
            self.assertEqual(cb[0][3:],[107,0,1,3,0,first]);self.assertEqual(cb[1][6],second)

    def test_txcap_override_still_reads_original_input(self):
        c=default_case(7);c[24]=1;_,ev=run('esp32s3',c)
        self.assertEqual([e[2] for e in ev if e[0]==3],[0,3,6,1,4,7,2,5,8])
        self.assertEqual([e[2] for e in ev if e[0]==1 and e[2]>=0x2ce],list(range(0x2ce,0x2d7)))
        self.assertEqual(calls(ev)[0][-1],0x11)

    def test_txcap_keeps_full_first_byte_and_reads_current_saved_byte(self):
        c=default_case(7);c[28]=(c[28]&0xffffff00)|0x81;c[15]=1;c[17]=0x5a
        _,ev=run('esp32s3',c)
        self.assertEqual(calls(ev)[0][-1],0x81)
        self.assertEqual([e[2:4] for e in ev if e[0]==2],[[0xbd,0xd1],[0xbe,0x32]])

    def test_txcap_padding_restart(self):
        o=oracle('esp32s3');self.assertNotIn(0x4037b5ab,o.program)
        self.assertEqual(o.program[0x4037b5ac][1:3],('movi.n',['a8','0']))

    def test_critical_helpers_have_no_memory_or_callback_effects(self):
        for chip in FIXTURE['chips']:
            for operation,event in ((8,9),(9,10)):
                self.assertEqual(run(chip,default_case(operation)),(0,[[event]+[0]*8]))


class RejectUnsupportedIramEvidence(unittest.TestCase):
    def test_unknown_instruction(self):
        data=copy.deepcopy(FIXTURE['chips']['esp32c3'])
        data['functions'][0]['instructions'][0]=data['functions'][0]['instructions'][0].replace('addi','unknown')
        with self.assertRaisesRegex(ValueError,'Unsupported instruction'):oracle('esp32c3',data).run(default_case(0))

    def test_code_hash(self):
        data=copy.deepcopy(FIXTURE['chips']['esp32s3']);data['functions'][0]['body_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'Code hash'):oracle('esp32s3',data)

    def test_missing_nonzero_instruction(self):
        data=copy.deepcopy(FIXTURE['chips']['esp32s3']);data['functions'][5]['instructions'].pop(7)
        with self.assertRaisesRegex(ValueError,'Unrecorded nonzero code'):oracle('esp32s3',data)

    def test_missing_literal(self):
        data=copy.deepcopy(FIXTURE['chips']['esp32s3']);data['literals']={}
        with self.assertRaisesRegex(ValueError,'Unrecorded literal'):oracle('esp32s3',data).run(default_case(0))

    def test_unknown_mmio(self):
        data=copy.deepcopy(FIXTURE['chips']['esp32s3']);data['literals']['0x4037b498']='0x6000e04c'
        with self.assertRaisesRegex(ValueError,'Unmapped read'):oracle('esp32s3',data).run(default_case(0))

    def test_unknown_callback_slot(self):
        data=copy.deepcopy(FIXTURE['chips']['esp32s3'])
        data['functions'][1]['instructions']=[line.replace('0x160','0x170') for line in data['functions'][1]['instructions']]
        with self.assertRaisesRegex(ValueError,'Unknown callback slot'):oracle('esp32s3',data).run(default_case(1))

    def test_unknown_memset(self):
        data=copy.deepcopy(FIXTURE['chips']['esp32s3']);data['symbols']['memset']['address']='0x40000000'
        with self.assertRaisesRegex(ValueError,'Unknown callback target'):oracle('esp32s3',data).run(default_case(3))

    def test_unknown_sar2(self):
        data=copy.deepcopy(FIXTURE['chips']['esp32c3']);data['symbols']['rom_i2c_sar2_init_code']['address']='0x40000000'
        with self.assertRaisesRegex(ValueError,'Unknown callback target'):oracle('esp32c3',data).run(default_case(3))

    def test_unknown_wakeup_init_boundary(self):
        data=copy.deepcopy(FIXTURE['chips']['esp32s3']);data['symbols']['phy_i2c_init2']['address']='0x40000000'
        with self.assertRaisesRegex(ValueError,'Unknown callback target'):oracle('esp32s3',data).run(default_case(4))

    def test_stuck_busy_rejected_without_inventing_timeout_return(self):
        for chip in FIXTURE['chips']:
            c=default_case(2);c[23]=0xffffffff
            with self.assertRaisesRegex(ValueError,'Instruction budget exhausted'):oracle(chip).run(c)

    def test_invalid_chip_operation(self):
        for chip,operation in (('esp32c3',7),('esp32s3',5),('esp32s3',6)):
            with self.assertRaisesRegex(ValueError,'Invalid case'):oracle(chip).run(default_case(operation))

    def test_invalid_header(self):
        for c in ([0]*31,[0]*33):
            with self.assertRaisesRegex(ValueError,'Invalid case words'):oracle('esp32c3').run(c)
        c=default_case(0);c[31]=1
        with self.assertRaisesRegex(ValueError,'Invalid case'):oracle('esp32c3').run(c)


if __name__=='__main__':unittest.main()
