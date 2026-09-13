#!/usr/bin/env python3
"""Re-extract code and data from the pinned pre-analog ELF and linker map.

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
import struct
from elftools.elf.elffile import ELFFile

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('bounded_extract', HERE.parent / 'phy-pwdet-oracle/extract.py')
code = importlib.util.module_from_spec(spec)
spec.loader.exec_module(code)
code.NAMES = {chip: ['get_rc_dout', 'rc_cal'] for chip in ['esp32c3', 'esp32s3']}
code.HELPERS = {chip: ['ets_delay_us', '__floatsidf', '__divdf3', '__subdf3', '__fixdfsi'] for chip in code.NAMES}


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
    result['owned_data_symbols'] = []
    for row in layout['owned_data_symbols']:
        item = dict(row)
        symbol = symbols.get_symbol_by_name(row['name'])[0]
        code.require(symbol['st_info']['type'] == 'STT_OBJECT', 'Missing data object')
        item['address'] = hex(symbol['st_value'])
        item['size'] = symbol['st_size']
        # Preserve the fixture's byte field, when present, from actual ELF data.
        if 'bytes' in row:
            item['bytes'] = read(symbol['st_value'], symbol['st_size']).hex()
        result['owned_data_symbols'].append(item)
    result['referenced_double_constants'] = []
    for row in layout['referenced_double_constants']:
        item = dict(row)
        if chip == 'esp32c3':
            raw = read(int(row['address'], 0), 8)
        else:
            raw = read(int(row['low_literal'], 0), 4) + read(int(row['high_literal'], 0), 4)
        item.update(bytes=raw.hex(), value=struct.unpack('<d', raw)[0])
        result['referenced_double_constants'].append(item)
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
