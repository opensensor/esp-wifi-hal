"""Check TX detector source ownership while retaining the other TX routines."""
import argparse
import json
from pathlib import Path
import audit_phy_spur as previous
import audit_phy_allocations as allocations
import audit_phy_temperature as temperature

SELECTED = {'pwdet_ref_code': '__opensensor_tx_detector_reference',
            'pwdet_code_cal': '__opensensor_tx_detector_calibrate'}
TX_IQ_SELECTED = {'txiq_get_mis_pwr': '__opensensor_txiq_measure',
                  'get_power_atten': '__opensensor_txiq_attenuation'}
TX_IQ_WRAPPER_SELECTED = {'txiq_cal_init': '__opensensor_txiq_initialize',
                          'bt_txiq_cal': '__opensensor_txiq_bluetooth'}
RETAINED = ('txdc_cal_v70', 'bt_txdc_cal', 'txdc_cal_init', 'txiq_get_mis_pwr',
            'txiq_cover', 'get_power_atten', 'rfcal_txiq', 'bt_txiq_cal',
            'txiq_cal_init', 'rfcal_txcap', 'tx_cap_init', 'rfcal_pwrctrl',
            'tx_pwctrl_init_cal', 'tx_pwctrl_init', 'bt_tx_pwctrl_init', 'bt_txpwr_freq')


def check_group(base, symbols, selected, expected):
    if base['chip'] not in ('esp32c3', 'esp32s3') or expected not in ('source', 'vendor'):
        raise ValueError('Invalid detector chip or expectation')
    inputs = base['allocations']['libphy.a']['inputs']
    member = [row for row in inputs if row['member'] == 'phy_tx_cal.o']
    for old, new in selected.items():
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


def check_detector(base, symbols, expected, *, expected_iq='vendor', expected_wrappers='vendor'):
    check_group(base, symbols, SELECTED, expected)
    check_group(base, symbols, TX_IQ_SELECTED, expected_iq)
    check_group(base, symbols, TX_IQ_WRAPPER_SELECTED, expected_wrappers)
    member = [row for row in base['allocations']['libphy.a']['inputs']
              if row['member'] == 'phy_tx_cal.o']
    for name in RETAINED:
        if name in TX_IQ_SELECTED or name in TX_IQ_WRAPPER_SELECTED:
            continue  # Explicit source/vendor ownership checked above.
        body = temperature.require_body(symbols, name)
        if not any(temperature.contains(row, body) for row in member):
            raise ValueError('Retained TX calibration dependency lost: ' + name)


def audit(elf_path, map_path, label, expected, *, expected_iq='vendor', expected_wrappers='vendor'):
    base = allocations.audit(elf_path, map_path, label, exclude_strings=True)
    prior = previous.audit(elf_path, map_path, label, 'source')
    names = sorted([*SELECTED, *SELECTED.values(), *RETAINED, *TX_IQ_SELECTED.values(), *TX_IQ_WRAPPER_SELECTED.values()])
    from elftools.elf.elffile import ELFFile
    with elf_path.open('rb') as stream:
        symbols = temperature.inspect_symbols(ELFFile(stream), names)
    check_detector(base, symbols, expected, expected_iq=expected_iq, expected_wrappers=expected_wrappers)
    return {**prior, 'schema': 'phy-tx-detector-allocation-audit-v1',
            'expect_tx_detector': expected, 'expect_tx_iq_measure': expected_iq, 'expect_txiq_wrappers': expected_wrappers, 'checks_passed': True,
            'previous_source_gates': {**prior['previous_source_gates'], 'rx_spur': True},
            'tx_detector_symbols': {old: {'original_or_alias': symbols.get(old),
                                        'source_body': symbols.get(new), 'source_symbol': new}
                                    for old, new in SELECTED.items()},
            'tx_iq_measure_symbols': {old: {'original_or_alias': symbols.get(old),
                                          'source_body': symbols.get(new), 'source_symbol': new}
                                      for old, new in TX_IQ_SELECTED.items()},
            'txiq_wrappers_symbols': {old: {'original_or_alias': symbols.get(old),
                                          'source_body': symbols.get(new), 'source_symbol': new}
                                      for old, new in TX_IQ_WRAPPER_SELECTED.items()},
            'retained_tx_calibration_symbols': {name: symbols[name] for name in RETAINED
                                                if (expected_iq == 'vendor' or name not in TX_IQ_SELECTED)
                                                and (expected_wrappers == 'vendor' or name not in TX_IQ_WRAPPER_SELECTED)},
            'limits': prior['limits'] + [str(16 - 2 * (expected_iq == 'source') - 2 * (expected_wrappers == 'source')) + ' TX calibration routines per chip and analog/ROM dependencies remain.']}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--elf', type=Path, required=True)
    p.add_argument('--map', type=Path, required=True)
    p.add_argument('--label', required=True)
    p.add_argument('--expect-detector', choices=['source', 'vendor'], required=True)
    args = p.parse_args()
    print(json.dumps(audit(args.elf, args.map, args.label, args.expect_detector), indent=2))
