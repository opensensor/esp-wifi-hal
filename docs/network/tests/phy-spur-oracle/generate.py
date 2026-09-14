"""Generate host replay inputs directly from the pinned original routines."""
import json
import sys
from pathlib import Path
from verify_contract import Spur, cases, check_pins

HERE = Path(__file__).resolve().parent
NAMES = ['slot_1d4', 'slot_50', 'slot_4c', 'slot_40', 'slot_f0', 'slot_f4',
         'slot_104', 'chip_v7_set_chan', 'phy_set_freq', 'start_tx_tone_step', 'phy_printf']


def main():
    check_pins()
    machine = Spur(json.loads((HERE/'esp32s3-instructions.json').read_text()))
    with Path(sys.argv[1]).open('w') as output:
        for case in cases():
            output.write('C ' + ' '.join(map(str, [case['kind'], int(case['table_mutation']), case['logging'], *case['args']])) + '\n')
            for row in machine.run(case):
                kind, *data = row
                if kind == 'call':
                    data[0] = NAMES.index(data[0])
                output.write(dict(read='R', write='W', call='K', **{'return': 'V', 'exception': 'X'})[kind] + ' ' + ' '.join(map(str, data)) + '\n')
            output.write('E\n')


if __name__ == '__main__':
    main()
