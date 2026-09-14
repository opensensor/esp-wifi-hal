#!/usr/bin/env python3
"""Audit complete PHY debug member replacement after the feature stage."""
import argparse,json,re
from pathlib import Path
import audit_phy_allocations as allocations
import audit_phy_feature as feature
import audit_phy_lifecycle as lifecycle
import audit_phy_temperature as temperature
SELECTED={chip:{'get_iq_value':'__opensensor_debug_iq','get_bias_ref_code':'__opensensor_debug_bias','phy_get_vdd33':'__opensensor_debug_voltage'} for chip in ['esp32c3','esp32s3']}
ALL_SOURCE_NAMES=set(SELECTED['esp32c3'].values())

def check_debug(base,symbols,expected):
    if expected not in ('vendor','source'):raise ValueError('Expected debug vendor or source')
    chip=base['chip'];inputs=base['allocations']['libphy.a']['inputs'];selected=SELECTED[chip]
    member=[r for r in inputs if r['member']=='phy_debug.o']
    if expected=='source':
        if member:raise ValueError('PHY debug member phy_debug.o still has allocated inputs')
        if any(r['member']=='phy_debug.o' and r['reported_input_bytes'] for r in base.get('excluded_mergeable_string_inputs',[])):
            raise ValueError('PHY debug member still has excluded mergeable string input')
    for name in ALL_SOURCE_NAMES-(set(selected.values()) if expected=='source' else set()):
        if symbols.get(name) is not None:raise ValueError('Unexpected debug source symbol: '+name)
    for old,new in selected.items():
        if expected=='source':
            body=temperature.require_body(symbols,new)
            if not lifecycle.alias_matches(symbols.get(old),body,executable=True):raise ValueError('Incorrect debug source alias: '+old)
            if any(temperature.overlaps(r,body) for r in inputs):raise ValueError('Debug source overlaps vendor input: '+new)
            if temperature.original_sections(inputs,old):raise ValueError('Original debug function input still allocated: '+old)
        else:
            body=temperature.require_body(symbols,old)
            if not any(temperature.contains(r,body) for r in temperature.original_sections(member,old)):
                raise ValueError('Original debug body lacks member ownership: '+old)

def audit(elf_path,map_path,label,expected,*,hw_freq_source=False,reg_source=False):
    from elftools.elf.elffile import ELFFile
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',label):raise ValueError('Label must be a simple artifact identifier')
    prior=feature.audit(elf_path,map_path,label,'source',hw_freq_source=hw_freq_source,reg_source=reg_source)
    base=allocations.audit(elf_path,map_path,label,exclude_strings=True);chip=base['chip']
    with elf_path.open('rb') as stream:symbols=temperature.inspect_symbols(ELFFile(stream),sorted(set(SELECTED[chip])|ALL_SOURCE_NAMES))
    check_debug(base,symbols,expected);phy=base['allocations']['libphy.a']
    return {'schema':'phy-debug-allocation-audit-v1','chip':chip,'label':label,'expect_debug':expected,'checks_passed':True,
        'profile':'full-tracking-station','elf_sha256':base['elf_sha256'],'map_sha256':base['map_sha256'],'method':base['method'],
        'previous_source_gates':{**prior['previous_source_gates'],'feature':True},
        'non_string_allocations':{**prior['non_string_allocations'],'phy_debug_member_bytes':phy['members'].get('phy_debug.o',0)},
        'selected_symbols':{old:{'original_or_alias':symbols[old],'source_symbol':new,'source_body':symbols.get(new)} for old,new in SELECTED[chip].items()},
        'allocated_phy_members':phy['members'],'allocated_phy_inputs':phy['inputs'],'input_archives_observed':base['input_archives_observed'],
        'retained_feature_rom_backups':prior['rom_backups'],
        'limits':['Linked-image ownership does not establish archive-wide or ROM replacement.',
                  'Source alias sizes can be stale; real source bodies are checked separately.',
                  'Native ABI, callback semantics, instruction behavior and device behavior need separate validation.']}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--elf',type=Path,required=True);p.add_argument('--map',type=Path,required=True)
    p.add_argument('--label',required=True);p.add_argument('--expect-debug',choices=['vendor','source'],required=True)
    a=p.parse_args();print(json.dumps(audit(a.elf,a.map,a.label,a.expect_debug),indent=2))
if __name__=='__main__':main()
