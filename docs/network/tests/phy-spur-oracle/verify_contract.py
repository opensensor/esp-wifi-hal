"""S3 spur original-instruction oracle and independent boundary model.

Compare ordered parameter/MMIO accesses and external helper calls. Callback
names are slot identifiers, without assuming physical units or analog effects.
Private stack scheduling and MEMW timing are outside this trace model.
"""
import hashlib
import json
import random
from pathlib import Path
from machine import Machine, decode, require, signed, MASK, CONDITIONAL, IntegerDivideByZero

HERE = Path(__file__).resolve().parent
PARAM = 0x230000
REGISTERS = [0x6001d014, 0x6001d018, 0x6001cc48, 0x60035000,
             0x60006148, 0x6000614c, 0x60006150, 0x60006154, 0x60006164]
SAMPLE_REGISTERS = REGISTERS[4:]


class Spur(Machine):
    def __init__(self, evidence):
        self.chip, self.e = 'esp32s3', evidence
        self.program, self.entries = decode(evidence)
        self.kinds = {v: i for i, v in enumerate(self.entries)}
        self.symbols = {n: int(s['address'], 0) for n, s in evidence['symbols'].items()}
        self.param, self.table = self.symbols['phy_param'], self.symbols['g_phyFuns']
        self.slots = {'slot_1d4': (0x1d4, 1), 'slot_50': (0x50, 4),
                      'slot_4c': (0x4c, 2), 'slot_40': (0x40, 2),
                      'slot_f0': (0xf0, 2), 'slot_f4': (0xf4, 0),
                      'slot_104': (0x104, 2)}
        self.direct = {n: self.symbols[n] for n in
                       ['chip_v7_set_chan', 'phy_set_freq', 'start_tx_tone_step', 'phy_printf']}
        require(len(evidence['logs']) == 1, 'Unexpected log count')
        self.format = int(evidence['logs'][0]['address'], 0)

    def put(self, address, width, value):
        for i in range(width):
            self.mem[address+i] = (value >> (8*i)) & 255

    def get(self, address, width):
        require(width in (1, 2, 4) and address % width == 0, 'Unaligned access')
        if 0x70000000 <= address < 0x71000000:
            require(width == 4, 'Wrong callback slot width')
            return address + 0x1000000
        require(all(address+i in self.mem for i in range(width)), f'Uninitialized {address:x}/{width}')
        return sum(self.mem[address+i] << (8*i) for i in range(width))

    def observed(self, address):
        return self.param <= address < self.param+1024 or address in REGISTERS

    def canonical(self, address):
        return PARAM+address-self.param if self.param <= address < self.param+1024 else address

    def read(self, address, width):
        if address == 0x60035000:
            self.put(address, 4, self.c['timers'][min(self.timer_reads, 1)])
            self.timer_reads += 1
        elif address == 0x6001cc48:
            self.put(address, 4, self.c['final_register_reads'][min(self.final_reads, 1)])
            self.final_reads += 1
        value = self.get(address, width)
        if self.observed(address):
            self.trace.append(['read', self.canonical(address), width, value])
        else:
            require(0x100000 <= address < 0x110000 or address == self.table or
                    0x70000000 <= address < 0x71000000, f'Undocumented read {address:x}')
        return value

    def write(self, address, width, value):
        require(width in (1, 2, 4) and address % width == 0, 'Unaligned write')
        value &= (1 << (width*8))-1
        if self.observed(address):
            self.trace.append(['write', self.canonical(address), width, value])
        else:
            require(0x100000 <= address < 0x110000, f'Undocumented write {address:x}')
        self.put(address, width, value)

    def enter(self, kind, sp):
        require(sp % 16 == 0, 'Unaligned stack')

    def target(self, kind):
        return self.read(self.read(self.table, 4)+self.slots[kind][0], 4)

    def call(self, kind, args, target=None):
        if target is None:
            target = self.target(kind) if kind in self.slots else self.direct[kind]
        if kind in self.slots:
            require(target == 0x71000000+self.generation*0x1000+self.slots[kind][0], 'Cached callback target')
            require(len(args) == self.slots[kind][1], 'Wrong callback arity')
        self.trace.append(['call', kind, target if kind in self.slots else 0, *[v & MASK for v in args]])
        result = self.c['unused_return']
        if kind == 'slot_1d4':
            result = self.c['divisor']
        elif kind == 'slot_50':
            result = self.c['scale_returns'][self.scales]
            self.scales += 1
        elif kind == 'slot_f0':
            require(args == [1, 4095], 'Unexpected estimator start ABI')
            values = self.c['samples'][self.samples % len(self.c['samples'])]
            self.samples += 1
            for address, value in zip(SAMPLE_REGISTERS, values):
                self.put(address, 4, value)
        elif kind == 'slot_104':
            result = self.c['numeric_returns'][self.numerics % len(self.c['numeric_returns'])]
            self.numerics += 1
        if self.c['mutation']:
            # Inputs can change in an opaque callback; distinguish live loads
            # from precomputed enable decisions and cached callback pointers.
            address, width = [(self.param+0x2a6, 1), (self.param+0x2d7, 1),
                              (0x6001d014, 4), (0x6001d018, 4)][self.calls % 4]
            self.write(address, width, self.get(address, width) ^ (self.calls*13+0x55))
        self.calls += 1
        if self.c['table_mutation']:
            self.generation += 1
            self.put(self.table, 4, 0x70000000+self.generation*0x1000)
        self.trace.append(['return', result & MASK])
        return result & MASK

    def dispatch(self, target, values, registers, depth):
        if 0x71000000 <= target < 0x72000000:
            slot = (target-0x71000000) % 0x1000
            kind = next((k for k, (s, _) in self.slots.items() if s == slot), None)
            require(kind is not None, 'Unknown callback')
            return self.call(kind, values(self.slots[kind][1]), target)
        kind = next((k for k, v in self.direct.items() if v == target), None)
        require(kind is not None, f'Unknown helper {target:x}')
        if kind == 'phy_printf':
            args = values(5)
            require(args[0] == self.format, 'Unexpected format')
            return self.call(kind, [0, *args[1:]], target)
        return self.call(kind, values({'chip_v7_set_chan': 2, 'phy_set_freq': 2,
                                       'start_tx_tone_step': 6}[kind]), target)

    def init(self, case):
        self.c, self.mem, self.trace = case, {}, []
        self.steps = self.calls = self.generation = self.scales = self.samples = self.numerics = 0
        self.timer_reads = self.final_reads = 0
        self.visited, self.branches = set(), set()
        for i in range(1024):
            self.put(self.param+i, 1, i*7+case['seed'])
        self.put(self.param+0x2a6, 1, case['parameter_enable'])
        self.put(self.param+0x2d7, 1, case['parameter_level'])
        self.put(self.table, 4, 0x70000000)
        for address in REGISTERS:
            self.put(address, 4, case['register'])

    def run(self, case, model=False):
        self.init(case)
        try:
            if model:
                (self.config_model if case['kind'] == 0 else self.power_model)()
            else:
                registers = self.registers()
                for i, value in enumerate(case['args'] if case['kind'] == 0 else [case['logging']]):
                    if i < 6:
                        registers[f'a{i+2}'] = value & MASK
                    else:
                        self.put(registers['a1']+4*(i-6), 4, value)
                self.execute(self.entries[case['kind']], registers, case['kind'])
        except IntegerDivideByZero:
            self.trace.append(['exception', 6])
        return self.trace

    def clear_path(self, address):
        self.write(address, 4, self.read(address, 4) & ~0x2000)

    @staticmethod
    def scaled(value):
        # Independent expression of the signed constant-division sequence.
        value = signed(value << 10)
        return (abs(value)//100) * (-1 if value < 0 else 1)

    def config_model(self):
        channel, mode, forced, width, flags, coefficient, enabled = self.c['args']
        channel = signed(channel, 8)
        mode = signed(mode, 8)
        forced, width, enabled = forced & 255, width & 255, enabled & 255
        flags, coefficient = flags & 65535, coefficient & 65535
        scale = 10 if mode < 2 else 20
        divisor = self.call('slot_1d4', [channel])
        span = {0: 40, 1: 26, 2: 24}.get(width, 40)
        if forced or (self.read(self.param+0x2a6, 1) != 0 and self.read(self.param+0x2d7, 1) > 10):
            actual_span = 48 if self.read(self.param+0x2a6, 1) else span
            result = self.call('slot_50', [divisor, scale, actual_span, 1])
            self.call('slot_4c', [0, self.scaled(result)])
        else:
            self.clear_path(0x6001d014)
        if flags:
            result = self.call('slot_50', [divisor, scale, coefficient, enabled])
            active = result != 0 and bool(flags & 0x4000) and bool((flags >> ((channel-1) & 31)) & 1)
            self.call('slot_4c', [1, self.scaled(result) if active else 0])
        else:
            self.clear_path(0x6001d018)
        shift = (self.read(0x6001cc48, 4) >> 24) & 31
        numerator = signed(80 << shift)
        upper = self.read(0x6001cc48, 4) & 0xff000000
        divisor = signed(divisor)
        if divisor == 0:
            raise IntegerDivideByZero()
        quotient = (abs(numerator)//abs(divisor)) * (-1 if (numerator < 0) != (divisor < 0) else 1)
        self.write(0x6001cc48, 4, upper | (quotient & 0xffffff))

    def power_model(self):
        start = self.read(0x60035000, 4)
        self.call('chip_v7_set_chan', [7, 0])
        self.call('phy_set_freq', [2443, 0])
        self.call('slot_40', [1, 54])
        self.call('start_tx_tone_step', [1, 128, 0, 0, 0, 0])
        minimum, associated, iteration = 0, 0, 0
        while True:
            self.call('slot_f0', [1, 4095])
            a = self.read(0x60006148, 4)
            b = self.read(0x6000614c, 4)
            c = self.read(0x60006150, 4)
            d = self.read(0x60006154, 4)
            x, y = signed(a+d), signed(b-c)
            high = signed((x*x+y*y) >> 32)
            first = self.call('slot_104', [high >> 6, 0])
            second = self.call('slot_104', [signed(self.read(0x60006164, 4)) >> 9, 0])
            candidate = (signed(second+8) >> 4) & MASK
            self.call('slot_f4', [])
            if iteration == 0 or candidate < minimum:
                associated = (signed(first+8) >> 4) & MASK
                minimum = candidate
            if minimum <= 24:
                break
            iteration += 1
            if iteration == 10:
                break
        self.call('start_tx_tone_step', [0, 128, 0, 0, 0, 0])
        self.call('slot_40', [0, 54])
        self.write(self.param+0x2d7, 1, associated)
        self.write(self.param+0x2d8, 1, minimum)
        if self.c['logging'] & 255:
            elapsed = (self.read(0x60035000, 4)-start) & MASK
            self.call('phy_printf', [0, iteration, elapsed, associated, minimum])


def base(kind):
    return dict(kind=kind, args=[7, 2, 1, 0, 0x4040, 4321, 1], logging=1,
                parameter_enable=1, parameter_level=11, divisor=2443,
                scale_returns=[100, 101], numeric_returns=[800, 1024],
                samples=[[0x80000000, 0x80000000, 0, 0, 0xffffffff]],
                timers=[0xffffff00, 0x12345], final_register_reads=[0x1b123456, 0xaaaabbcc],
                register=0x87654321, seed=27, mutation=False, table_mutation=True,
                unused_return=0xa5a51234)


def cases():
    rng = random.Random(0x53505552)
    for channel in [0, 1, 7, 14, 31, 32, 127, 128, 255, 0x10001, 0xffffffff]:
        for flags in [0, 1, 0x4000, 0x4040, 0x4001, 0xffff, 0x10000]:
            for mode in [0, 1, 2, 127, 128, 255, 0x10002]:
                c = base(0)
                c['args'] = [channel, mode, rng.choice([0, 1, 256]), rng.randrange(5), flags, 0x12345678, 0x98765432]
                c.update(parameter_enable=rng.choice([0, 1, 255]), parameter_level=rng.choice([0, 10, 11, 255]))
                yield c
    for shift in range(32):
        for divisor in [0, 1, -1, 3, -3, 2443, 0x7fffffff, 0x80000000]:
            c = base(0)
            c.update(divisor=divisor & MASK, final_register_reads=[shift << 24, 0xfd123456])
            yield c
    for value in [0, 1, -1, 3, 0x1fffff, 0x200000, 0x7fffffff, 0x80000000, 0xffffffff]:
        c = base(0)
        c['scale_returns'] = [value & MASK, value & MASK]
        yield c
    for i in range(1600):
        c = base(0)
        c.update(args=[rng.getrandbits(32) for _ in range(7)], divisor=rng.getrandbits(32),
                 scale_returns=[rng.getrandbits(32) for _ in range(2)],
                 final_register_reads=[rng.getrandbits(32) for _ in range(2)],
                 parameter_enable=rng.randrange(256), parameter_level=rng.randrange(256),
                 table_mutation=i%3 != 0, mutation=i%2 == 0)
        yield c
    # Script every possible termination iteration, equal/nonmonotonic minima,
    # arithmetic wrap/carry, signed values and low-byte logging narrowing.
    for logging in [0, 1, 255, 256, 0x12340001]:
        for end in range(11):
            c = base(1)
            values = []
            for i in range(10):
                values += [0x80000000+i*256, (24 if i == end else 50-i)*16]
            c.update(logging=logging, numeric_returns=values)
            yield c
    boundary = [0, 1, 0x7fffffff, 0x80000000, 0xffffffff, 0x10000, 0xffff0000]
    for a in boundary:
        for b in boundary:
            c = base(1)
            c.update(samples=[[a, b, 0, 0, a]], numeric_returns=[a, b])
            yield c
    for i in range(1800):
        c = base(1)
        vals = [rng.choice([0, 376, 384, 392, 400, 0xffffffff, 0xfffffff8, 0x7ffffff8,
                            0x80000000, 0x7fffffff, rng.getrandbits(32)]) for _ in range(20)]
        c.update(logging=rng.choice([0, 1, 256, rng.getrandbits(32)]), numeric_returns=vals,
                 samples=[[rng.getrandbits(32) for _ in range(5)] for _ in range(10)],
                 timers=[rng.getrandbits(32) for _ in range(2)],
                 mutation=i%2 == 0, table_mutation=i%3 != 0, unused_return=rng.getrandbits(32))
        yield c


def check_pins():
    manifest = json.loads((HERE/'manifest.json').read_text())
    for name, expected in manifest['files_sha256'].items():
        require(hashlib.sha256((HERE/name).read_bytes()).hexdigest() == expected, 'Changed pinned file '+name)


def main():
    check_pins()
    evidence = json.loads((HERE/'esp32s3-instructions.json').read_text())
    original, reference = Spur(evidence), Spur(evidence)
    pcs, edges, digest, count = set(), set(), hashlib.sha256(), 0
    for count, case in enumerate(cases(), 1):
        try:
            a, b = original.run(case), reference.run(case, True)
        except Exception:
            (HERE/'failure.json').write_text(json.dumps(dict(index=count, case=case, original=original.trace, reference=reference.trace), indent=2)+'\n')
            raise
        if a != b:
            (HERE/'failure.json').write_text(json.dumps(dict(index=count, case=case, original=a, reference=b), indent=2)+'\n')
            mismatch = next((i for i, pair in enumerate(zip(a, b)) if pair[0] != pair[1]), min(len(a), len(b)))
            raise ValueError(f'Case {count}, trace mismatch {mismatch}: {a[mismatch:mismatch+1]} versus {b[mismatch:mismatch+1]}')
        pcs |= original.visited
        edges |= original.branches
        digest.update(json.dumps([case, a], separators=(',', ':')).encode())
    all_edges = {(pc, take) for pc, (_, op, _) in original.program.items() if op in CONDITIONAL for take in (False, True)}
    result = dict(cases=count, instructions=len(original.program), covered_instructions=len(pcs),
                  edges=len(all_edges), covered_edges=len(edges),
                  uncovered_pcs=[hex(v) for v in sorted(set(original.program)-pcs)],
                  uncovered_edges=[[hex(v), t] for v, t in sorted(all_edges-edges)],
                  trace_sha256=digest.hexdigest())
    print(json.dumps(result), flush=True)
    require(pcs == set(original.program) and edges == all_edges, 'Uncovered original instructions/edges')
    require(result == json.loads((HERE/'expected-results.json').read_text()), 'Changed expected original result')


if __name__ == '__main__':
    main()
