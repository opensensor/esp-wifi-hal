#!/usr/bin/env python3
"""Audit complete PHY RF PLL member replacement after the analog-calibration stage."""
import argparse,hashlib,json,re
from pathlib import Path
import audit_phy_allocations as allocations
import audit_phy_track as tracking
import audit_phy_lifecycle as lifecycle
import audit_phy_temperature as temperature
SELECTED={'esp32c3': {'restart_cal': '__opensensor_rfpll_restart', 'write_rfpll_sdm': '__opensensor_rfpll_sdm', 'wait_rfpll_cal_end': '__opensensor_rfpll_wait', 'rfpll_set_freq': '__opensensor_rfpll_frequency', 'correct_rfpll_offset': '__opensensor_rfpll_correct_offset', 'rom2_write_pll_cap': '__opensensor_rfpll_write_cap', 'rom2_read_pll_cap': '__opensensor_rfpll_read_cap', 'ram2_rfpll_cap_correct': '__opensensor_rfpll_correct_cap', 'rfpll_cap_init_cal': '__opensensor_rfpll_init_cap', 'set_rfpll_freq': '__opensensor_rfpll_set', 'set_rf_freq_offset': '__opensensor_rfpll_set_offset', 'set_channel_rfpll_freq': '__opensensor_rfpll_set_channel', 'chip_v7_set_chan_misc': '__opensensor_rfpll_misc', 'chip_v7_set_chan': '__opensensor_rfpll_channel', 'chip_v7_set_chan_offset': '__opensensor_rfpll_channel_offset', 'chip_v7_set_chan_ana': '__opensensor_rfpll_channel_analog'}, 'esp32s3': {'restart_cal': '__opensensor_rfpll_restart', 'write_rfpll_sdm': '__opensensor_rfpll_sdm', 'wait_rfpll_cal_end': '__opensensor_rfpll_wait', 'rfpll_set_freq': '__opensensor_rfpll_frequency', 'correct_rfpll_offset': '__opensensor_rfpll_correct_offset', 'ram_write_pll_cap': '__opensensor_rfpll_write_cap', 'read_pll_cap': '__opensensor_rfpll_read_cap', 'rfpll_cap_correct': '__opensensor_rfpll_correct_cap', 'rfpll_cap_init_cal': '__opensensor_rfpll_init_cap', 'set_rfpll_freq': '__opensensor_rfpll_set', 'set_rf_freq_offset': '__opensensor_rfpll_set_offset', 'set_channel_rfpll_freq': '__opensensor_rfpll_set_channel', 'chip_v7_set_chan_misc': '__opensensor_rfpll_misc', 'chip_v7_set_chan': '__opensensor_rfpll_channel', 'chip_v7_set_chan_offset': '__opensensor_rfpll_channel_offset', 'chip_v7_set_chan_ana': '__opensensor_rfpll_channel_analog', 'phy_set_freq': '__opensensor_rfpll_phy_frequency', 'ram_pll_vol_cal': '__opensensor_rfpll_voltage'}}
ALL_SOURCE_NAMES=set().union(*(set(v.values()) for v in SELECTED.values()))

def check_rfpll(base,symbols,expected):
    if expected not in ('vendor','source'):raise ValueError('Expected RF PLL vendor or source')
    chip=base['chip'];inputs=base['allocations']['libphy.a']['inputs'];selected=SELECTED[chip]
    member=[r for r in inputs if r['member']=='phy_rfpll.o']
    if expected=='source':
        if member:raise ValueError('PHY RF PLL member phy_rfpll.o still has allocated inputs')
        if any(r['member']=='phy_rfpll.o' and r['reported_input_bytes'] for r in base.get('excluded_mergeable_string_inputs',[])):
            raise ValueError('PHY RF PLL member still has excluded mergeable string input')
    for name in ALL_SOURCE_NAMES-(set(selected.values()) if expected=='source' else set()):
        if symbols.get(name) is not None:raise ValueError('Unexpected RF PLL source symbol: '+name)
    for old,new in selected.items():
        if expected=='source':
            body=temperature.require_body(symbols,new)
            if not lifecycle.alias_matches(symbols.get(old),body,executable=True):raise ValueError('Incorrect RF PLL source alias: '+old)
            if any(temperature.overlaps(r,body) for r in inputs):raise ValueError('RF PLL source overlaps vendor input: '+new)
            if temperature.original_sections(inputs,old):raise ValueError('Original RF PLL function input still allocated: '+old)
        else:
            body=temperature.require_body(symbols,old)
            if not any(temperature.contains(r,body) for r in temperature.original_sections(member,old)):
                raise ValueError('Original RF PLL body lacks member ownership: '+old)


def audit(elf_path,map_path,label,expected,*,hw_freq_source=False,reg_source=False):
    from elftools.elf.elffile import ELFFile
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',label):raise ValueError('Label must be a simple artifact identifier')
    prior=tracking.audit(elf_path,map_path,label,'source',hw_freq_source=hw_freq_source,reg_source=reg_source)
    base=allocations.audit(elf_path,map_path,label,exclude_strings=True);chip=base['chip']
    with elf_path.open('rb') as stream:symbols=temperature.inspect_symbols(ELFFile(stream),sorted(set().union(*(set(v) for v in SELECTED.values()))|ALL_SOURCE_NAMES))
    check_rfpll(base,symbols,expected);phy=base['allocations']['libphy.a']
    return {'schema':'phy-rfpll-allocation-audit-v1','chip':chip,'label':label,'expect_rfpll':expected,'checks_passed':True,
        'profile':'full-rfpll-station','elf_sha256':base['elf_sha256'],'map_sha256':base['map_sha256'],'method':base['method'],
        'previous_source_gates':{**prior['previous_source_gates'],'tracking':True},
        'non_string_allocations':{**prior['non_string_allocations'],'phy_rfpll_member_bytes':phy['members'].get('phy_rfpll.o',0)},
        'selected_symbols':{old:{'original_or_alias':symbols[old],'source_symbol':new,'source_body':symbols.get(new)} for old,new in SELECTED[chip].items()},
        'allocated_phy_members':phy['members'],'allocated_phy_inputs':phy['inputs'],'input_archives_observed':base['input_archives_observed'],
        'retained_feature_rom_backups':prior['retained_feature_rom_backups'],
        'limits':['Linked-image ownership does not establish archive-wide or ROM replacement.',
                  'Source alias sizes can be stale; real source bodies are checked separately.',
                  'Native ABI, callback semantics, instruction behavior and device behavior need separate validation.']}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--elf',type=Path,required=True);p.add_argument('--map',type=Path,required=True)
    p.add_argument('--label',required=True);p.add_argument('--expect-rfpll',choices=['vendor','source'],required=True)
    a=p.parse_args();print(json.dumps(audit(a.elf,a.map,a.label,a.expect_rfpll),indent=2))
if __name__=='__main__':main()
