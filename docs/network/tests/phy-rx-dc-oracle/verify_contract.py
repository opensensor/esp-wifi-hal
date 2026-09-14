"""Compare DC reference contracts with pinned original instructions.

No production Rust replacement, analog estimator, or RF equivalence is tested.
The existing instruction engine is pinned locally in manifest.json. Callback
effects and table generations are deliberately visible in the ordered traces.
"""
import hashlib
import json
import random
from pathlib import Path

from machine import Machine, decode, require, signed, CONDITIONAL, MASK

HERE = Path(__file__).resolve().parent
DATA, STATUS, OUT, SCRATCH = 0x300000, 0x310000, 0x320000, 0x500000


class DC(Machine):
    def __init__(self, chip, evidence):
        self.chip, self.e = chip, evidence
        self.program, _ = decode(evidence)
        self.entries = {i: int(f['address'], 0) for i, f in enumerate(evidence['functions'])}
        self.kinds = {v: k for k, v in self.entries.items()}
        self.table = int(evidence['symbols']['g_phyFuns']['address'], 0)
        self.param = int(evidence['symbols']['phy_param']['address'], 0)
        self.gate_offsets = (842, 844) if chip == 'esp32c3' else (736, 730)

    def put(self, a, width, value):
        for i in range(width):
            self.mem[a + i] = (value >> (8 * i)) & 255

    def get(self, a, width):
        if 0x70000000 <= a < 0x71000000:
            require(width == 4 and a % 4 == 0, 'Invalid callback table read')
            return a + 0x1000000
        require(all(a + i in self.mem for i in range(width)), f'Uninitialized {a:x}/{width}')
        return sum(self.mem[a + i] << (8 * i) for i in range(width))

    def canonical(self, a):
        if a in self.locals:
            return self.locals[a]
        if self.table <= a < self.table + 4:
            return 0x220000 + a - self.table
        if self.param <= a < self.param + 1024:
            return 0x230000 + a - self.param
        return a

    def observed(self, a):
        a = self.canonical(a)
        return (0x220000 <= a < 0x230400 or DATA <= a < DATA + 168
                or STATUS <= a < STATUS + 42 or OUT <= a < OUT + 12
                or SCRATCH <= a < SCRATCH + 12 or 0x70000000 <= a < 0x71000000)

    def read(self, a, width):
        value = self.get(a, width)
        if self.observed(a):
            self.trace.append(['read', self.canonical(a), width, value])
        else:
            require(0x100000 <= a < 0x110000, f'Unmapped read {a:x}')
        return value

    def write(self, a, width, value):
        value &= (1 << (width * 8)) - 1
        if self.observed(a):
            self.trace.append(['write', self.canonical(a), width, value])
        else:
            require(0x100000 <= a < 0x110000, f'Unmapped write {a:x}')
        self.put(a, width, value)

    def enter(self, kind, sp):
        if kind == 0:
            self.scratch = sp + (4 if self.chip == 'esp32c3' else 0)
            self.locals.update({self.scratch + i: SCRATCH + i for i in range(12)})

    def callback(self, target, args, kind):
        index = self.calls
        self.calls += 1
        offset = (0x10c if kind == 0 else 0x100) if self.chip == 'esp32c3' else (0xf8 if kind == 0 else 0xec)
        require(0x71000000 <= target < 0x72000000 and (target - 0x71000000) % 0x1000 == offset,
                'Unexpected callback target')
        self.trace.append(['call', target, *[self.canonical(v) if i == 2 else v & MASK for i, v in enumerate(args)]])
        if kind == 0:
            require(args[:2] == [1, self.c['sample_count'] & (65535 if self.chip == 'esp32s3' else MASK)],
                    'Estimator arguments changed')
            require(index < 8, 'Too many estimates')
            for i, value in enumerate(self.c['samples'][index]):
                self.write(args[2] + i * 4, 4, value)
            gate, selector = self.c['gates'][index]
            self.write(self.param + self.gate_offsets[0], 2, gate)
            self.write(self.param + self.gate_offsets[1], 1, selector)
            result = 0
        else:
            mode = self.c['abs_mode']
            result = abs(signed(args[0])) if mode == 'abs' else mode & MASK
            if self.c.get('mutate'):
                self.write(self.status + ((index * 7 + 5) % self.cells), 1, index % 3)
                a = DATA + ((index * 11 + 2) % self.cells) * 4
                self.write(a, 4, self.get(a, 4) ^ (0x12345678 + index))
        if self.c['table_mutation']:
            self.write(self.table, 4, 0x70000000 + self.calls * 0x1000)
        self.trace.append(['return', result & MASK])
        return result

    def dispatch(self, target, values, registers, depth):
        return self.callback(target, values(3 if self.c['kind'] == 0 else 1), self.c['kind'])

    def init(self, c):
        self.c = c
        self.mem, self.locals, self.trace = {}, {}, []
        self.steps = self.calls = 0
        self.visited, self.branches = set(), set()
        self.cells = 42 if self.chip == 'esp32c3' else 14
        self.status = DATA if c.get('status_alias') else STATUS
        for a, size in [(self.param, 1024), (DATA, 168), (STATUS, 42), (OUT, 12)]:
            for i in range(size):
                self.put(a + i, 1, 0xa5 if a == OUT else 0)
        self.put(self.table, 4, 0x70000000)
        for i, v in enumerate(c.get('data', [])):
            self.put(DATA + i * 4, 4, v)
        for i, v in enumerate(c.get('status', [])):
            self.put(self.status + i, 1, v)
        self.out = self.param + (self.gate_offsets[0] & ~3) if c.get('output_alias') else OUT

    def run(self, c, model=False, reset_columns=False, full_abs=False):
        self.init(c)
        if model:
            self.enter(c['kind'], 0x10fe00)
            self.reference(reset_columns, full_abs)
        else:
            r = self.registers()
            args = [c['sample_count'], c['unused'], self.out] if c['kind'] == 0 else [DATA, self.status]
            for i, v in enumerate(args):
                r[f'a{i + (2 if self.chip == "esp32s3" else 0)}'] = v & MASK
            self.execute(self.entries[c['kind']], r, c['kind'])
        return self.trace

    def reference(self, reset_columns, full_abs):
        c = self.c
        if c['kind'] == 0:
            best = 100
            for i in range(8):
                table = self.read(self.table, 4)
                offset = 0x10c if self.chip == 'esp32c3' else 0xf8
                target = self.read(table + offset, 4)
                self.callback(target, [1, c['sample_count'] & (65535 if self.chip == 'esp32s3' else MASK), self.scratch], 0)
                score = signed(self.read(self.scratch + 8, 4))
                if score < best and (self.read(self.param + self.gate_offsets[0], 2) == 0
                                     or self.read(self.param + self.gate_offsets[1], 1) == 1):
                    first = self.read(self.scratch, 4)
                    self.write(self.out + 8, 4, score)
                    best = score
                    self.write(self.out, 4, first)
                    self.write(self.out + 4, 4, self.read(self.scratch + 4, 4))
                if best <= 35 or (best <= 47 and i >= 2):
                    return
            for offset, value in [(8, 56), (0, 0), (4, 0)]:
                self.write(self.out + offset, 4, value)
            return
        columns = 3 if self.chip == 'esp32c3' else 1
        preference = 0
        for col in range(columns):
            count = 0 if reset_columns else preference
            for i in range(14):
                if self.read(self.status + i * columns + col, 1) == 1:
                    count = (count + 1) & 255
            preference = 1 if count else 2
            for i in range(14):
                if self.read(self.status + i * columns + col, 1) == 1:
                    continue
                selected, distance = i, 20
                for j in range(14):
                    if self.read(self.status + j * columns + col, 1) != preference:
                        continue
                    table = self.read(self.table, 4)
                    target = self.read(table + (0x100 if self.chip == 'esp32c3' else 0xec), 4)
                    value = self.callback(target, [(i - j) & MASK], 1)
                    value = signed(value, 32 if full_abs else 8)
                    if value < distance:
                        selected, distance = j, value
                value = self.read(DATA + (selected * columns + col) * 4, 4)
                self.write(DATA + (i * columns + col) * 4, 4, value & 0xffff01ff)


def cases(chip):
    rng = random.Random(0x44435345)
    scores = [-0x80000000, -1, 0, 34, 35, 36, 46, 47, 48, 55, 56, 99, 100, 101, 0x7fffffff]
    for score in scores:
        for gate, selector in [(0, 0), (1, 0), (1, 1), (65535, 2), (65536, 257)]:
            for at in range(8):
                seq = [101] * 8
                seq[at] = score
                yield {'kind': 0, 'sample_count': 0x12348001, 'unused': MASK,
                       'samples': [[i + 1, 0x12340000 + i, v & MASK] for i, v in enumerate(seq)],
                       'gates': [[gate, selector]] * 8, 'table_mutation': True}
    for i in range(256):
        yield {'kind': 0, 'sample_count': rng.getrandbits(32), 'unused': rng.getrandbits(32),
               'samples': [[rng.getrandbits(32), rng.getrandbits(32), rng.choice(scores) & MASK] for _ in range(8)],
               'gates': [[rng.choice([0, 1, 65535]), rng.choice([0, 1, 2, 255])] for _ in range(8)],
               'output_alias': bool(i % 2), 'table_mutation': bool(i % 3)}
    cells = 42 if chip == 'esp32c3' else 14
    statuses = [[v] * cells for v in [0, 1, 2, 255]]
    for source in range(cells):
        for status in [1, 2]:
            row = [0] * cells
            row[source] = status
            statuses.append(row)
    statuses += [[rng.choice([0, 1, 2, 255]) for _ in range(cells)] for _ in range(128)]
    for i, status in enumerate(statuses):
        for mode in ['abs', 20, 127, 128, 255, 256, -0x80000000]:
            yield {'kind': 1, 'status': status, 'data': [rng.getrandbits(32) for _ in range(cells)],
                   'abs_mode': mode, 'table_mutation': bool(i % 3), 'mutate': bool(i % 4 == 3),
                   'status_alias': bool(i % 8 == 7)}


def main():
    manifest = json.loads((HERE / 'manifest.json').read_text())
    for name, sha in manifest['tool_sha256'].items():
        require(hashlib.sha256((HERE / name).read_bytes()).hexdigest() == sha, 'Pinned engine changed')
    result = {'preparation_only': True, 'production_replacement_tested': False, 'chips': {}}
    for chip in ['esp32c3', 'esp32s3']:
        fixture = HERE / (chip + '-instructions.json')
        require(hashlib.sha256(fixture.read_bytes()).hexdigest() == manifest['chips'][chip]['instructions_sha256'], 'Pinned instructions changed')
        evidence = json.loads(fixture.read_text())
        a, b = DC(chip, evidence), DC(chip, evidence)
        visited, branches = set(), set()
        digest = hashlib.sha256()
        count = 0
        for c in cases(chip):
            original, contract = a.run(c), b.run(c, model=True)
            if original != contract:
                (HERE / 'failure.json').write_text(json.dumps({'chip': chip, 'case': c, 'original': original, 'contract': contract}, indent=2))
                raise ValueError(f'{chip} contract mismatch case {count}')
            visited |= a.visited
            branches |= a.branches
            digest.update(json.dumps([c, original], separators=(',', ':')).encode())
            count += 1
        edges = {(pc, v) for pc, (_, op, _) in a.program.items() if op in CONDITIONAL for v in (False, True)}
        require(visited == set(a.program), 'Uncovered original instruction')
        require(branches == edges, 'Uncovered original conditional edge')
        result['chips'][chip] = {'cases': count, 'ordered_trace_sha256': digest.hexdigest(),
                                'instructions': len(a.program), 'covered_instructions': len(visited),
                                'conditional_edges': len(edges), 'covered_conditional_edges': len(branches),
                                'uncovered_pcs': [hex(v) for v in sorted(set(a.program) - visited)],
                                'uncovered_edges': [[hex(pc), v] for pc, v in sorted(edges - branches)]}
        print(chip, result['chips'][chip], flush=True)
        if chip == 'esp32c3':
            c = {'kind': 1, 'status': [2, 2, 2] + [0] * 39, 'data': [0x12340000 + i for i in range(42)],
                 'abs_mode': 'abs', 'table_mutation': True}
            expected = a.run(c)
            wrong = b.run(c, model=True, reset_columns=True)
            require(expected != wrong, 'Resetting each C3 column must change this contract')
            actual_words = [a.get(DATA + i * 4, 4) for i in range(6)]
            wrong_words = [b.get(DATA + i * 4, 4) for i in range(6)]
            require(actual_words != wrong_words, 'C3 column-carry probe needs visible output differences')
            result['c3_column_reset_counterexample'] = {'case': c, 'original_first_two_rows': actual_words,
                                                       'incorrect_reset_first_two_rows': wrong_words}
        c = {'kind': 1, 'status': [2] + [0] * ((42 if chip == 'esp32c3' else 14) - 1),
             'data': [0x56780000 + i for i in range(42 if chip == 'esp32c3' else 14)],
             'abs_mode': 256, 'table_mutation': True}
        require(a.run(c) != b.run(c, model=True, full_abs=True), 'Signed-byte callback narrowing must be observable')
    expected = HERE / 'expected-results.json'
    if expected.exists():
        require(result == json.loads(expected.read_text()), 'Contract digest or coverage changed')
    result['contract_script_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    print('Reference contract digests and coverage match the pinned expectations.', flush=True)


if __name__ == '__main__':
    main()
