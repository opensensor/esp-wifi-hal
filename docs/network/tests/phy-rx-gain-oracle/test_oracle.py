import copy,hashlib,json,unittest
from pathlib import Path
import verify as v
E=json.loads(Path(__file__).with_name('original-instructions.json').read_text())
def rows(t):return [t[i:i+16] for i in range(0,len(t),16)]
class ReceiveGainOracle(unittest.TestCase):
    def run_case(self,chip,op,**axes):
        c=v.default_case(op)
        for i,value in axes.items():c[int(i)]=value&v.MASK
        return v.Oracle(chip,E[chip]).run(c)
    def test_body_hash(self):
        for chip in E:
            e=copy.deepcopy(E[chip]);e['functions'][0]['code_hex']='00'+e['functions'][0]['code_hex'][2:]
            with self.assertRaisesRegex(ValueError,'Code hash'):v.Oracle(chip,e)
    def test_instruction_bytes(self):
        e=copy.deepcopy(E['esp32s3']);e['functions'][0]['instructions'][0]=e['functions'][0]['instructions'][0].replace('00c136','00c137')
        with self.assertRaisesRegex(ValueError,'bytes differ'):v.Oracle('esp32s3',e)
    def test_duplicate_instruction(self):
        e=copy.deepcopy(E['esp32c3']);e['functions'][0]['instructions'].append(e['functions'][0]['instructions'][0])
        with self.assertRaisesRegex(ValueError,'Overlapping'):v.Oracle('esp32c3',e)
    def test_unknown_opcode(self):
        e=copy.deepcopy(E['esp32c3']);e['functions'][0]['instructions'][0]=e['functions'][0]['instructions'][0].replace('addi','invented')
        with self.assertRaisesRegex(ValueError,'Unsupported'):v.Oracle('esp32c3',e)
    def test_missing_literal(self):
        e=copy.deepcopy(E['esp32s3']);e['literals']={}
        with self.assertRaisesRegex(ValueError,'Unknown literal'):v.Oracle('esp32s3',e).run(v.default_case(0))
    def test_wrong_parameter_extent(self):
        e=copy.deepcopy(E['esp32s3']);e['symbols']['phy_param']['size_bytes']=848
        with self.assertRaisesRegex(ValueError,'extent'):v.Oracle('esp32s3',e)
    def test_readonly_bytes_and_size(self):
        for chip in E:
            for change in ('bytes','size_bytes'):
                e=copy.deepcopy(E[chip]);row=e['readonly'][0]
                if change=='bytes':row['bytes']='ff'+row['bytes'][2:]
                else:row['size_bytes']+=1
                with self.assertRaisesRegex(ValueError,'Readonly hash'):v.Oracle(chip,e)
    def test_case_domain(self):
        for c in ([5]+[0]*31,[0]*31,[0]*31+[1<<32]):
            with self.assertRaises(ValueError):v.Oracle('esp32c3',E['esp32c3']).run(c)
    def test_unknown_rom_call(self):
        e=copy.deepcopy(E['esp32c3']);e['symbols']['rom_phy_reg_init']['address']='0x40000002'
        with self.assertRaisesRegex(ValueError,'Unknown call'):v.Oracle('esp32c3',e).run(v.default_case(4))
    def test_original_initialization_counts_and_order(self):
        for chip,n,count in [('esp32c3',79,79),('esp32s3',82,76)]:
            r=rows(self.run_case(chip,4)[1]);self.assertEqual([x[:4] for x in r[:2]],[[2,0x2001f6,1,n],[2,0x2001f5,1,count]])
            writes=[x for x in r if x[0]==6 and x[1]&4095==44]
            self.assertEqual([x[2:5] for x in writes],[[0x10080,0x40200000,i] for i in range(n)])
            self.assertEqual(r[-1][1]&4095,4)
            if chip=='esp32c3':self.assertEqual(r[-4][:2],[10,3])
            else:self.assertEqual(r[-4][1]&4095,0x248)
    def test_callback_table_generation_reloaded(self):
        for chip in E:
            r=rows(self.run_case(chip,4,**{'13':v.MASK})[1]);calls=[x for x in r if x[0]==6]
            self.assertEqual([x[1]>>12 for x in calls],list(range(0x71000,0x71000+len(calls))) if chip=='esp32s3' else list(range(0x71000,0x71000+len(calls)-1))+[0x71000+len(calls)])
    def test_captured_write_slot_survives_read_callback(self):
        for chip in E:
            r=rows(self.run_case(chip,2,**{'13':v.MASK})[1]);slot=0x1a8 if chip=='esp32s3' else 0x1cc
            i=next(i for i,x in enumerate(r) if x[0]==5 and x[1]==slot)
            self.assertEqual([x[0] for x in r[i:i+4]],[5,5,6,6]);self.assertEqual((r[i+3][1]-0x71000000)//4096,r[i][2])
    def test_calibration_chip_argument_counts(self):
        for chip in E:
            r=rows(self.run_case(chip,2,**{'1':0})[1]);dc=next(x for x in r if x[:2]==[10,1]);self.assertEqual(dc[2:6],[0,0,3,0x310000]);self.assertEqual(dc[10:12],[4,14] if chip=='esp32s3' else [0,0])
    def test_generator_index_limit(self):
        for chip in E:self.assertEqual(self.run_case(chip,0,**{'21':1,'6':255,'2':255})[0],85)
    def test_generator_logging_records_stack_arguments(self):
        for chip in E:
            r=rows(self.run_case(chip,0,**{'7':1})[1]);logs=[x for x in r if x[0]==11];self.assertGreater(len(logs),1);self.assertEqual(logs[0][7],9);self.assertEqual(logs[-1][1],1)
    def test_packed_read_widths(self):
        for chip in E:
            r=rows(self.run_case(chip,1)[1]);reads=[x for x in r if x[0]==1 and 0x300000<=x[1]<0x300200];self.assertTrue(reads);self.assertEqual({x[2] for x in reads},{2 if chip=='esp32s3' else 4})
    def test_s3_mode_narrows_c3_does_not(self):
        self.assertEqual(self.run_case('esp32s3',2,**{'1':256}),self.run_case('esp32s3',2,**{'1':0}))
        self.assertNotEqual(self.run_case('esp32c3',2,**{'1':256}),self.run_case('esp32c3',2,**{'1':0}))
    def test_opaque_children_keep_calibration_dependencies(self):
        for chip in E:
            normal=rows(self.run_case(chip,3)[1]);opaque=rows(self.run_case(chip,3,**{'20':0})[1]);self.assertGreater(len(normal),len(opaque));self.assertEqual([x[1] for x in opaque if x[0]==9],[0,0,2,2,1,1]);self.assertTrue(any(x[:2]==[10,1] for x in normal))
    def test_register_read_churn_changes_effects(self):
        for chip in E:self.assertNotEqual(self.run_case(chip,3,**{'17':512})[1],self.run_case(chip,3,**{'17':512,'11':v.MASK})[1])
if __name__=='__main__':unittest.main()
