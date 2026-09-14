#!/usr/bin/env python3
"""Audit complete PHY feature member replacement, retaining all earlier source gates."""
import argparse
import json
from pathlib import Path
import re
import audit_phy_allocations as allocations
import audit_phy_i2c as i2c
import audit_phy_basic as basic
import audit_phy_lifecycle as lifecycle
import audit_phy_temperature as temperature

SELECTED={chip:{'phy_dig_reg_backup':'__opensensor_feature_dig','phy_freq_mem_backup':'__opensensor_feature_freq','phy_set_most_tpw':'__opensensor_feature_power','phy_11p_set':'__opensensor_feature_mode'} for chip in ['esp32c3','esp32s3']}
ALL_SOURCE_NAMES=set(SELECTED['esp32s3'].values())
IRAM={'phy_dig_reg_backup','phy_freq_mem_backup'}
RETAINED={'esp32c3':{'ram1_wifi_set_tx_gain':('phy_tx_gain.o','.text.ram1_wifi_set_tx_gain')},'esp32s3':{}}
ROM={'esp32c3':{'rom_phy_dig_reg_backup':0x40001c30,'rom_phy_freq_mem_backup':0x40001c20},'esp32s3':{'rom_phy_dig_reg_backup':0x40006408,'rom_phy_freq_mem_backup':0x400063d8}}


def check_feature(base,symbols,expected,*,tx_gain_source=False):
    if expected not in ('vendor','source'):raise ValueError('Expected feature vendor or source')
    if tx_gain_source and expected!='source':raise ValueError('Transmit gain transition requires complete feature source stage')
    chip=base['chip'];inputs=base['allocations']['libphy.a']['inputs'];selected=SELECTED[chip]
    member=[row for row in inputs if row['member']=='phy_feature.o']
    if expected=='source':
        if member:raise ValueError('PHY feature member phy_feature.o still has allocated inputs')
        if any(row['member']=='phy_feature.o' and row['reported_input_bytes'] for row in base.get('excluded_mergeable_string_inputs',[])):
            raise ValueError('PHY feature member still has excluded mergeable string input')
    allowed=set(selected.values()) if expected=='source' else set()
    for name in ALL_SOURCE_NAMES-allowed:
        if symbols.get(name) is not None:raise ValueError('Unexpected feature source symbol: '+name)
    for old,new in selected.items():
        if expected=='source':
            body=temperature.require_body(symbols,new)
            if not lifecycle.alias_matches(symbols.get(old),body,executable=True):raise ValueError('Incorrect feature source alias: '+old)
            if any(temperature.overlaps(row,body) for row in inputs):raise ValueError('feature source overlaps vendor input: '+new)
            if temperature.original_sections(inputs,old):raise ValueError('Original feature function input still allocated: '+old)
        else:
            body=temperature.require_body(symbols,old)
            rows=([row for row in member if row['section']=='.iram1'] if old in IRAM else temperature.original_sections(member,old))
            if not any(temperature.contains(row,body) for row in rows):raise ValueError('Original feature body lacks member ownership: '+old)
        if old in IRAM and not i2c.in_iram(body):raise ValueError('feature routine is outside IRAM: '+old)
    for name,address in ROM[chip].items():
        rom=symbols.get(name)
        if not (rom and rom.get('absolute') and int(rom['address'],0)==address):raise ValueError('Changed ROM backup binding: '+name)
    for name,(member_name,section) in RETAINED[chip].items():
        if tx_gain_source:
            new='__opensensor_tx_gain_wifi_set'
            body=temperature.require_body(symbols,new)
            if not lifecycle.alias_matches(symbols.get(name),body,executable=True):raise ValueError('Incorrect transmit gain helper alias: '+name)
            if any(temperature.overlaps(row,body) for row in inputs):raise ValueError('Transmit gain helper overlaps vendor input: '+name)
            if temperature.original_sections(inputs,name):raise ValueError('Original transmit gain helper input still allocated: '+name)
            continue
        body=temperature.require_body(symbols,name)
        if not any(row['member']==member_name and row['section']==section and temperature.contains(row,body) for row in inputs):
            raise ValueError('Retained feature helper lacks original ownership: '+name)
        if section=='.iram1' and not i2c.in_iram(body):raise ValueError('Retained feature helper is outside IRAM: '+name)


def audit(elf_path,map_path,label,expected,*,hw_freq_source=False,reg_source=False,tx_gain_source=False):
    from elftools.elf.elffile import ELFFile
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',label):raise ValueError('Label must be a simple artifact identifier')
    prior=basic.audit(elf_path,map_path,label,'source',feature_source=(expected=='source'),hw_freq_source=hw_freq_source,reg_source=reg_source)
    base=allocations.audit(elf_path,map_path,label,exclude_strings=True);chip=base['chip']
    names=set(SELECTED[chip])|ALL_SOURCE_NAMES|set(RETAINED[chip])|set(ROM[chip])
    if tx_gain_source and RETAINED[chip]:names.add('__opensensor_tx_gain_wifi_set')
    with elf_path.open('rb') as stream:symbols=temperature.inspect_symbols(ELFFile(stream),sorted(names))
    check_feature(base,symbols,expected,tx_gain_source=tx_gain_source)
    phy=base['allocations']['libphy.a']
    return {'schema':'phy-feature-allocation-audit-v1','chip':chip,'label':label,'expect_feature':expected,'checks_passed':True,
        'profile':'full-tracking-station','elf_sha256':base['elf_sha256'],'map_sha256':base['map_sha256'],
        'method':base['method'],'previous_source_gates':{**prior['previous_source_gates'],'basic':True},
        'non_string_allocations':{**prior['non_string_allocations'],'phy_feature_member_bytes':phy['members'].get('phy_feature.o',0)},
        'selected_symbols':{old:{'original_or_alias':symbols[old],'source_symbol':new,'source_body':symbols.get(new),'requires_iram':old in IRAM} for old,new in SELECTED[chip].items()},
        'retained_helpers':{name:symbols[name] for name in RETAINED[chip]},'tx_gain_source':tx_gain_source,'rom_backups':{name:symbols[name] for name in ROM[chip]},
        'allocated_phy_members':phy['members'],'allocated_phy_inputs':phy['inputs'],'input_archives_observed':base['input_archives_observed'],
        'limits':['This is linked-image ownership evidence, not an archive-wide replacement claim.',
                  'Source aliases may have stale sizes; actual source bodies are checked separately.',
                  'IRAM entry placement does not prove transitive flash independence or literal placement.',
                  'Instruction behavior, callback ABI and device behavior need separate validation.']}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--elf',type=Path,required=True);p.add_argument('--map',type=Path,required=True)
    p.add_argument('--label',required=True);p.add_argument('--expect-feature',choices=['vendor','source'],required=True)
    a=p.parse_args();print(json.dumps(audit(a.elf,a.map,a.label,a.expect_feature),indent=2))
if __name__=='__main__':main()
