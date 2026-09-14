#!/usr/bin/env python3
"""Audit complete PHY API member replacement, retaining all earlier source gates."""
import argparse
import json
from pathlib import Path
import re
import audit_phy_allocations as allocations
import audit_phy_i2c as i2c
import audit_phy_lifecycle as lifecycle
import audit_phy_temperature as temperature

COMMON={
    'phy_wakeup_init':'__opensensor_api_wakeup',
    'phy_close_rf':'__opensensor_api_close',
    'phy_get_rf_cal_version':'__opensensor_api_calibration_version',
}
SELECTED={'esp32c3':COMMON,'esp32s3':{**COMMON,'phy_set_tx_seed':'__opensensor_api_tx_seed'}}
ALL_SOURCE_NAMES=set(SELECTED['esp32s3'].values())
IRAM={'phy_wakeup_init','phy_close_rf'}
RETAINED={
    'esp32c3':{'ram1_phy_wakeup_init':('phy_init.o','.iram1'),
               'ram1_phy_close_rf':('phy_init.o','.iram1'),
               'get_rf_freq_init':('phy_hw_freq.o','.text.get_rf_freq_init')},
    'esp32s3':{'ram_phy_wakeup_init':('phy_init.o','.iram1'),
               'ram_phy_close_rf':('phy_init.o','.iram1'),
               'get_rf_freq_init':('phy_hw_freq.o','.text.get_rf_freq_init')},
}

def check_api(base,symbols,expected,*,hw_freq_source=False):
    if expected not in ('vendor','source'):raise ValueError('Expected API vendor or source')
    if hw_freq_source and expected!='source':raise ValueError('Hardware frequency source requires API source')
    chip=base['chip'];inputs=base['allocations']['libphy.a']['inputs'];selected=SELECTED[chip]
    member=[row for row in inputs if row['member']=='phy_api.o']
    if expected=='source':
        if member:raise ValueError('PHY API member phy_api.o still has allocated inputs')
        if any(row['member']=='phy_api.o' and row['reported_input_bytes'] for row in base.get('excluded_mergeable_string_inputs',[])):
            raise ValueError('PHY API member still has excluded mergeable string input')
    allowed=set(selected.values()) if expected=='source' else set()
    for name in ALL_SOURCE_NAMES-allowed:
        if symbols.get(name) is not None:raise ValueError('Unexpected API source symbol: '+name)
    for old,new in selected.items():
        if expected=='source':
            body=temperature.require_body(symbols,new)
            if not lifecycle.alias_matches(symbols.get(old),body,executable=True):raise ValueError('Incorrect API source alias: '+old)
            if any(temperature.overlaps(row,body) for row in inputs):raise ValueError('API source overlaps vendor input: '+new)
            if temperature.original_sections(inputs,old):raise ValueError('Original API function input still allocated: '+old)
        else:
            body=temperature.require_body(symbols,old)
            rows=([row for row in member if row['section']=='.iram1'] if old in IRAM else temperature.original_sections(member,old))
            if not any(temperature.contains(row,body) for row in rows):raise ValueError('Original API body lacks member ownership: '+old)
        if old in IRAM and not i2c.in_iram(body):raise ValueError('API routine is outside IRAM: '+old)
    for name,(member_name,section) in RETAINED[chip].items():
        if name=='get_rf_freq_init' and hw_freq_source:
            body=temperature.require_body(symbols,'__opensensor_hw_freq_initialize')
            if not lifecycle.alias_matches(symbols.get(name),body,executable=True):raise ValueError('Incorrect hardware frequency API helper alias')
            if any(temperature.overlaps(row,body) for row in inputs):raise ValueError('Hardware frequency API helper overlaps vendor input')
            if temperature.original_sections(inputs,name):raise ValueError('Original hardware frequency API helper still allocated')
            continue
        body=temperature.require_body(symbols,name)
        if not any(row['member']==member_name and row['section']==section and temperature.contains(row,body) for row in inputs):
            raise ValueError('Retained API helper lacks original ownership: '+name)
        if section=='.iram1' and not i2c.in_iram(body):raise ValueError('Retained API helper is outside IRAM: '+name)


def audit(elf_path,map_path,label,expected,*,feature_source=False,hw_freq_source=False):
    from elftools.elf.elffile import ELFFile
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',label):raise ValueError('Label must be a simple artifact identifier')
    prior=i2c.audit(elf_path,map_path,label,'source',api_source=expected=='source',feature_source=feature_source)
    base=allocations.audit(elf_path,map_path,label,exclude_strings=True);chip=base['chip']
    names=set(SELECTED[chip])|ALL_SOURCE_NAMES|set(RETAINED[chip])|{'__opensensor_hw_freq_initialize'}
    with elf_path.open('rb') as stream:symbols=temperature.inspect_symbols(ELFFile(stream),sorted(names))
    check_api(base,symbols,expected,hw_freq_source=hw_freq_source)
    phy=base['allocations']['libphy.a']
    return {'schema':'phy-api-allocation-audit-v1','chip':chip,'label':label,'expect_api':expected,'checks_passed':True,
        'profile':'full-tracking-station','elf_sha256':base['elf_sha256'],'map_sha256':base['map_sha256'],
        'method':base['method'],'previous_source_gates':{**prior['previous_source_gates'],'i2c':True},
        'non_string_allocations':{**prior['non_string_allocations'],'phy_api_member_bytes':phy['members'].get('phy_api.o',0)},
        'selected_symbols':{old:{'original_or_alias':symbols[old],'source_symbol':new,'source_body':symbols.get(new),'requires_iram':old in IRAM} for old,new in SELECTED[chip].items()},
        'retained_helpers':{name:symbols[name] for name in RETAINED[chip]},
        'allocated_phy_members':phy['members'],'allocated_phy_inputs':phy['inputs'],'input_archives_observed':base['input_archives_observed'],
        'limits':['This is linked-image ownership evidence, not an archive-wide replacement claim.',
                  'Source aliases may have stale sizes; actual source bodies are checked separately.',
                  'IRAM entry placement does not prove transitive flash independence or literal placement.',
                  'Instruction behavior, callback ABI and device behavior need separate validation.']}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--elf',type=Path,required=True);p.add_argument('--map',type=Path,required=True)
    p.add_argument('--label',required=True);p.add_argument('--expect-api',choices=['vendor','source'],required=True)
    a=p.parse_args();print(json.dumps(audit(a.elf,a.map,a.label,a.expect_api),indent=2))
if __name__=='__main__':main()
