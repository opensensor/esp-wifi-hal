"""Check the final S3 RX spur transition and absence of the RX archive member."""
import argparse
import json
from pathlib import Path
import audit_phy_rx_gain_cal as previous
import audit_phy_allocations as allocations
import audit_phy_temperature as temperature

SELECTED = {'spur_coef_cfg_new': '__opensensor_spur_config',
            'phy_2448m_spur_pwr': '__opensensor_spur_power'}


def check_spur(base, symbols, expected):
    if expected not in ('source', 'vendor'):
        raise ValueError('Invalid spur expectation')
    inputs = base['allocations']['libphy.a']['inputs']
    member = [row for row in inputs if row['member'] == 'phy_rx_cal.o']
    strings = [row for row in base.get('excluded_mergeable_string_inputs', [])
               if row['member'] == 'phy_rx_cal.o' and row['reported_input_bytes']]
    if base['chip'] == 'esp32c3':
        if member or strings:
            raise ValueError('C3 RX calibration member returned')
        if any(symbols.get(name) is not None for name in [*SELECTED, *SELECTED.values()]):
            raise ValueError('S3 spur symbol in C3 image')
        return
    if base['chip'] != 'esp32s3':
        raise ValueError('Unsupported spur chip')
    if expected == 'source' and (member or strings):
        raise ValueError('S3 RX calibration member still allocated')
    for old, new in SELECTED.items():
        if expected == 'source':
            body = temperature.require_body(symbols, new)
            alias = symbols.get(old)
            if not (alias and alias['address'] == body['address'] and
                    (alias.get('absolute') or alias.get('allocated') and alias.get('executable'))):
                raise ValueError('Wrong spur source alias: '+old)
            if any(temperature.overlaps(row, body) for row in inputs):
                raise ValueError('Spur source overlaps vendor allocation')
            if temperature.original_sections(inputs, old):
                raise ValueError('Original spur section remains: '+old)
        else:
            body = temperature.require_body(symbols, old)
            if not any(temperature.contains(row, body) for row in member):
                raise ValueError('Wrong retained spur owner: '+old)
            if symbols.get(new) is not None:
                raise ValueError('Source spur body in vendor control')


def audit(elf_path, map_path, label, expected):
    from elftools.elf.elffile import ELFFile
    base = allocations.audit(elf_path, map_path, label, exclude_strings=True)
    prior = previous.audit(elf_path, map_path, label, 'source',
                           spur_source=(expected == 'source' and base['chip'] == 'esp32s3'))
    with elf_path.open('rb') as stream:
        symbols = temperature.inspect_symbols(ELFFile(stream), sorted([*SELECTED, *SELECTED.values()]))
    check_spur(base, symbols, expected)
    return {**prior, 'schema': 'phy-spur-allocation-audit-v1', 'expect_spur': expected,
            'checks_passed': True,
            'previous_source_gates': {**prior['previous_source_gates'], 'rx_gain_cal': True},
            'spur_symbols': {old: {'original_or_alias': symbols.get(old),
                                  'source_body': symbols.get(new), 'source_symbol': new}
                             for old, new in SELECTED.items()},
            'limits': prior['limits'] + ['S3 RX spur routines replaced; TX calibration and analog/ROM dependencies remain.']}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--elf', type=Path, required=True)
    p.add_argument('--map', type=Path, required=True)
    p.add_argument('--label', required=True)
    p.add_argument('--expect-spur', choices=['source', 'vendor'], required=True)
    a = p.parse_args()
    print(json.dumps(audit(a.elf, a.map, a.label, a.expect_spur), indent=2))
