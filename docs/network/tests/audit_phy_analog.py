#!/usr/bin/env python3
"""Audit complete PHY analog member replacement after the power-detector stage."""
import argparse,hashlib,json,re
from pathlib import Path
import audit_phy_allocations as allocations
import audit_phy_pwdet as pwdet
import audit_phy_lifecycle as lifecycle
import audit_phy_temperature as temperature
SELECTED={chip:{'get_rc_dout':'__opensensor_analog_measurement','rc_cal':'__opensensor_analog_calibrate'} for chip in ['esp32c3','esp32s3']}
DATA={'wifi_ht20':('__opensensor_analog_ht20',155),'wifi_ht40':('__opensensor_analog_ht40',355)}
ALL_SOURCE_NAMES=set().union(*(set(v.values()) for v in SELECTED.values()))

def check_analog(base,symbols,expected):
    if expected not in ('vendor','source'):raise ValueError('Expected analog vendor or source')
    chip=base['chip'];inputs=base['allocations']['libphy.a']['inputs'];selected=SELECTED[chip]
    member=[r for r in inputs if r['member']=='phy_analog_cal.o']
    if expected=='source':
        if member:raise ValueError('PHY analog member phy_analog_cal.o still has allocated inputs')
        if any(r['member']=='phy_analog_cal.o' and r['reported_input_bytes'] for r in base.get('excluded_mergeable_string_inputs',[])):
            raise ValueError('PHY analog member still has excluded mergeable string input')
    for name in ALL_SOURCE_NAMES-(set(selected.values()) if expected=='source' else set()):
        if symbols.get(name) is not None:raise ValueError('Unexpected analog source symbol: '+name)
    for old,new in selected.items():
        if expected=='source':
            body=temperature.require_body(symbols,new)
            if not lifecycle.alias_matches(symbols.get(old),body,executable=True):raise ValueError('Incorrect analog source alias: '+old)
            if any(temperature.overlaps(r,body) for r in inputs):raise ValueError('Analog source overlaps vendor input: '+new)
            if temperature.original_sections(inputs,old):raise ValueError('Original analog function input still allocated: '+old)
        else:
            body=temperature.require_body(symbols,old)
            if not any(temperature.contains(r,body) for r in temperature.original_sections(member,old)):
                raise ValueError('Original analog body lacks member ownership: '+old)

    for old,(new,initial) in DATA.items():
        if chip=='esp32s3':
            if symbols.get(old) is not None or symbols.get(new) is not None:raise ValueError('Unexpected analog divisor on S3')
            continue
        name=new if expected=='source' else old
        body=symbols.get(name)
        digest=hashlib.sha256(initial.to_bytes(2,'little')).hexdigest()
        if not (body and body['type']=='STT_OBJECT' and body['allocated'] and body['body_contained'] and body['symbol_size_bytes']==2 and not body['executable'] and body.get('writable') and int(body['address'],0)%2==0 and body['body_sha256']==digest):
            raise ValueError('Invalid writable analog divisor: '+name)
        if expected=='source':
            if not lifecycle.alias_matches(symbols.get(old),body,executable=False):raise ValueError('Incorrect analog data alias: '+old)
            if any(temperature.overlaps(r,body) for r in inputs):raise ValueError('Analog data overlaps vendor input')
            if any(r['section'] in ('.data.'+old,'.sdata.'+old) for r in inputs):raise ValueError('Original analog data input still allocated')
        else:
            if symbols.get(new) is not None:raise ValueError('Unexpected analog source data')
            if not any(r['section']=='.data.'+old and temperature.contains(r,body) for r in member):raise ValueError('Original analog data lacks member ownership')
    if chip=='esp32c3':
        a,b=[symbols[DATA[n][0] if expected=='source' else n] for n in DATA]
        if temperature.overlaps({'address':a['address'],'size_bytes':2},b):raise ValueError('Analog divisor objects overlap')

def inspect(elf):
    names=set(SELECTED['esp32c3'])|ALL_SOURCE_NAMES|set(DATA)|{v[0] for v in DATA.values()}
    symbols=temperature.inspect_symbols(elf,sorted(names));table=elf.get_section_by_name('.symtab')
    for name,body in symbols.items():
        if body is None:continue
        matches=[s for s in table.get_symbol_by_name(name) if s['st_shndx']!='SHN_UNDEF']
        section=elf.get_section(matches[0]['st_shndx']) if matches and isinstance(matches[0]['st_shndx'],int) else None
        body['writable']=bool(section and section['sh_flags']&1)
    return symbols

def audit(elf_path,map_path,label,expected,*,hw_freq_source=False,reg_source=False,tx_gain_source=False,init_source=False):
    from elftools.elf.elffile import ELFFile
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',label):raise ValueError('Label must be a simple artifact identifier')
    prior=pwdet.audit(elf_path,map_path,label,'source',hw_freq_source=hw_freq_source,reg_source=reg_source,tx_gain_source=tx_gain_source,init_source=init_source)
    base=allocations.audit(elf_path,map_path,label,exclude_strings=True);chip=base['chip']
    with elf_path.open('rb') as stream:symbols=inspect(ELFFile(stream))
    check_analog(base,symbols,expected);phy=base['allocations']['libphy.a']
    return {'schema':'phy-analog-allocation-audit-v1','chip':chip,'label':label,'expect_analog':expected,'checks_passed':True,
        'profile':'full-tracking-station','elf_sha256':base['elf_sha256'],'map_sha256':base['map_sha256'],'method':base['method'],
        'previous_source_gates':{**prior['previous_source_gates'],'pwdet':True},
        'non_string_allocations':{**prior['non_string_allocations'],'phy_analog_member_bytes':phy['members'].get('phy_analog_cal.o',0)},
        'selected_symbols':{old:{'original_or_alias':symbols[old],'source_symbol':new,'source_body':symbols.get(new)} for old,new in SELECTED[chip].items()},
        'divisor_symbols':{n:symbols[n] for n in sorted(set(DATA)|{v[0] for v in DATA.values()})},
        'allocated_phy_members':phy['members'],'allocated_phy_inputs':phy['inputs'],'input_archives_observed':base['input_archives_observed'],
        'retained_feature_rom_backups':prior['retained_feature_rom_backups'],
        'limits':['Linked-image ownership does not establish archive-wide or ROM replacement.',
                  'Source alias sizes can be stale; real source bodies are checked separately.',
                  'Native ABI, callback semantics, instruction behavior and device behavior need separate validation.']}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--elf',type=Path,required=True);p.add_argument('--map',type=Path,required=True)
    p.add_argument('--label',required=True);p.add_argument('--expect-analog',choices=['vendor','source'],required=True)
    a=p.parse_args();print(json.dumps(audit(a.elf,a.map,a.label,a.expect_analog),indent=2))
if __name__=='__main__':main()
