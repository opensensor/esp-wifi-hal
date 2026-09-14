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


NAMES = {'esp32c3': ['gen_rx_gain_table', 'wr_rx_gain_mem', 'set_rx_gain_param', 'set_rx_gain_table', 'phy_rx_table_init'], 'esp32s3': ['gen_rx_gain_table', 'wr_rx_gain_mem', 'set_rx_gain_param', 'set_rx_gain_table', 'phy_rx_table_init']}
HELPERS = {'esp32c3': ['memcpy', 'phy_printf', 'rom_phy_reg_init', 'set_rf_freq_offset', 'set_rx_gain_cal_dc', 'set_rx_gain_cal_iq'], 'esp32s3': ['memcpy', 'phy_printf', 'rom_phy_reg_init', 'set_rf_freq_offset', 'set_rx_gain_cal_dc', 'set_rx_gain_cal_iq']}



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
            if op in ('ret', 'retw.n', 'jr'):
                continue
            if op == 'j':
                target = int(args.split(',')[-1], 16)
                # Permit only recorded function boundaries for direct tail calls.
                if start <= target < start + size:
                    pending.append(target)
                else:
                    require(target in [symbols[n]['st_value'] for n in NAMES[chip]+HELPERS[chip]], 'Unknown tail target')
                continue
            if op in ('beq', 'beqi', 'blt', 'bge', 'bne', 'beqz', 'beqz.n',
                      'bnez', 'bnez.n', 'blez', 'bgtz', 'blti', 'bany', 'bltz', 'bgez', 'bgeui', 'bltu', 'bnei', 'bbsi', 'bbci', 'bnone', 'loop', 'bgeu', 'bgei', 'bltui', 'bgeui'):
                pending.append(int(args.split(',')[-1], 16))
            pending.append(address + width)
        functions.append({'name': name, 'address': hex(start), 'size_bytes': size,
                          'body_sha256': hashlib.sha256(body).hexdigest(), 'code_hex': body.hex(),
                          'instructions': [program[a] for a in sorted(program)]})
    recorded = {n: {'address': hex(symbols[n]['st_value']), 'size_bytes': symbols[n]['st_size']}
                for n in ['phy_param', 'g_phyFuns', *HELPERS[chip]]}
    readonly, logs = [], []
    for row in baseline['readonly']:
        payload=read(int(row['address'],0),row['size_bytes'])
        require(payload.hex()==row['bytes'] and hashlib.sha256(payload).hexdigest()==row['sha256'],'Readonly re-extraction differs')
        readonly.append(dict(row,bytes=payload.hex()))
    for row in baseline['logs']:
        payload=read(int(row['address'],0),len(bytes.fromhex(row['bytes'])))
        require(payload.hex()==row['bytes'],'Format re-extraction differs');logs.append(dict(row,bytes=payload.hex()))
    return {'readonly':readonly,'logs':logs,'elf_sha256': baseline['elf_sha256'], 'map_sha256': baseline['map_sha256'],
            'functions': functions, 'symbols': recorded, 'literals': literals}



def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('chip', choices=NAMES)
    p.add_argument('elf', type=Path)
    p.add_argument('objdump')
    p.add_argument('output', type=Path)
    args = p.parse_args()
    baseline = json.loads(Path(__file__).with_name('baselines.json').read_text())[args.chip]
    result = extract(args.chip, args.elf, args.objdump, baseline)
    args.output.write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
