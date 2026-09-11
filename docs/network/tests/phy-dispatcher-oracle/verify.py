#!/usr/bin/env python3
"""Bounded original-instruction oracle. Analog calls are opaque boundaries."""
import hashlib
import json
from pathlib import Path
import re
import struct
import sys


def require(ok, message):
    if not ok:
        raise ValueError(message)


def decode(evidence):
    f = evidence['function']
    expected = int(f['address'], 0)
    code = bytearray()
    program = {}
    for line in f['instructions']:
        match = re.fullmatch(r'([0-9a-f]+): ([0-9a-f]+) (\S+)(?: (.*))?', line)
        require(match is not None, 'Malformed instruction')
        addr, raw, op, args = match.groups()
        addr = int(addr, 16)
        width = len(raw) // 2
        require(width in (2, 3, 4) and addr == expected, 'Instruction coverage gap')
        code += int(raw, 16).to_bytes(width, 'little')
        expected += width
        program[addr] = (expected, op, [a.strip() for a in (args or '').split(',') if a.strip()])
    require(len(code) == f['size_bytes'] and code.hex() == f['code_hex'], 'Code bytes differ')
    require(hashlib.sha256(code).hexdigest() == f['instruction_bytes_sha256'], 'Code hash differs')
    return program


class Oracle:
    def __init__(self, chip, evidence):
        self.chip, self.e = chip, evidence
        self.program = decode(evidence)
        self.param = int(evidence['symbols']['phy_param']['address'], 0)
        require(evidence['symbols']['phy_param']['size_bytes'] == (848 if chip == 'esp32c3' else 740),
                'Unexpected parameter size')
        self.table_var = int(evidence['symbols']['g_phyFuns']['address'], 0)
        self.direct = {}
        for name, kind in [('rom1_tsens_temp_read', 7), ('ram2_rfpll_cap_track', 9),
                           ('rfcal_track', 10), ('rfpll_cap_track', 9)]:
            if name in evidence['symbols']:
                self.direct[int(evidence['symbols'][name]['address'], 0)] = kind
        if chip == 'esp32c3':
            self.direct[0x40001c2c] = 8

    def run(self, case):
        first, second, gate, low, pll, arg, rf, token, hooks = case
        s3 = self.chip == 'esp32s3'
        mem = bytearray(self.e['symbols']['phy_param']['size_bytes'])
        if s3:
            mem[0x2a0:0x2a4] = ((gate << 16) | low).to_bytes(4, 'little')
        else:
            mem[0x320], mem[0x31f] = gate & 255, gate >> 8
        mem[0x9c], mem[0x9b], mem[0x216] = pll, arg, rf
        generation = 0
        trace, stack = [], {}
        registers = {f'a{i}': 0 for i in range(16)}
        registers.update(sp=0x100100, ra=0, s0=0, s1=0, s2=0, s3=0, t1=0)
        registers.update({'a2': first, 'a3': second} if s3 else {'a0': first, 'a1': second})

        def event(kind, a=0, b=0, c=0):
            trace.extend((kind, a, b, c))

        def read(address, width):
            if self.param <= address and address + width <= self.param + len(mem):
                offset = address - self.param
                value = int.from_bytes(mem[offset:offset+width], 'little')
                event(1 if width == 1 else 2, offset, value)
                return value
            if address == self.table_var and width == 4:
                event(3, generation)
                return 0x70000000 + generation * 0x1000
            table = 0x70000000 + generation * 0x1000
            if table <= address < table + 0x400 and width == 4:
                slot = address - table
                event(4, slot, generation)
                return 0x71000000 + generation * 0x1000 + slot
            if address in stack and width == 4:
                return stack[address]
            raise ValueError(f'Unmapped read {address:x}/{width}')

        def call(target):
            nonlocal generation
            a, b = (registers['a10'], registers['a11']) if s3 else (registers['a0'], registers['a1'])
            slot = None
            if target in self.direct:
                kind = self.direct[target]
            else:
                base = 0x71000000 + generation * 0x1000
                require(base <= target < base + 0x400, 'Unknown/stale callback target')
                slot = target - base
                kinds = {0x160: 5, 0x164: 6, 0x258: 7, 0x28c: 8} if s3 else {0x184: 5, 0x188: 6}
                require(slot in kinds, 'Unexpected callback slot')
                kind = kinds[slot]
            if kind == 5:
                event(5, slot, token)
                if hooks & 1: generation += 1
                if hooks & 64:
                    if s3: mem[0x2a0:0x2a4] = b'\0'*4
                    else: mem[0x320] = mem[0x31f] = 0
            elif kind == 6:
                event(6, slot, a)
                require(a == token, 'Exit token changed')
            elif kind == 7:
                event(7, slot or 0)
                if hooks & 2: generation += 1
                if hooks & 4: mem[0x9c], mem[0x9b], mem[0x216] = 255, 91, 1
            elif kind == 8:
                event(8, a, b)
                if hooks & 8: mem[0x9c], mem[0x9b] = 128, 127
            elif kind == 9:
                event(9, a)
                if hooks & 16: mem[0x216], mem[0x9b] = 255, 201
                if hooks & 32: generation += 1
            elif kind == 10:
                event(10, a, b)
                if hooks & 128: generation += 1
            # Clobber caller-saved registers, preserving the ABI's saved bank.
            for reg in ([f'a{i}' for i in range(8, 16)] if s3 else [f'a{i}' for i in range(8)] + ['t1']):
                registers[reg] = 0xdeadbeef
            registers['a10' if s3 else 'a0'] = token if kind == 5 else 0

        pc = int(self.e['function']['address'], 0)
        for step in range(100):
            require(pc in self.program, 'Unknown branch target')
            next_pc, op, args = self.program[pc]
            if op == 'entry':
                require(s3 and step == 0 and args == ['a1', '32'], 'Unexpected entry')
            elif op in ('mv', 'mov.n'):
                registers[args[0]] = registers[args[1]]
            elif op == 'li':
                registers[args[0]] = int(args[1], 0)
            elif op == 'lui':
                registers[args[0]] = int(args[1], 0) << 12
            elif op in ('addi', 'auipc'):
                base = pc if op == 'auipc' else registers[args[1]]
                value = int(args[-1], 0) * (4096 if op == 'auipc' else 1)
                registers[args[0]] = (base + value) & 0xffffffff
            elif op == 'or':
                registers[args[0]] = registers[args[1]] | registers[args[2]]
            elif op == 'extui':
                registers[args[0]] = (registers[args[1]] >> int(args[2])) & ((1 << int(args[3]))-1)
            elif op == 'l32r':
                literal = hex(int(args[1], 16))
                require(literal in self.e['literals'], 'Unrecorded literal')
                registers[args[0]] = int(self.e['literals'][literal], 0)
            elif op in ('lw', 'lbu', 'sw'):
                m = re.fullmatch(r'(-?\d+)\((\w+)\)', args[1])
                require(m is not None, 'Bad memory operand')
                addr = (registers[m[2]] + int(m[1])) & 0xffffffff
                if op == 'sw':
                    require(m[2] == 'sp' and 0x100000 <= addr < 0x100100, 'Non-stack store')
                    stack[addr] = registers[args[0]]
                else:
                    registers[args[0]] = read(addr, 1 if op == 'lbu' else 4)
            elif op in ('l32i', 'l32i.n', 'l8ui'):
                registers[args[0]] = read(registers[args[1]] + int(args[2], 0), 1 if op == 'l8ui' else 4)
            elif op in ('beqz', 'beqz.n', 'bnez', 'bany'):
                test = registers[args[0]]
                taken = (test & registers[args[1]]) != 0 if op == 'bany' else (test != 0 if op == 'bnez' else test == 0)
                if taken: next_pc = int(args[-1], 16)
            elif op in ('jal', 'call8', 'callx8', 'jalr', 'jr'):
                if op in ('jal', 'call8'): target = int(args[0], 16)
                elif '(' in args[0]:
                    m = re.fullmatch(r'(-?\d+)\((\w+)\)', args[0]); require(m is not None, 'Bad call operand')
                    target = (registers[m[2]] + int(m[1])) & 0xffffffff
                else: target = registers[args[0]]
                call(target)
                if op == 'jr':
                    require(not s3 and trace[-4] == 6, 'Unexpected tail call')
                    return trace
            elif op == 'retw.n':
                require(s3 and trace[-4] == 6, 'Unexpected return')
                return trace
            else:
                raise ValueError(f'Unsupported instruction {op}')
            pc = next_pc
        raise ValueError('Instruction budget exhausted')


def cases(chip):
    # Exhaust each boundary separately, then combine adversarial callback changes.
    for first in range(256):
        for second in range(256):
            yield (first, second, 0, 0, 1, 73, 1, 0x80000001, 0)
    for gate in range(65536):
        for low in ((0, 0x5a5a, 0xffff) if chip == 'esp32s3' else (0,)):
            yield (1, 0, gate, low, 1, 9, 1, 0xffffffff, 0)
    for flag in (0, 1, 128, 255):
        for rf in (0, 1, 128, 255):
            for arg in range(256):
                yield (255, 128, 0, 0xffff, flag, arg, rf, 0x80000000, 0)
    for token in (0, 1, 0x80000000, 0xffffffff):
        for hooks in range(256):
            for gate in (0, 0xffff):
                yield (37, 255, gate, 0x5a5a, 0, 0, 0, token, hooks)


def main():
    chip, destination = sys.argv[1:]
    fixture = json.loads(Path(__file__).with_name('original-instructions.json').read_text())
    oracle = Oracle(chip, fixture['chips'][chip])
    digest = hashlib.sha256()
    count = 0
    with open(destination, 'wb') as stream:
        for case in cases(chip):
            trace = oracle.run(case)
            encoded = struct.pack('<' + 'I'*(10+len(trace)), *case, len(trace)//4, *trace)
            stream.write(encoded); digest.update(encoded); count += 1
    report = {'chip':chip, 'cases':count, 'oracle_sha256':digest.hexdigest()}
    expected = json.loads(Path(__file__).with_name('expected-results.json').read_text())[chip]
    require(report == expected, 'Original instruction trace digest changed')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
