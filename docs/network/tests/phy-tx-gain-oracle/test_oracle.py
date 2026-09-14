import copy
import json
from pathlib import Path
import unittest
import verify as v

FIXTURE=json.loads(Path(__file__).with_name('original-instructions.json').read_text())

def events(trace,kind=None):
    rows=[trace[i:i+16] for i in range(0,len(trace),16)]
    return rows if kind is None else [r for r in rows if r[0]==kind]

class TransmitGainOracle(unittest.TestCase):
    def run_case(self,chip,kind,**changes):
        c=v.default_case(kind)
        for index,value in changes.items():c[int(index)]=value
        return v.Oracle(chip,FIXTURE[chip]).run(c)
    def test_every_pinned_instruction_decodes(self):
        for chip,count in [('esp32c3',642),('esp32s3',712)]:
            self.assertEqual(len(v.Oracle(chip,FIXTURE[chip]).program),count)
    def test_code_bytes_and_hashes_checked(self):
        e=copy.deepcopy(FIXTURE['esp32c3']);e['functions'][0]['code_hex']='00'+e['functions'][0]['code_hex'][2:]
        with self.assertRaisesRegex(ValueError,'Code hash'):v.Oracle('esp32c3',e)
    def test_instruction_encoding_must_match_body(self):
        e=copy.deepcopy(FIXTURE['esp32s3']);f=e['functions'][0];line=f['instructions'][0];parts=line.split();parts[1]='000000';f['instructions'][0]=' '.join(parts)
        with self.assertRaisesRegex(ValueError,'Instruction bytes'):v.Oracle('esp32s3',e)
    def test_unknown_instruction_rejected(self):
        e=copy.deepcopy(FIXTURE['esp32c3']);f=e['functions'][0];f['instructions'][0]=f['instructions'][0].replace('lui','invented',1)
        with self.assertRaisesRegex(ValueError,'Unsupported instruction'):v.Oracle('esp32c3',e)
    def test_readonly_corruption_rejected(self):
        for chip in FIXTURE:
            e=copy.deepcopy(FIXTURE[chip]);e['readonly'][0]['bytes']='00'+e['readonly'][0]['bytes'][2:]
            with self.assertRaisesRegex(ValueError,'Readonly hash'):v.Oracle(chip,e)
    def test_log_formats_checked(self):
        e=copy.deepcopy(FIXTURE['esp32s3']);e['logs'][0]['format']='changed'
        with self.assertRaisesRegex(ValueError,'Log format'):v.Oracle('esp32s3',e)
    def test_parameter_extent_checked(self):
        e=copy.deepcopy(FIXTURE['esp32c3']);e['symbols']['phy_param']['size_bytes']=740
        with self.assertRaisesRegex(ValueError,'Parameter extent'):v.Oracle('esp32c3',e)
    def test_unknown_function_rejected(self):
        with self.assertRaisesRegex(ValueError,'Unknown function'):self.run_case('esp32c3',99)
    def test_case_size_checked(self):
        with self.assertRaisesRegex(ValueError,'Invalid case'):v.Oracle('esp32s3',FIXTURE['esp32s3']).run([0]*32)
    def test_interpolation_return_signedness_and_read_order(self):
        for chip,result,addresses in [('esp32c3',0xffffff80,[0x300001,0x300000]),('esp32s3',128,[0x300000,0x300001])]:
            actual,trace=self.run_case(chip,1,**{'1':12,'38':0xff0080})
            self.assertEqual(actual,result);self.assertEqual([r[1] for r in events(trace,1)],addresses)
    def test_disabled_setter_preserves_chip_specific_eager_reads(self):
        for chip in FIXTURE:
            _,trace=self.run_case(chip,7,**{'17':1})
            reads=events(trace,1)
            expected=[0x200099] if chip=='esp32s3' else [0x2001fb,0x20009a,*range(0x2000f4,0x200102),0x200099]
            self.assertEqual([r[1] for r in reads],expected)
            self.assertFalse(events(trace,6));self.assertFalse(events(trace,9))
    def test_s3_lookup_keeps_both_difference_writes(self):
        _,trace=self.run_case('esp32s3',4,**{'2':1})
        writes=[r for r in events(trace,2) if r[1]==0x310020]
        self.assertEqual(len(writes),2);self.assertTrue(all(r[2]==2 for r in writes))
    def test_s3_digital_correction_width_asymmetry(self):
        _,trace=self.run_case('esp32s3',11,**{'1':0x1234,'2':0x2018})
        self.assertEqual([(r[1],r[2]) for r in events(trace,1)],[(0x300000,2),(0x310000,1)])
        self.assertEqual([(r[1],r[2]) for r in events(trace,2)],[(0x300000,2),(0x310000,2)])
    def test_s3_table_is_reloaded_between_setter_calls(self):
        _,trace=self.run_case('esp32s3',8,**{'13':v.MASK,'39':0})
        self.assertEqual([r[1] for r in events(trace,4)],[0,1,2])
        self.assertEqual([r[1] for r in events(trace,5)],[0x218,0x210,0x214])
        self.assertEqual(events(trace)[0][0],4)
    def test_c3_wifi_callback_is_per_entry(self):
        _,trace=self.run_case('esp32c3',6,**{'13':v.MASK})
        self.assertEqual(len(events(trace,4)),14)
        self.assertTrue(all(r[1]==0x110 for r in events(trace,5)))
    def test_c3_calibration_reference_alias_is_observed(self):
        _,trace=self.run_case('esp32c3',10)
        refs=[r[3] for r in events(trace,1) if r[1]==0x20004e]
        self.assertEqual(len(refs),18)
        self.assertEqual(refs[:5],[32]*5);self.assertEqual(refs[5:],[0]*13)
    def test_s3_digital_gain_executes_existing_source_helper(self):
        _,trace=self.run_case('esp32s3',0)
        self.assertEqual([r[1] for r in events(trace,9)],[12])
        self.assertEqual([r[1] for r in events(trace,8)],v.MMIO)
    def test_logging_keeps_stack_arguments(self):
        for chip in FIXTURE:
            _,trace=self.run_case(chip,6,**{'4':1})
            rows=events(trace,11);self.assertEqual(len(rows),14)
            self.assertTrue(all(r[1]==1 for r in rows));self.assertEqual([r[2] for r in rows],list(range(14)))
    def test_nonfinite_or_out_of_extent_case_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'Uninitialized read|Instruction budget'):
            self.run_case('esp32c3',4,**{'1':0x80000000,'2':256})

if __name__=='__main__':unittest.main()
