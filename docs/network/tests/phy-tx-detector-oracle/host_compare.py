from pathlib import Path
import hashlib, json, subprocess, tempfile
import verify

ROOT = Path(__file__).resolve().parent
TEMP = tempfile.TemporaryDirectory()
OUT = Path(TEMP.name)
cases = list(verify.cases())
text = ''.join(' '.join(map(str, [c['operation'], c['code'], c['flags'], c['register'], *c['returns'], *sum(c['effects'], [])])) + '\n' for c in cases)
records = []
for optimization in (0, 2):
    binary = OUT / ('host-o' + str(optimization))
    subprocess.run(['rustc', '--edition=2021', '-C', 'opt-level=' + str(optimization), '--cfg', 'test', str(ROOT.parent / 'phy_tx_detector.rs'), '-o', str(binary)], check=True)
    for chip in ('esp32c3', 'esp32s3'):
        evidence = json.loads((ROOT / (chip + '-instructions.json')).read_text())
        result = subprocess.check_output([str(binary), chip], input=text, text=True)
        rows = [json.loads(line) for line in result.splitlines()]
        verify.machine.require(len(rows) == len(cases), 'Wrong result count')
        for index, (case, row) in enumerate(zip(cases, rows)):
            original = verify.Original(chip, evidence, case)
            original.run()
            verify.machine.require(row == [original.trace, original.final()], (chip, optimization, index))
        records.append(dict(chip=chip, optimization=optimization, cases=len(rows),
                            stdout_sha256=hashlib.sha256(result.encode()).hexdigest(), matches=True))
TEMP.cleanup()
print(records)
