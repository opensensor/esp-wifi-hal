#!/usr/bin/env python3
"""Audit complete PHY register programming member replacement after RF PLL replacement."""
import argparse,hashlib,json,re
from pathlib import Path
import audit_phy_allocations as allocations
import audit_phy_hw_freq as previous
import audit_phy_lifecycle as lifecycle
import audit_phy_temperature as temperature
SELECTED={'esp32c3': {'ram1_set_pbus_reg': '__opensensor_reg_pbus', 'rom1_tx_paon_set': '__opensensor_reg_paon', 'btbb_wifi_bb_cfg2': '__opensensor_reg_btbb', 'rx_agc_reg_opt': '__opensensor_reg_agc_options', 'rx_11b_opt': '__opensensor_reg_options_11b', 'rom1_disable_wifi_agc': '__opensensor_reg_disable_agc', 'rom1_enable_wifi_agc': '__opensensor_reg_enable_agc', 'ram1_fe_i2c_reg_renew': '__opensensor_reg_renew', 'phy_wifi_enable_set': '__opensensor_reg_wifi_enable', 'txiq_set_reg': '__opensensor_reg_tx_iq', 'rxiq_set_reg': '__opensensor_reg_rx_iq', 'start_tx_tone_step': '__opensensor_reg_start_tone', 'stop_tx_tone': '__opensensor_reg_stop_tone', 'rom1_set_noise_floor': '__opensensor_reg_noise_floor', 'phy_freq_correct': '__opensensor_reg_frequency_correct', 'force_txrx_off': '__opensensor_reg_force_off'}, 'esp32s3': {'ram_set_pbus_reg': '__opensensor_reg_pbus', 'ram_wifi_tx_dig_gain_reg': '__opensensor_reg_digital_gain', 'btbb_wifi_bb_cfg2': '__opensensor_reg_btbb', 'rx_agc_reg_opt': '__opensensor_reg_agc_options', 'rx_11b_opt': '__opensensor_reg_options_11b', 'ram_disable_wifi_agc': '__opensensor_reg_disable_agc', 'ram_enable_wifi_agc': '__opensensor_reg_enable_agc', 'ram_fe_i2c_reg_renew': '__opensensor_reg_renew', 'phy_wifi_enable_set': '__opensensor_reg_wifi_enable', 'txiq_set_reg': '__opensensor_reg_tx_iq', 'rxiq_set_reg': '__opensensor_reg_rx_iq', 'start_tx_tone_step': '__opensensor_reg_start_tone', 'stop_tx_tone': '__opensensor_reg_stop_tone', 'ram_set_noise_floor': '__opensensor_reg_noise_floor', 'phy_freq_correct': '__opensensor_reg_frequency_correct', 'force_txrx_off': '__opensensor_reg_force_off'}}
ALL_SOURCE_NAMES=set().union(*(set(v.values()) for v in SELECTED.values()))

IRAM={'__opensensor_reg_digital_gain', '__opensensor_reg_options_11b', '__opensensor_reg_disable_agc', '__opensensor_reg_paon', '__opensensor_reg_wifi_enable', '__opensensor_reg_enable_agc', '__opensensor_reg_agc_options', '__opensensor_reg_pbus', '__opensensor_reg_renew', '__opensensor_reg_btbb'}

def check_reg(base,symbols,expected):
    if expected not in ('vendor','source'):raise ValueError('Expected register programming vendor or source')
    chip=base['chip'];inputs=base['allocations']['libphy.a']['inputs'];selected=SELECTED[chip]
    member=[r for r in inputs if r['member']=='phy_reg.o']
    if expected=='source':
        if member:raise ValueError('PHY register programming member phy_reg.o still has allocated inputs')
        if any(r['member']=='phy_reg.o' and r['reported_input_bytes'] for r in base.get('excluded_mergeable_string_inputs',[])):
            raise ValueError('PHY register programming member still has excluded mergeable string input')
    for name in ALL_SOURCE_NAMES-(set(selected.values()) if expected=='source' else set()):
        if symbols.get(name) is not None:raise ValueError('Unexpected register programming source symbol: '+name)
    for old,new in selected.items():
        if expected=='source':
            body=temperature.require_body(symbols,new)
            if new in IRAM:
                start=int(body['address'],0)
                if not (0x40300000<=start and start+body['symbol_size_bytes']<=0x40400000):raise ValueError('Register programming helper must reside in IRAM: '+new)
            if not lifecycle.alias_matches(symbols.get(old),body,executable=True):raise ValueError('Incorrect register programming source alias: '+old)
            if any(temperature.overlaps(r,body) for r in inputs):raise ValueError('register programming source overlaps vendor input: '+new)
            if temperature.original_sections(inputs,old):raise ValueError('Original register programming function input still allocated: '+old)
        else:
            body=temperature.require_body(symbols,old)
            if not any(temperature.contains(r,body) for r in ([r for r in member if r['section']=='.iram1'] if new in IRAM else temperature.original_sections(member,old))):
                raise ValueError('Original register programming body lacks member ownership: '+old)


def audit(elf_path,map_path,label,expected):
    from elftools.elf.elffile import ELFFile
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',label):raise ValueError('Label must be a simple artifact identifier')
    prior=previous.audit(elf_path,map_path,label,'source',reg_source=(expected=='source'))
    base=allocations.audit(elf_path,map_path,label,exclude_strings=True);chip=base['chip']
    with elf_path.open('rb') as stream:symbols=temperature.inspect_symbols(ELFFile(stream),sorted(set().union(*(set(v) for v in SELECTED.values()))|ALL_SOURCE_NAMES))
    check_reg(base,symbols,expected);phy=base['allocations']['libphy.a']
    return {'schema':'phy-reg-allocation-audit-v1','chip':chip,'label':label,'expect_reg':expected,'checks_passed':True,
        'profile':'full-reg-station','elf_sha256':base['elf_sha256'],'map_sha256':base['map_sha256'],'method':base['method'],
        'previous_source_gates':{**prior['previous_source_gates'],'hw_freq':True},
        'non_string_allocations':{**prior['non_string_allocations'],'phy_reg_member_bytes':phy['members'].get('phy_reg.o',0)},
        'selected_symbols':{old:{'original_or_alias':symbols[old],'source_symbol':new,'source_body':symbols.get(new)} for old,new in SELECTED[chip].items()},
        'allocated_phy_members':phy['members'],'allocated_phy_inputs':phy['inputs'],'input_archives_observed':base['input_archives_observed'],
        'retained_feature_rom_backups':prior['retained_feature_rom_backups'],
        'limits':['Linked-image ownership does not establish archive-wide or ROM replacement.',
                  'Source alias sizes can be stale; real source bodies are checked separately.',
                  'Native ABI, callback semantics, instruction behavior and device behavior need separate validation.']}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--elf',type=Path,required=True);p.add_argument('--map',type=Path,required=True)
    p.add_argument('--label',required=True);p.add_argument('--expect-reg',choices=['vendor','source'],required=True)
    a=p.parse_args();print(json.dumps(audit(a.elf,a.map,a.label,a.expect_reg),indent=2))
if __name__=='__main__':main()
