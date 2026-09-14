#!/usr/bin/env python3
"""Audit complete PHY basic member replacement, retaining all earlier source gates."""
import argparse
import json
from pathlib import Path
import re
import audit_phy_allocations as allocations
import audit_phy_i2c as i2c
import audit_phy_api as api
import audit_phy_lifecycle as lifecycle
import audit_phy_temperature as temperature

SELECTED={
    'esp32c3':{'rom1_i2c_master_reset':'__opensensor_basic_reset','chan14_mic_cfg':'__opensensor_basic_channel14'},
    'esp32s3':{'ram_i2c_master_reset':'__opensensor_basic_reset','chan14_mic_cfg':'__opensensor_basic_channel14','ram_set_chan_cal_interp':'__opensensor_basic_interpolate'},
}
ALL_SOURCE_NAMES=set(SELECTED['esp32s3'].values())
IRAM={'rom1_i2c_master_reset','ram_i2c_master_reset'}
RETAINED={chip:{'phy_set_most_tpw':('phy_feature.o','.text.phy_set_most_tpw')} for chip in SELECTED}
ROM={'esp32c3':0x40001bec,'esp32s3':0x4000633c}


def check_basic(base,symbols,expected,feature_source=False):
    if expected not in ('vendor','source'):raise ValueError('Expected basic vendor or source')
    if feature_source and expected!='source':raise ValueError('Feature source requires basic source')
    chip=base['chip'];inputs=base['allocations']['libphy.a']['inputs'];selected=SELECTED[chip]
    member=[row for row in inputs if row['member']=='phy_basic.o']
    if expected=='source':
        if member:raise ValueError('PHY basic member phy_basic.o still has allocated inputs')
        if any(row['member']=='phy_basic.o' and row['reported_input_bytes'] for row in base.get('excluded_mergeable_string_inputs',[])):
            raise ValueError('PHY basic member still has excluded mergeable string input')
    allowed=set(selected.values()) if expected=='source' else set()
    for name in ALL_SOURCE_NAMES-allowed:
        if symbols.get(name) is not None:raise ValueError('Unexpected basic source symbol: '+name)
    for old,new in selected.items():
        if expected=='source':
            body=temperature.require_body(symbols,new)
            if not lifecycle.alias_matches(symbols.get(old),body,executable=True):raise ValueError('Incorrect basic source alias: '+old)
            if any(temperature.overlaps(row,body) for row in inputs):raise ValueError('basic source overlaps vendor input: '+new)
            if temperature.original_sections(inputs,old):raise ValueError('Original basic function input still allocated: '+old)
        else:
            body=temperature.require_body(symbols,old)
            rows=([row for row in member if row['section']=='.iram1'] if old in IRAM else temperature.original_sections(member,old))
            if not any(temperature.contains(row,body) for row in rows):raise ValueError('Original basic body lacks member ownership: '+old)
        if old in IRAM and not i2c.in_iram(body):raise ValueError('basic routine is outside IRAM: '+old)
    rom=symbols.get('rom_set_chan_reg')
    if not (rom and rom.get('absolute') and int(rom['address'],0)==ROM[chip]):raise ValueError('Changed ROM channel binding')
    for name,(member_name,section) in RETAINED[chip].items():
        if feature_source and name=='phy_set_most_tpw':
            body=temperature.require_body(symbols,'__opensensor_feature_power')
            if not lifecycle.alias_matches(symbols.get(name),body,executable=True):raise ValueError('Incorrect feature power alias')
            if any(temperature.overlaps(row,body) for row in inputs):raise ValueError('Feature power overlaps vendor input')
            if temperature.original_sections(inputs,name):raise ValueError('Original feature power still allocated')
            continue
        body=temperature.require_body(symbols,name)
        if not any(row['member']==member_name and row['section']==section and temperature.contains(row,body) for row in inputs):
            raise ValueError('Retained basic helper lacks original ownership: '+name)
        if section=='.iram1' and not i2c.in_iram(body):raise ValueError('Retained basic helper is outside IRAM: '+name)


def audit(elf_path,map_path,label,expected,feature_source=False,*,hw_freq_source=False,reg_source=False):
    from elftools.elf.elffile import ELFFile
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',label):raise ValueError('Label must be a simple artifact identifier')
    prior=api.audit(elf_path,map_path,label,'source',feature_source=feature_source,hw_freq_source=hw_freq_source,reg_source=reg_source)
    base=allocations.audit(elf_path,map_path,label,exclude_strings=True);chip=base['chip']
    names=set(SELECTED[chip])|ALL_SOURCE_NAMES|set(RETAINED[chip])|{'rom_set_chan_reg'}
    if feature_source:names.add('__opensensor_feature_power')
    with elf_path.open('rb') as stream:symbols=temperature.inspect_symbols(ELFFile(stream),sorted(names))
    check_basic(base,symbols,expected,feature_source)
    phy=base['allocations']['libphy.a']
    return {'schema':'phy-basic-allocation-audit-v1','chip':chip,'label':label,'expect_basic':expected,'checks_passed':True,
        'profile':'full-tracking-station','elf_sha256':base['elf_sha256'],'map_sha256':base['map_sha256'],
        'method':base['method'],'previous_source_gates':{**prior['previous_source_gates'],'api':True},
        'non_string_allocations':{**prior['non_string_allocations'],'phy_basic_member_bytes':phy['members'].get('phy_basic.o',0)},
        'selected_symbols':{old:{'original_or_alias':symbols[old],'source_symbol':new,'source_body':symbols.get(new),'requires_iram':old in IRAM} for old,new in SELECTED[chip].items()},
        'retained_helpers':{name:symbols[name] for name in RETAINED[chip]},'rom_channel':symbols['rom_set_chan_reg'],
        'allocated_phy_members':phy['members'],'allocated_phy_inputs':phy['inputs'],'input_archives_observed':base['input_archives_observed'],
        'limits':['This is linked-image ownership evidence, not an archive-wide replacement claim.',
                  'Source aliases may have stale sizes; actual source bodies are checked separately.',
                  'IRAM entry placement does not prove transitive flash independence or literal placement.',
                  'Instruction behavior, callback ABI and device behavior need separate validation.']}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--elf',type=Path,required=True);p.add_argument('--map',type=Path,required=True)
    p.add_argument('--label',required=True);p.add_argument('--expect-basic',choices=['vendor','source'],required=True)
    a=p.parse_args();print(json.dumps(audit(a.elf,a.map,a.label,a.expect_basic),indent=2))
if __name__=='__main__':main()
