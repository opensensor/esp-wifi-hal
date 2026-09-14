#!/usr/bin/env python3
"""Audit complete PHY transmit gain member replacement after receive gain replacement."""
import argparse,hashlib,json,re
from pathlib import Path
import audit_phy_allocations as allocations
import audit_phy_rx_gain as previous
import audit_phy_lifecycle as lifecycle
import audit_phy_i2c as i2c
import audit_phy_temperature as temperature
SELECTED={'esp32c3': {'rom1_wifi_tx_dig_gain': '__opensensor_tx_gain_digital', 'bt_chan_pwr_interp': '__opensensor_tx_gain_interpolate', 'rom1_get_rate_fcc_index': '__opensensor_tx_gain_fcc', 'rom1_get_chan_target_power': '__opensensor_tx_gain_limits', 'rom2_get_tx_gain_value1': '__opensensor_tx_gain_lookup', 'rom1_bt_get_tx_gain_new': '__opensensor_tx_gain_bt_get', 'rom1_wifi_get_tx_gain': '__opensensor_tx_gain_wifi_get', 'ram1_wifi_set_tx_gain': '__opensensor_tx_gain_wifi_set', 'rom1_bt_set_tx_gain': '__opensensor_tx_gain_bt_set', 'bt_tx_gain_init': '__opensensor_tx_gain_bt_initialize', 'txcal_gain_check': '__opensensor_tx_gain_calibration_tables'}, 'esp32s3': {'ram_wifi_tx_dig_gain': '__opensensor_tx_gain_digital', 'bt_chan_pwr_interp': '__opensensor_tx_gain_interpolate', 'ram_get_rate_fcc_index': '__opensensor_tx_gain_fcc', 'ram_get_chan_target_power': '__opensensor_tx_gain_limits', 'get_tx_gain_value': '__opensensor_tx_gain_lookup', 'ram_bt_get_tx_gain': '__opensensor_tx_gain_bt_get', 'ram_wifi_get_tx_gain': '__opensensor_tx_gain_wifi_get', 'ram_wifi_set_tx_gain': '__opensensor_tx_gain_wifi_set', 'ram_bt_set_tx_gain': '__opensensor_tx_gain_bt_set', 'bt_tx_gain_init': '__opensensor_tx_gain_bt_initialize', 'tx_gain_set': '__opensensor_tx_gain_calibration_tables', 'dig_gain_check': '__opensensor_tx_gain_dig_check'}}
ALL_SOURCE_NAMES=set().union(*(set(v.values()) for v in SELECTED.values()))

IRAM={'esp32c3': {'__opensensor_tx_gain_digital'}, 'esp32s3': {'__opensensor_tx_gain_digital','__opensensor_tx_gain_bt_set'}}

def check_tx_gain(base,symbols,expected):
    if expected not in ('vendor','source'):raise ValueError('Expected transmit gain vendor or source')
    chip=base['chip'];inputs=base['allocations']['libphy.a']['inputs'];selected=SELECTED[chip]
    member=[r for r in inputs if r['member']=='phy_tx_gain.o']
    if expected=='source':
        if member:raise ValueError('PHY transmit gain member phy_tx_gain.o still has allocated inputs')
        if any(r['member']=='phy_tx_gain.o' and r['reported_input_bytes'] for r in base.get('excluded_mergeable_string_inputs',[])):
            raise ValueError('PHY transmit gain member still has excluded mergeable string input')
    for name in ALL_SOURCE_NAMES-(set(selected.values()) if expected=='source' else set()):
        if symbols.get(name) is not None:raise ValueError('Unexpected transmit gain source symbol: '+name)
    for old,new in selected.items():
        if expected=='source':
            body=temperature.require_body(symbols,new)
            if new in IRAM[chip]:
                if not i2c.in_iram(body):raise ValueError('Transmit gain helper must reside in IRAM: '+new)
            if not lifecycle.alias_matches(symbols.get(old),body,executable=True):raise ValueError('Incorrect transmit gain source alias: '+old)
            if any(temperature.overlaps(r,body) for r in inputs):raise ValueError('transmit gain source overlaps vendor input: '+new)
            if temperature.original_sections(inputs,old):raise ValueError('Original transmit gain function input still allocated: '+old)
        else:
            body=temperature.require_body(symbols,old)
            if not any(temperature.contains(r,body) for r in ([r for r in member if r['section']=='.iram1'] if new in IRAM[chip] else temperature.original_sections(member,old))):
                raise ValueError('Original transmit gain body lacks member ownership: '+old)


def audit(elf_path,map_path,label,expected,*,init_source=False):
    from elftools.elf.elffile import ELFFile
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',label):raise ValueError('Label must be a simple artifact identifier')
    prior=previous.audit(elf_path,map_path,label,'source',tx_gain_source=(expected=='source'),init_source=init_source)
    base=allocations.audit(elf_path,map_path,label,exclude_strings=True);chip=base['chip']
    with elf_path.open('rb') as stream:symbols=temperature.inspect_symbols(ELFFile(stream),sorted(set().union(*(set(v) for v in SELECTED.values()))|ALL_SOURCE_NAMES))
    check_tx_gain(base,symbols,expected);phy=base['allocations']['libphy.a']
    return {'schema':'phy-tx-gain-allocation-audit-v1','chip':chip,'label':label,'expect_tx_gain':expected,'checks_passed':True,
        'profile':'full-tx-gain-station','elf_sha256':base['elf_sha256'],'map_sha256':base['map_sha256'],'method':base['method'],
        'previous_source_gates':{**prior['previous_source_gates'],'rx_gain':True},
        'non_string_allocations':{**prior['non_string_allocations'],'phy_tx_gain_member_bytes':phy['members'].get('phy_tx_gain.o',0)},
        'selected_symbols':{old:{'original_or_alias':symbols[old],'source_symbol':new,'source_body':symbols.get(new)} for old,new in SELECTED[chip].items()},
        'allocated_phy_members':phy['members'],'allocated_phy_inputs':phy['inputs'],'input_archives_observed':base['input_archives_observed'],
        'retained_feature_rom_backups':prior['retained_feature_rom_backups'],
        'limits':['Linked-image ownership does not establish archive-wide or ROM replacement.',
                  'Source alias sizes can be stale; real source bodies are checked separately.',
                  'Native ABI, callback semantics, instruction behavior and device behavior need separate validation.']}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--elf',type=Path,required=True);p.add_argument('--map',type=Path,required=True)
    p.add_argument('--label',required=True);p.add_argument('--expect-tx-gain',choices=['vendor','source'],required=True)
    a=p.parse_args();print(json.dumps(audit(a.elf,a.map,a.label,a.expect_tx_gain),indent=2))
if __name__=='__main__':main()
