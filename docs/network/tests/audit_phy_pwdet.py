#!/usr/bin/env python3
"""Audit complete PHY pwdet member replacement after the debug stage."""
import argparse,json,re
from pathlib import Path
import audit_phy_allocations as allocations
import audit_phy_debug as debug
import audit_phy_lifecycle as lifecycle
import audit_phy_temperature as temperature
SELECTED={'esp32c3': {'phy_set_pwdet_power': '__opensensor_pwdet_power', 'get_sar_sig_ref': '__opensensor_pwdet_reference', 'pwdet_tone_start': '__opensensor_pwdet_tone', 'get_tone_sar_dout': '__opensensor_pwdet_samples', 'get_fm_sar_dout': '__opensensor_pwdet_fm', 'txtone_linear_pwr': '__opensensor_pwdet_linear', 'get_power_db': '__opensensor_pwdet_db', 'ram_pkdet_vol_start': '__opensensor_pwdet_pkdet', 'rom1_read_sar2_code': '__opensensor_pwdet_read'}, 'esp32s3': {'phy_set_pwdet_power': '__opensensor_pwdet_power', 'get_sar_sig_ref': '__opensensor_pwdet_reference', 'pwdet_tone_start': '__opensensor_pwdet_tone', 'get_tone_sar_dout': '__opensensor_pwdet_samples', 'get_fm_sar_dout': '__opensensor_pwdet_fm', 'txtone_linear_pwr': '__opensensor_pwdet_linear', 'get_power_db': '__opensensor_pwdet_db', 'ram_read_sar2_code': '__opensensor_pwdet_read'}}
ALL_SOURCE_NAMES=set().union(*(set(v.values()) for v in SELECTED.values()))

def check_pwdet(base,symbols,expected):
    if expected not in ('vendor','source'):raise ValueError('Expected pwdet vendor or source')
    chip=base['chip'];inputs=base['allocations']['libphy.a']['inputs'];selected=SELECTED[chip]
    member=[r for r in inputs if r['member']=='phy_pwdet.o']
    if expected=='source':
        if member:raise ValueError('PHY pwdet member phy_pwdet.o still has allocated inputs')
        if any(r['member']=='phy_pwdet.o' and r['reported_input_bytes'] for r in base.get('excluded_mergeable_string_inputs',[])):
            raise ValueError('PHY pwdet member still has excluded mergeable string input')
    for name in ALL_SOURCE_NAMES-(set(selected.values()) if expected=='source' else set()):
        if symbols.get(name) is not None:raise ValueError('Unexpected pwdet source symbol: '+name)
    for old,new in selected.items():
        if expected=='source':
            body=temperature.require_body(symbols,new)
            if not lifecycle.alias_matches(symbols.get(old),body,executable=True):raise ValueError('Incorrect pwdet source alias: '+old)
            if any(temperature.overlaps(r,body) for r in inputs):raise ValueError('Pwdet source overlaps vendor input: '+new)
            if temperature.original_sections(inputs,old):raise ValueError('Original pwdet function input still allocated: '+old)
        else:
            body=temperature.require_body(symbols,old)
            if not any(temperature.contains(r,body) for r in temperature.original_sections(member,old)):
                raise ValueError('Original pwdet body lacks member ownership: '+old)

def audit(elf_path,map_path,label,expected,*,hw_freq_source=False):
    from elftools.elf.elffile import ELFFile
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',label):raise ValueError('Label must be a simple artifact identifier')
    prior=debug.audit(elf_path,map_path,label,'source',hw_freq_source=hw_freq_source)
    base=allocations.audit(elf_path,map_path,label,exclude_strings=True);chip=base['chip']
    with elf_path.open('rb') as stream:symbols=temperature.inspect_symbols(ELFFile(stream),sorted(set(SELECTED[chip])|ALL_SOURCE_NAMES))
    check_pwdet(base,symbols,expected);phy=base['allocations']['libphy.a']
    return {'schema':'phy-pwdet-allocation-audit-v1','chip':chip,'label':label,'expect_pwdet':expected,'checks_passed':True,
        'profile':'full-tracking-station','elf_sha256':base['elf_sha256'],'map_sha256':base['map_sha256'],'method':base['method'],
        'previous_source_gates':{**prior['previous_source_gates'],'debug':True},
        'non_string_allocations':{**prior['non_string_allocations'],'phy_pwdet_member_bytes':phy['members'].get('phy_pwdet.o',0)},
        'selected_symbols':{old:{'original_or_alias':symbols[old],'source_symbol':new,'source_body':symbols.get(new)} for old,new in SELECTED[chip].items()},
        'allocated_phy_members':phy['members'],'allocated_phy_inputs':phy['inputs'],'input_archives_observed':base['input_archives_observed'],
        'retained_feature_rom_backups':prior['retained_feature_rom_backups'],
        'limits':['Linked-image ownership does not establish archive-wide or ROM replacement.',
                  'Source alias sizes can be stale; real source bodies are checked separately.',
                  'Native ABI, callback semantics, instruction behavior and device behavior need separate validation.']}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--elf',type=Path,required=True);p.add_argument('--map',type=Path,required=True)
    p.add_argument('--label',required=True);p.add_argument('--expect-pwdet',choices=['vendor','source'],required=True)
    a=p.parse_args();print(json.dumps(audit(a.elf,a.map,a.label,a.expect_pwdet),indent=2))
if __name__=='__main__':main()
