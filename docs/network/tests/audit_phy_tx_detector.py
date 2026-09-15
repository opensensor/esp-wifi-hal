"""Check TX detector source ownership while retaining the other TX routines."""
import argparse
import json
from pathlib import Path
import audit_phy_spur as previous
import audit_phy_allocations as allocations
import audit_phy_temperature as temperature

SELECTED = {'pwdet_ref_code': '__opensensor_tx_detector_reference',
            'pwdet_code_cal': '__opensensor_tx_detector_calibrate'}
RETAINED = ('txdc_cal_v70', 'bt_txdc_cal', 'txdc_cal_init', 'txiq_get_mis_pwr',
            'txiq_cover', 'get_power_atten', 'rfcal_txiq', 'bt_txiq_cal',
            'txiq_cal_init', 'rfcal_txcap', 'tx_cap_init', 'rfcal_pwrctrl',
            'tx_pwctrl_init_cal', 'tx_pwctrl_init', 'bt_tx_pwctrl_init', 'bt_txpwr_freq')


def check_detector(base, symbols, expected):
    if base['chip'] not in ('esp32c3', 'esp32s3') or expected not in ('source', 'vendor'):
        raise ValueError('Invalid detector chip or expectation')
    inputs = base['allocations']['libphy.a']['inputs']
    member = [row for row in inputs if row['member'] == 'phy_tx_cal.o']
    for old, new in SELECTED.items():
        if expected == 'source':
            body = temperature.require_body(symbols, new)
            alias = symbols.get(old)
            if not (alias and alias['address'] == body['address'] and
                    (alias.get('absolute') or alias.get('allocated') and alias.get('executable'))):
                raise ValueError('Wrong TX detector alias: ' + old)
            if any(temperature.overlaps(row, body) for row in inputs):
                raise ValueError('TX detector source overlaps vendor allocation')
            if temperature.original_sections(inputs, old):
                raise ValueError('Original TX detector input remains: ' + old)
        else:
            body = temperature.require_body(symbols, old)
            if not any(temperature.contains(row, body) for row in member):
                raise ValueError('Wrong retained TX detector owner: ' + old)
            if symbols.get(new) is not None:
                raise ValueError('TX detector source body in vendor control')
    for name in RETAINED:
        body = temperature.require_body(symbols, name)
        if not any(temperature.contains(row, body) for row in member):
            raise ValueError('Retained TX calibration dependency lost: ' + name)


def audit(elf_path, map_path, label, expected):
    base = allocations.audit(elf_path, map_path, label, exclude_strings=True)
    prior = previous.audit(elf_path, map_path, label, 'source')
    names = sorted([*SELECTED, *SELECTED.values(), *RETAINED])
    from elftools.elf.elffile import ELFFile
    with elf_path.open('rb') as stream:
        symbols = temperature.inspect_symbols(ELFFile(stream), names)
    check_detector(base, symbols, expected)
    return {**prior, 'schema': 'phy-tx-detector-allocation-audit-v1',
            'expect_tx_detector': expected, 'checks_passed': True,
            'previous_source_gates': {**prior['previous_source_gates'], 'rx_spur': True},
            'tx_detector_symbols': {old: {'original_or_alias': symbols.get(old),
                                        'source_body': symbols.get(new), 'source_symbol': new}
                                    for old, new in SELECTED.items()},
            'retained_tx_calibration_symbols': {name: symbols[name] for name in RETAINED},
            'limits': prior['limits'] + ['Sixteen TX calibration routines per chip and analog/ROM dependencies remain.']}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--elf', type=Path, required=True)
    p.add_argument('--map', type=Path, required=True)
    p.add_argument('--label', required=True)
    p.add_argument('--expect-detector', choices=['source', 'vendor'], required=True)
    args = p.parse_args()
    print(json.dumps(audit(args.elf, args.map, args.label, args.expect_detector), indent=2))
