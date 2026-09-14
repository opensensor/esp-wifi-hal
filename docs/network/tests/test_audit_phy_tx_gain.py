import hashlib
import unittest
import audit_phy_tx_gain as track
from test_audit_phy_lifecycle import append_input
from test_audit_phy_temperature import symbol

def fixture(chip='esp32c3',expected='source'):
    base={'chip':chip,'allocations':{'libphy.a':{'inputs':[]}},'excluded_mergeable_string_inputs':[]};syms={}
    for i,(old,new) in enumerate(track.SELECTED[chip].items()):
        address=(0x40380000 if new in track.IRAM[chip] else 0x4200e000)+i*32;syms[old]=symbol(address);syms[new]=symbol(address) if expected=='source' else None
        if expected=='vendor':append_input(base,'phy_tx_gain.o','.iram1' if new in track.IRAM[chip] else '.text.'+old,address,32)
    return base,syms
class TransmitGainAudit(unittest.TestCase):
    def test_both_modes_and_chips(self):
        for chip in track.SELECTED:
            for mode in ['vendor','source']:track.check_tx_gain(*fixture(chip,mode),mode)
    def test_unknown_mode(self):
        with self.assertRaises(ValueError):track.check_tx_gain(*fixture(),'automatic')
    def test_every_member_input_rejected(self):
        for section in ['.iram1','.rodata','.data','COMMON','.text.other','.literal.get_power_db']:
            b,s=fixture();append_input(b,'phy_tx_gain.o',section)
            with self.assertRaisesRegex(ValueError,'still has allocated'):track.check_tx_gain(b,s,'source')
    def test_excluded_strings_rejected(self):
        b,s=fixture();b['excluded_mergeable_string_inputs']=[{'member':'phy_tx_gain.o','reported_input_bytes':1}]
        with self.assertRaisesRegex(ValueError,'excluded mergeable'):track.check_tx_gain(b,s,'source')
    def test_every_alias_checked(self):
        for chip in track.SELECTED:
            for old in track.SELECTED[chip]:
                b,s=fixture(chip);s[old]['address']=hex(int(s[old]['address'],0)^8)
                with self.assertRaisesRegex(ValueError,'Incorrect transmit gain source alias'):track.check_tx_gain(b,s,'source')
    def test_stale_alias_sizes_are_not_body_sizes(self):
        for chip in track.SELECTED:
            b,s=fixture(chip)
            for old in track.SELECTED[chip]:s[old].update(symbol_size_bytes=0xffffffff,absolute=True,allocated=False,executable=False,type='STT_NOTYPE')
            track.check_tx_gain(b,s,'source')
    def test_every_source_body_must_be_real_and_contained(self):
        for chip in track.SELECTED:
            for name in track.SELECTED[chip].values():
                for field,value in [('allocated',False),('body_contained',False),('symbol_size_bytes',0),('type','STT_OBJECT'),('executable',False)]:
                    b,s=fixture(chip);s[name][field]=value
                    with self.assertRaisesRegex(ValueError,'Missing allocated function'):track.check_tx_gain(b,s,'source')
    def test_partial_vendor_overlap_rejected(self):
        b,s=fixture();append_input(b,'other.o','.data',0x40380008)
        with self.assertRaisesRegex(ValueError,'overlaps vendor'):track.check_tx_gain(b,s,'source')
    def test_old_named_function_under_other_member_rejected(self):
        for name in track.SELECTED['esp32c3']:
            b,s=fixture();append_input(b,'other.o','.text.'+name)
            with self.assertRaisesRegex(ValueError,'Original transmit gain function'):track.check_tx_gain(b,s,'source')
    def test_vendor_needs_correct_member_and_section(self):
        for field,value in [('member','other.o'),('section','.text.wrong')]:
            b,s=fixture('esp32s3','vendor');b['allocations']['libphy.a']['inputs'][0][field]=value
            with self.assertRaisesRegex(ValueError,'lacks member ownership'):track.check_tx_gain(b,s,'vendor')
    def test_vendor_rejects_every_source_symbol(self):
        for chip in track.SELECTED:
            for name in track.ALL_SOURCE_NAMES:
                b,s=fixture(chip,'vendor');s[name]=symbol(0x42001000)
                with self.assertRaisesRegex(ValueError,'Unexpected transmit gain source'):track.check_tx_gain(b,s,'vendor')
    def test_missing_alias_and_missing_body_rejected(self):
        for chip in track.SELECTED:
            for old,new in track.SELECTED[chip].items():
                b,s=fixture(chip);s.pop(old)
                with self.assertRaisesRegex(ValueError,'Incorrect transmit gain source alias'):track.check_tx_gain(b,s,'source')
                b,s=fixture(chip);s.pop(new)
                with self.assertRaisesRegex(ValueError,'Missing allocated function'):track.check_tx_gain(b,s,'source')
    def test_vendor_requires_containing_member_input(self):
        b,s=fixture('esp32s3','vendor');b['allocations']['libphy.a']['inputs'][0]['size_bytes']=1
        with self.assertRaisesRegex(ValueError,'lacks member ownership'):track.check_tx_gain(b,s,'vendor')


    def test_iram_entries_must_stay_in_ram(self):
        for chip in track.SELECTED:
            for name in track.IRAM[chip]:
                for address in ['0x42001000','0x4036fff0','0x403dfff8']:
                    b,s=fixture(chip);s[name]['address']=address
                    with self.assertRaisesRegex(ValueError,'must reside in IRAM'):track.check_tx_gain(b,s,'source')
    def test_s3_only_entry_cannot_leak_into_c3(self):
        b,s=fixture('esp32c3');s['__opensensor_tx_gain_dig_check']=symbol(0x42001000)
        with self.assertRaisesRegex(ValueError,'Unexpected transmit gain source'):track.check_tx_gain(b,s,'source')

if __name__=='__main__':unittest.main()
