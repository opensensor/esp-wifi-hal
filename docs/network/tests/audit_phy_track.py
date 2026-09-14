#!/usr/bin/env python3
"""Audit complete PHY tracking member replacement after the analog-calibration stage."""
import argparse,hashlib,json,re
from pathlib import Path
import audit_phy_allocations as allocations
import audit_phy_analog as analog
import audit_phy_lifecycle as lifecycle
import audit_phy_temperature as temperature
SELECTED={'esp32c3': {'rom2_wait_hw_freq_busy': '__opensensor_track_wait', 'rom2_ulp_ext_code_set': '__opensensor_track_ulp_set', 'rom2_ulp_code_track': '__opensensor_track_ulp', 'ram2_rfpll_cap_track': '__opensensor_track_pll', 'rom1_txpwr_cal_track': '__opensensor_track_power', 'txpwr_offset': '__opensensor_track_offset', 'rfcal_track': '__opensensor_track_rfcal'}, 'esp32s3': {'wait_hw_freq_busy': '__opensensor_track_wait', 'ulp_ext_code_set': '__opensensor_track_ulp_set', 'ulp_code_track': '__opensensor_track_ulp', 'rfpll_cap_track': '__opensensor_track_pll', 'ram_txpwr_cal_track': '__opensensor_track_power', 'txpwr_offset': '__opensensor_track_offset', 'ram_wifi_track_tx_power': '__opensensor_track_wifi', 'ram_bt_track_tx_power': '__opensensor_track_bt'}}
ALL_SOURCE_NAMES=set().union(*(set(v.values()) for v in SELECTED.values()))

def check_track(base,symbols,expected):
    if expected not in ('vendor','source'):raise ValueError('Expected tracking vendor or source')
    chip=base['chip'];inputs=base['allocations']['libphy.a']['inputs'];selected=SELECTED[chip]
    member=[r for r in inputs if r['member']=='phy_track.o']
    if expected=='source':
        if member:raise ValueError('PHY tracking member phy_track.o still has allocated inputs')
        if any(r['member']=='phy_track.o' and r['reported_input_bytes'] for r in base.get('excluded_mergeable_string_inputs',[])):
            raise ValueError('PHY tracking member still has excluded mergeable string input')
    for name in ALL_SOURCE_NAMES-(set(selected.values()) if expected=='source' else set()):
        if symbols.get(name) is not None:raise ValueError('Unexpected tracking source symbol: '+name)
    for old,new in selected.items():
        if expected=='source':
            body=temperature.require_body(symbols,new)
            if not lifecycle.alias_matches(symbols.get(old),body,executable=True):raise ValueError('Incorrect tracking source alias: '+old)
            if any(temperature.overlaps(r,body) for r in inputs):raise ValueError('Tracking source overlaps vendor input: '+new)
            if temperature.original_sections(inputs,old):raise ValueError('Original tracking function input still allocated: '+old)
        else:
            body=temperature.require_body(symbols,old)
            if not any(temperature.contains(r,body) for r in temperature.original_sections(member,old)):
                raise ValueError('Original tracking body lacks member ownership: '+old)


def audit(elf_path,map_path,label,expected,*,hw_freq_source=False,reg_source=False):
    from elftools.elf.elffile import ELFFile
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',label):raise ValueError('Label must be a simple artifact identifier')
    prior=analog.audit(elf_path,map_path,label,'source',hw_freq_source=hw_freq_source,reg_source=reg_source)
    base=allocations.audit(elf_path,map_path,label,exclude_strings=True);chip=base['chip']
    with elf_path.open('rb') as stream:symbols=temperature.inspect_symbols(ELFFile(stream),sorted(set().union(*(set(v) for v in SELECTED.values()))|ALL_SOURCE_NAMES))
    check_track(base,symbols,expected);phy=base['allocations']['libphy.a']
    return {'schema':'phy-track-allocation-audit-v1','chip':chip,'label':label,'expect_track':expected,'checks_passed':True,
        'profile':'full-tracking-station','elf_sha256':base['elf_sha256'],'map_sha256':base['map_sha256'],'method':base['method'],
        'previous_source_gates':{**prior['previous_source_gates'],'analog':True},
        'non_string_allocations':{**prior['non_string_allocations'],'phy_track_member_bytes':phy['members'].get('phy_track.o',0)},
        'selected_symbols':{old:{'original_or_alias':symbols[old],'source_symbol':new,'source_body':symbols.get(new)} for old,new in SELECTED[chip].items()},
        'allocated_phy_members':phy['members'],'allocated_phy_inputs':phy['inputs'],'input_archives_observed':base['input_archives_observed'],
        'retained_feature_rom_backups':prior['retained_feature_rom_backups'],
        'limits':['Linked-image ownership does not establish archive-wide or ROM replacement.',
                  'Source alias sizes can be stale; real source bodies are checked separately.',
                  'Native ABI, callback semantics, instruction behavior and device behavior need separate validation.']}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--elf',type=Path,required=True);p.add_argument('--map',type=Path,required=True)
    p.add_argument('--label',required=True);p.add_argument('--expect-track',choices=['vendor','source'],required=True)
    a=p.parse_args();print(json.dumps(audit(a.elf,a.map,a.label,a.expect_track),indent=2))
if __name__=='__main__':main()
