"""Compare independently expressed TX detector control flow to original instructions.

This is a software-boundary comparison, not an RF model.
"""
from pathlib import Path
import hashlib, json, random
import machine

ROOT = Path(__file__).resolve().parent
MASK = 0xffffffff
REG = 0x6000e05c


class Boundary:
    def __init__(self, chip, evidence, case):
        self.chip, self.e, self.case = chip, evidence, case
        self.param = int(evidence['symbols']['phy_param']['address'], 0)
        self.memory, self.trace, self.calls = {}, [], 0
        self.put(self.param + 0x120, 4, case['flags'])
        self.put(REG, 4, case['register'])
        self.put(self.param + 218, 2, 0x1234)
        self.put(self.param + 220, 2, 0x5678)

    def put(self, address, width, value):
        for i in range(width):
            self.memory[address + i] = (value >> (8 * i)) & 255

    def get(self, address, width):
        return sum(self.memory.get(address + i, 0) << (8 * i) for i in range(width))

    def location(self, address, width):
        if 0x100000 <= address < 0x110000:
            return None  # private ABI spills
        if self.param <= address and address + width <= self.param + 0x300:
            return ['param', address - self.param]
        machine.require(address == REG and width == 4, (hex(address), width))
        return ['register', REG]

    def read(self, address, width):
        value = self.get(address, width)
        where = self.location(address, width)
        if where is not None:
            self.trace.append(['read', width, where, value])
        return value

    def write(self, address, width, value):
        value &= (1 << (8 * width)) - 1
        where = self.location(address, width)
        if where is not None:
            self.trace.append(['write', width, where, value])
        self.put(address, width, value)

    def helper(self, name, args):
        arity = {'start_tx_tone_step': 6, 'get_tone_sar_dout': 1,
                 'txcal_debuge_mode': 0, 'txcal_work_mode': 0}[name]
        machine.require(len(args) == arity, 'Contract check failed')
        self.trace.append(['helper', name, args])
        # Explicit adversarial boundary: helper calls may change relevant state.
        # Both programs receive identical effects; no hardware behavior is inferred.
        index = self.calls
        self.calls += 1
        effect = self.case['effects'][index]
        for address, width, value in ((REG, 4, effect[0]), (self.param + 0x120, 4, effect[1]),
                                      (self.param + 218, 2, effect[2]), (self.param + 220, 2, effect[3])):
            self.put(address, width, value)
        self.trace.append(['helper_effect', index, effect])
        return self.case['returns'][index]

    def final(self):
        return [self.get(REG, 4), self.get(self.param + 0x120, 4),
                self.get(self.param + 218, 2), self.get(self.param + 220, 2)]


class Original(Boundary, machine.Machine):
    def __init__(self, chip, evidence, case):
        Boundary.__init__(self, chip, evidence, case)
        self.program, self.starts = machine.decode(evidence)
        self.kinds = dict(zip(self.starts, (0, 1)))
        self.kinds.update({address: 0 for address in evidence.get('internal_reference_helpers', [])})
        self.steps, self.visited, self.branches = 0, set(), set()
        self.helpers = {int(evidence['symbols'][n]['address'], 0): n for n in (
            'start_tx_tone_step', 'get_tone_sar_dout', 'txcal_debuge_mode', 'txcal_work_mode')}

    def enter(self, kind, stack):
        machine.require(0x100000 <= stack < 0x110000, 'Contract check failed')

    def dispatch(self, target, values, registers, depth):
        if target in self.kinds:
            machine.require(self.kinds[target] == 0, 'Contract check failed')
            child = self.registers(registers['a1' if self.chip == 'esp32s3' else 'sp'])
            child['a2' if self.chip == 'esp32s3' else 'a0'] = values(1)[0]
            return self.execute(target, child, 0, depth + 1)
        machine.require(target in self.helpers, hex(target))
        name = self.helpers[target]
        arity = {'start_tx_tone_step': 6, 'get_tone_sar_dout': 1,
                 'txcal_debuge_mode': 0, 'txcal_work_mode': 0}[name]
        return self.helper(name, values(arity))

    def run(self):
        registers = self.registers()
        registers['a2' if self.chip == 'esp32s3' else 'a0'] = self.case['code']
        self.execute(self.starts[self.case['operation']], registers, self.case['operation'])


def reference(io, code):
    io.helper('start_tx_tone_step', [1, 128, code & 255, 0, 0, 0])
    io.write(REG, 4, io.read(REG, 4) & 0xffff0000)
    sample = io.helper('get_tone_sar_dout', [4])
    saved = io.read(REG, 4)
    io.write(io.param + 218, 2, sample)
    io.write(REG, 4, (saved & 0xffff0000) | 0x5555)
    sample = io.helper('get_tone_sar_dout', [4])
    if io.chip == 'esp32s3':
        io.write(io.param + 220, 2, sample)
        saved = io.read(REG, 4)
    else:
        saved = io.read(REG, 4)
        io.write(io.param + 220, 2, sample)
    io.write(REG, 4, (saved & 0xffff0000) | 0xaaaa)


def model(io):
    if io.case['operation'] == 0:
        reference(io, io.case['code'])
    elif io.read(io.param + 0x120, 4) & (1 << 24) == 0:
        io.helper('txcal_debuge_mode', [])
        reference(io, 80 if io.chip == 'esp32s3' else 120)
        io.helper('txcal_work_mode', [])
        io.write(io.param + 0x120, 4, io.read(io.param + 0x120, 4) | (1 << 24))


def cases():
    rng = random.Random(0x50574445)
    values = [0, 1, 0x7fff, 0x8000, 0xffff, 0x10000, 0x80000000, MASK]
    codes = list(range(256)) + [0x100, 0x10001, 0x80000080, MASK]
    for operation in (0, 1):
        for code in codes:
            for enabled in (False, True):
                flags = rng.getrandbits(32) & ~(1 << 24)
                if enabled:
                    flags |= 1 << 24
                yield dict(operation=operation, code=code, flags=flags, register=rng.getrandbits(32),
                           returns=[values[(code + i) % len(values)] for i in range(5)],
                           effects=[[rng.getrandbits(32), rng.getrandbits(32), rng.getrandbits(16), rng.getrandbits(16)] for _ in range(5)])


def main():
    manifest = json.loads((ROOT / 'manifest.json').read_text())
    for name, digest in manifest['files'].items():
        machine.require(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, 'Fixture hash differs: ' + name)
    records = {}
    for chip in ('esp32c3', 'esp32s3'):
        evidence = json.loads((ROOT / (chip + '-instructions.json')).read_text())
        digest = hashlib.sha256()
        visited, branches = set(), set()
        for index, case in enumerate(cases()):
            original, abstract = Original(chip, evidence, case), Boundary(chip, evidence, case)
            original.run()
            model(abstract)
            machine.require(original.trace == abstract.trace, (chip, index, original.trace, abstract.trace))
            machine.require(original.final() == abstract.final(), (chip, index))
            visited.update(original.visited)
            branches.update(original.branches)
            digest.update(json.dumps([case, original.trace, original.final()], separators=(',', ':')).encode() + b'\n')
        program, _ = machine.decode(evidence)
        edges = {(pc, take) for pc, (_, op, _) in program.items() if op in machine.CONDITIONAL for take in (False, True)}
        machine.require(visited == set(program) and branches == edges, 'Contract check failed')
        records[chip] = dict(cases=index + 1, instructions=len(program), covered_instructions=len(visited),
                             edges=len(edges), covered_edges=len(branches), trace_sha256=digest.hexdigest())
    machine.require(records == json.loads((ROOT / 'expected-results.json').read_text()), 'Original corpus changed')
    print(records)


if __name__ == '__main__':
    main()
