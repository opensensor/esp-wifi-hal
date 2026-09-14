#!/usr/bin/env python3
"""Re-extract code and data from the pinned pre-track ELF and linker map.

Requires pyelftools and the chip's GNU objdump. The checked-in fixture supplies
only the pinned data layout; instruction bytes, data bytes and symbol addresses
are read from the supplied ELF. Firmware and configuration stay private.
"""
import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path

from elftools.elf.elffile import ELFFile

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('bounded_extract', HERE.parent / 'phy-pwdet-oracle/extract.py')
code = importlib.util.module_from_spec(spec)
spec.loader.exec_module(code)
code.NAMES = {'esp32c3': ['ram2_rfpll_cap_track', 'rfcal_track', 'rom2_wait_hw_freq_busy', 'rom1_txpwr_cal_track', 'rom2_ulp_ext_code_set', 'rom2_ulp_code_track', 'txpwr_offset'], 'esp32s3': ['ram_wifi_track_tx_power', 'ram_txpwr_cal_track', 'ram_bt_track_tx_power', 'rfpll_cap_track', 'wait_hw_freq_busy', 'ulp_code_track', 'ulp_ext_code_set', 'txpwr_offset']}
code.HELPERS = {'esp32c3': ['ets_delay_us', 'phy_printf', '__opensensor_debug_voltage', '__opensensor_tsens_temp_to_power', 'txdc_cal_init', 'ram1_wifi_set_tx_gain', 'rom1_bt_set_tx_gain', 'rom_phy_bbpll_cal', 'ram2_rfpll_cap_correct'], 'esp32s3': ['ets_delay_us', 'phy_printf', '__opensensor_debug_voltage', '__opensensor_tsens_temp_to_power', 'rfpll_cap_correct']}


def extract(chip, path, map_path, objdump):
    baseline = json.loads((HERE / 'baselines.json').read_text())[chip]
    code.require(hashlib.sha256(map_path.read_bytes()).hexdigest() == baseline['map_sha256'], 'Map hash differs')
    result = code.extract(chip, path, objdump, baseline)
    layout = json.loads((HERE / 'original-instructions.json').read_text())[chip]
    elf = ELFFile(io.BytesIO(path.read_bytes()))
    symbols = elf.get_section_by_name('.symtab')

    def read(address, width):
        for section in elf.iter_sections():
            start = section['sh_addr']
            if section['sh_flags'] & 2 and start <= address and address + width <= start + section['sh_size']:
                data = section.data()[address-start:address-start+width]
                code.require(len(data) == width, 'Missing allocated bytes')
                return data
        raise ValueError('Unmapped allocated data')

    result['owned_inputs'] = []
    for row in layout['owned_inputs']:
        item = dict(row)
        raw = read(int(row['address'], 0), row['size_bytes'])
        if 'bytes' in row:
            item['bytes'] = raw.hex()
        result['owned_inputs'].append(item)
    result['strings'] = []
    for row in layout['strings']:
        item = dict(row)
        raw = read(int(row['address'], 0), len(bytes.fromhex(row['bytes'])))
        item.update(bytes=raw.hex(), text=raw.removesuffix(b'\0').decode())
        result['strings'].append(item)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('chip', choices=code.NAMES)
    parser.add_argument('elf', type=Path)
    parser.add_argument('map', type=Path)
    parser.add_argument('objdump')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(extract(args.chip, args.elf, args.map, args.objdump), indent=2) + '\n')


if __name__ == '__main__':
    main()
