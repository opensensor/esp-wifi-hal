import copy,json,unittest
from pathlib import Path
import verify as v
DATA=json.loads(Path(__file__).with_name('original-instructions.json').read_text())

def events(trace):return [trace[i:i+8] for i in range(0,len(trace),8)]
class PowerDetectorOracle(unittest.TestCase):
    def run_case(self,chip,op,**changes):
        c=v.default_case(op)
        for index,value in changes.items():c[int(index)]=value
        return v.Oracle(chip,DATA[chip]).run(c)
    def test_all_selected_bodies_and_nested_modes(self):
        for chip,e in DATA.items():
            o=v.Oracle(chip,e)
            for op in o.entries:
                for mode in (0,31):
                    c=v.default_case(op);c[8]=mode;self.assertEqual(o.run(c)[0],0)
    def test_reference_narrows_before_unsigned_comparison(self):
        for chip in DATA:
            result=self.run_case(chip,1,**{'1':0xffffffd7 if chip=='esp32c3' else 0xffffffcd,'2':1,'3':65535})
            self.assertEqual([e[2] for e in events(result[2]) if e[0]==2],[65534,65534])
    def test_parameter_overlap_reads_both_before_writing(self):
        for chip in DATA:
            _,_,trace=self.run_case(chip,1,**{'1':2000,'11':14})
            rows=events(trace);self.assertEqual([e[0] for e in rows],[1,1,2,2])
            self.assertEqual([e[2] for e in rows],[1000,3000,1040 if chip=='esp32c3' else 1050,2000])
    def test_shared_output_preserves_store_order(self):
        for chip in DATA:
            _,_,trace=self.run_case(chip,1,**{'1':2000,'11':0})
            writes=[e for e in events(trace) if e[0]==2]
            self.assertEqual([e[1] for e in writes],[0x300000,0x300000]);self.assertEqual(writes[-1][2],2000)
    def test_tone_mmio_and_delay_order(self):
        for chip in DATA:
            _,_,trace=self.run_case(chip,2)
            self.assertEqual([(e[0],e[1]) for e in events(trace)],[(7,0x60006040),(8,0x60006040),(11,1),(7,0x6000e050),(8,0x6000e050),(7,0x6000e050),(8,0x6000e050),(11,2),(7,0x6000e050),(7,0x60006040),(8,0x60006040)])
    def test_pkdet_has_separate_cleanup_writes(self):
        _,_,trace=self.run_case('esp32c3',3)
        writes=[e for e in events(trace) if e[0]==8 and e[1]==0x6000e05c]
        self.assertEqual(len(writes),4)
        self.assertTrue(writes[0][2]&(1<<21));self.assertTrue(writes[1][2]&(1<<19))
        self.assertEqual(writes[2][2]&(1<<21),0);self.assertEqual(writes[3][2]&(1<<19),0)
    def test_stalled_poll_keeps_prefix_without_cleanup(self):
        for chip in DATA:
            status,result,trace=self.run_case(chip,2,**{'13':0})
            self.assertEqual((status,result,len(trace)//8),(2,0,96))
            self.assertEqual(len([e for e in events(trace) if e[0]==8 and e[1]==0x60006040]),1)
    def test_delayed_poll_completes(self):
        for chip in DATA:
            self.assertEqual(self.run_case(chip,2,**{'13':0x70000000})[0],0)
    def test_buffer_callback_writes_eight_halfwords(self):
        for chip in DATA:
            status,result,trace=self.run_case(chip,4,**{'4':0xdead1234,'8':0})
            self.assertEqual((status,result),(0,0x1234))
            self.assertEqual([e[1] for e in events(trace) if e[0]==10],list(range(0,16,2)))
    def test_callback_table_reloaded_after_setup(self):
        for chip in DATA:
            _,_,trace=self.run_case(chip,4,**{'8':0,'9':1})
            self.assertEqual([e[1] for e in events(trace) if e[0]==4],[0,1])
    def test_c3_setup_can_execute_nested_pkdet(self):
        opaque=self.run_case('esp32c3',4,**{'8':0})
        nested=self.run_case('esp32c3',4,**{'8':16})
        self.assertEqual(opaque[:2],nested[:2]);self.assertEqual(len(nested[2])-len(opaque[2]),15*8)
    def test_zero_count_keeps_chip_specific_result(self):
        self.assertEqual(self.run_case('esp32c3',5,**{'1':0})[:2],(0,65535))
        self.assertEqual(self.run_case('esp32s3',5,**{'1':0})[:2],(1,0))
    def test_wide_count_c3_wraps_s3_narrows(self):
        status,_,trace=self.run_case('esp32c3',5,**{'1':256,'8':0})
        self.assertEqual(status,2);self.assertGreater(sum(e[:2]==[9,2] for e in events(trace)),255)
        self.assertEqual(self.run_case('esp32s3',5,**{'1':256,'8':0})[:2],(1,0))
        self.assertEqual(self.run_case('esp32s3',5,**{'1':257,'8':0})[:2],(0,2000))
    def test_full_count_average(self):
        for chip in DATA:self.assertEqual(self.run_case(chip,5,**{'1':255,'8':0})[:2],(0,2889))
    def test_linear_signed_narrowing_and_zero_denominator(self):
        for chip in DATA:
            for denominator,expected in [(0,0xfffff800),(1,0xfffff800),(65535,2048)]:
                self.assertEqual(self.run_case(chip,7,**{'8':0,'14':32767,'15':denominator})[:2],(0,expected))
    def test_db_preserves_raw_returns_and_signed_arguments(self):
        for chip in DATA:
            status,result,trace=self.run_case(chip,8,**{'1':0x80000000,'6':0xffffffff,'7':0x7fffffff,'8':0,'14':65535,'15':32768,'9':1})
            self.assertEqual((status,result),(0,0))
            self.assertEqual([e[2:4] for e in events(trace) if e[0]==6],[[0xffffffff,3],[0xffff8000,3]])
    def test_fm_returns_zero_and_composes_sampling(self):
        for chip in DATA:
            status,result,trace=self.run_case(chip,6)
            self.assertEqual((status,result),(0,0));self.assertEqual(sum(e[0]==10 for e in events(trace)),16)
    def test_invalid_domain_rejected(self):
        for chip in DATA:
            for index,value in [(0,9),(2,65536),(3,65536),(8,32),(11,16),(14,65536),(15,65536)]:
                c=v.default_case(1);c[index]=value
                with self.assertRaisesRegex(ValueError,'Invalid case domain'):v.Oracle(chip,DATA[chip]).run(c)
    def test_corrupt_instruction_bytes_rejected(self):
        for chip,e in DATA.items():
            bad=copy.deepcopy(e);f=bad['functions'][1];f['code_hex']='ff'+f['code_hex'][2:]
            with self.assertRaisesRegex(ValueError,'Code hash differs'):v.Oracle(chip,bad)
    def test_unknown_instruction_and_literal_rejected(self):
        for chip,e in DATA.items():
            bad=copy.deepcopy(e);line=bad['functions'][1]['instructions'][0].split();line[2]='unsupported';bad['functions'][1]['instructions'][0]=' '.join(line)
            with self.assertRaisesRegex(ValueError,'Unsupported instruction'):v.Oracle(chip,bad)
        bad=copy.deepcopy(DATA['esp32s3']);bad['literals'][next(iter(bad['literals']))]='0xdeadbeef'
        with self.assertRaisesRegex(ValueError,'Unknown literal'):v.Oracle('esp32s3',bad)
    def test_unmapped_memory_operand_rejected(self):
        bad=copy.deepcopy(DATA['esp32c3']);f=bad['functions'][1]
        f['instructions']=[s.replace('218(a5)','222(a5)') for s in f['instructions']]
        with self.assertRaisesRegex(ValueError,'Unmapped read'):v.Oracle('esp32c3',bad).run(v.default_case(1))
if __name__=='__main__':unittest.main()
