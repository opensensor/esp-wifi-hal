#!/usr/bin/env python3
"""Extract bounded reachable instructions from the private, hash-pinned ELF.

Requires pyelftools and the corresponding GNU objdump. This does not publish
firmware, PHY state, calibration data, or network configuration.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
from elftools.elf.elffile import ELFFile


NAMES = {
    'esp32c3': ['phy_set_tsens_power', 'rom2_tsens_read_init1', 'phy_xpd_tsens',
                'rom2_temp_to_power1', 'get_temp_init'],
    'esp32s3': ['phy_set_tsens_power', 'tsens_read_init_new', 'phy_xpd_tsens',
                'ram_tsens_code_read', 'ram_temp_to_power', 'get_temp_init'],
}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def extract(chip, path, objdump, baseline):
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == baseline['elf_sha256'], 'ELF hash differs')
    elf = ELFFile(io.BytesIO(raw))
    symbols = {s.name: s for s in elf.get_section_by_name('.symtab').iter_symbols()}

    def read(address, size):
        for section in elf.iter_sections():
            start = section['sh_addr']
            if start <= address and address + size <= start + section['sh_size']:
                return section.data()[address-start:address-start+size]
        raise ValueError('Unmapped ELF read')

    functions, literals = [], {}
    for name in NAMES[chip]:
        symbol = symbols[name]
        start, size = symbol['st_value'], symbol['st_size']
        body = read(start, size)
        require(size > 0, 'Missing function body')
        pending, program = [start], {}
        while pending:
            address = pending.pop()
            if address in program:
                continue
            require(start <= address < start + size, 'Branch outside function')
            # Restart at every reachable PC; literals/padding between functions
            # must never be mistaken for executable instructions.
            output = subprocess.check_output([objdump, '-d', f'--start-address={address}',
                                              f'--stop-address={start+size}', str(path)], text=True)
            match = re.search(r'^[ \t]*([0-9a-f]+):[ \t]+([0-9a-f]+)[ \t]+(\S+)(?:[ \t]+([^\n]*))?$', output, re.M)
            require(match is not None and int(match[1], 16) == address, 'Missing instruction')
            encoded, op = match[2], match[3]
            args = re.split(r'\s*[<#]', match[4] or '')[0].strip()
            width = len(encoded) // 2
            require(width in (2, 3, 4), 'Unsupported width')
            require(int(encoded, 16).to_bytes(width, 'little') == read(address, width), 'Byte mismatch')
            program[address] = f'{address:x}: {encoded} {op}' + (f' {args}' if args else '')
            if op == 'l32r':
                literal = int(args.split(',')[1], 16)
                literals[hex(literal)] = hex(int.from_bytes(read(literal, 4), 'little'))
            if op in ('ret', 'retw.n'):
                continue
            if op == 'j':
                target = int(args.split(',')[-1], 16)
                # C3 read initialization tail-calls the selected power body.
                if start <= target < start + size:
                    pending.append(target)
                else:
                    require(target in [symbols[n]['st_value'] for n in NAMES[chip]], 'Unknown tail target')
                continue
            if op in ('beq', 'beqi', 'blt', 'bge', 'bne', 'beqz', 'beqz.n',
                      'bnez', 'bnez.n', 'blez', 'bgtz', 'blti'):
                pending.append(int(args.split(',')[-1], 16))
            pending.append(address + width)
        functions.append({'name': name, 'address': hex(start), 'size_bytes': size,
                          'body_sha256': hashlib.sha256(body).hexdigest(), 'code_hex': body.hex(),
                          'instructions': [program[a] for a in sorted(program)]})
    recorded = {n: {'address': hex(symbols[n]['st_value']), 'size_bytes': symbols[n]['st_size']}
                for n in ('phy_param', 'g_phyFuns', 'phy_tsens_attribute',
                          '__opensensor_tsens_outer', 'rom_phy_xpd_tsens')}
    attr = symbols['phy_tsens_attribute']
    require(attr['st_size'] == 30, 'Attribute table must contain exactly five six-byte rows')
    return {'elf_sha256': baseline['elf_sha256'], 'map_sha256': baseline['map_sha256'],
            'functions': functions, 'symbols': recorded, 'literals': literals,
            'attribute_bytes': list(read(attr['st_value'], 30))}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('chip', choices=NAMES)
    p.add_argument('elf', type=Path)
    p.add_argument('objdump')
    p.add_argument('output', type=Path)
    args = p.parse_args()
    baseline = json.loads(Path(__file__).parents[2].joinpath('phy-temperature-validation.json').read_text())
    result = extract(args.chip, args.elf, args.objdump, baseline['allocations'][args.chip+'/source-v4'])
    args.output.write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
