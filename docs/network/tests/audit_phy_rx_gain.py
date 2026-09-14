#!/usr/bin/env python3
"""Audit complete PHY receive gain member replacement after RF PLL replacement."""
import argparse,hashlib,json,re
from pathlib import Path
import audit_phy_allocations as allocations
import audit_phy_reg as previous
import audit_phy_lifecycle as lifecycle
import audit_phy_temperature as temperature
SELECTED={'esp32c3': {'gen_rx_gain_table': '__opensensor_rx_gain_generate', 'wr_rx_gain_mem': '__opensensor_rx_gain_write_memory', 'set_rx_gain_param': '__opensensor_rx_gain_set_param', 'set_rx_gain_table': '__opensensor_rx_gain_set_table', 'phy_rx_table_init': '__opensensor_rx_gain_initialize'}, 'esp32s3': {'gen_rx_gain_table': '__opensensor_rx_gain_generate', 'wr_rx_gain_mem': '__opensensor_rx_gain_write_memory', 'set_rx_gain_param': '__opensensor_rx_gain_set_param', 'set_rx_gain_table': '__opensensor_rx_gain_set_table', 'phy_rx_table_init': '__opensensor_rx_gain_initialize'}}
ALL_SOURCE_NAMES=set().union(*(set(v.values()) for v in SELECTED.values()))

IRAM=set()

def check_rx_gain(base,symbols,expected):
    if expected not in ('vendor','source'):raise ValueError('Expected receive gain vendor or source')
    chip=base['chip'];inputs=base['allocations']['libphy.a']['inputs'];selected=SELECTED[chip]
    member=[r for r in inputs if r['member']=='phy_rx_gain.o']
    if expected=='source':
        if member:raise ValueError('PHY receive gain member phy_rx_gain.o still has allocated inputs')
        if any(r['member']=='phy_rx_gain.o' and r['reported_input_bytes'] for r in base.get('excluded_mergeable_string_inputs',[])):
            raise ValueError('PHY receive gain member still has excluded mergeable string input')
    for name in ALL_SOURCE_NAMES-(set(selected.values()) if expected=='source' else set()):
        if symbols.get(name) is not None:raise ValueError('Unexpected receive gain source symbol: '+name)
    for old,new in selected.items():
        if expected=='source':
            body=temperature.require_body(symbols,new)
            if new in IRAM:
                start=int(body['address'],0)
                if not (0x40300000<=start and start+body['symbol_size_bytes']<=0x40400000):raise ValueError('Receive gain helper must reside in IRAM: '+new)
            if not lifecycle.alias_matches(symbols.get(old),body,executable=True):raise ValueError('Incorrect receive gain source alias: '+old)
            if any(temperature.overlaps(r,body) for r in inputs):raise ValueError('receive gain source overlaps vendor input: '+new)
            if temperature.original_sections(inputs,old):raise ValueError('Original receive gain function input still allocated: '+old)
        else:
            body=temperature.require_body(symbols,old)
            if not any(temperature.contains(r,body) for r in ([r for r in member if r['section']=='.iram1'] if new in IRAM else temperature.original_sections(member,old))):
                raise ValueError('Original receive gain body lacks member ownership: '+old)


def audit(elf_path,map_path,label,expected,*,tx_gain_source=False,init_source=False):
    from elftools.elf.elffile import ELFFile
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',label):raise ValueError('Label must be a simple artifact identifier')
    prior=previous.audit(elf_path,map_path,label,'source',tx_gain_source=tx_gain_source,init_source=init_source)
    base=allocations.audit(elf_path,map_path,label,exclude_strings=True);chip=base['chip']
    with elf_path.open('rb') as stream:symbols=temperature.inspect_symbols(ELFFile(stream),sorted(set().union(*(set(v) for v in SELECTED.values()))|ALL_SOURCE_NAMES))
    check_rx_gain(base,symbols,expected);phy=base['allocations']['libphy.a']
    return {'schema':'phy-rx-gain-allocation-audit-v1','chip':chip,'label':label,'expect_rx_gain':expected,'checks_passed':True,
        'profile':'full-rx-gain-station','elf_sha256':base['elf_sha256'],'map_sha256':base['map_sha256'],'method':base['method'],
        'previous_source_gates':{**prior['previous_source_gates'],'reg':True},
        'non_string_allocations':{**prior['non_string_allocations'],'phy_rx_gain_member_bytes':phy['members'].get('phy_rx_gain.o',0)},
        'selected_symbols':{old:{'original_or_alias':symbols[old],'source_symbol':new,'source_body':symbols.get(new)} for old,new in SELECTED[chip].items()},
        'allocated_phy_members':phy['members'],'allocated_phy_inputs':phy['inputs'],'input_archives_observed':base['input_archives_observed'],
        'retained_feature_rom_backups':prior['retained_feature_rom_backups'],
        'limits':['Linked-image ownership does not establish archive-wide or ROM replacement.',
                  'Source alias sizes can be stale; real source bodies are checked separately.',
                  'Native ABI, callback semantics, instruction behavior and device behavior need separate validation.']}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--elf',type=Path,required=True);p.add_argument('--map',type=Path,required=True)
    p.add_argument('--label',required=True);p.add_argument('--expect-rx-gain',choices=['vendor','source'],required=True)
    a=p.parse_args();print(json.dumps(audit(a.elf,a.map,a.label,a.expect_rx_gain),indent=2))
if __name__=='__main__':main()
