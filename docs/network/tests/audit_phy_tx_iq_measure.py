"""Check TX IQ measurement ownership after every earlier source gate."""
import argparse
import json
from pathlib import Path
import audit_phy_tx_detector as previous

SELECTED = previous.TX_IQ_SELECTED
RETAINED = tuple(name for name in previous.RETAINED if name not in SELECTED)


def audit(elf_path, map_path, label, expected, *, expected_wrappers='vendor'):
    prior = previous.audit(elf_path, map_path, label, 'source', expected_iq=expected, expected_wrappers=expected_wrappers)
    return {**prior, 'schema': 'phy-tx-iq-measure-allocation-audit-v1',
            'previous_source_gates': {**prior['previous_source_gates'], 'tx_detector': True}}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--elf', type=Path, required=True)
    p.add_argument('--map', type=Path, required=True)
    p.add_argument('--label', required=True)
    p.add_argument('--expect-iq', choices=['source', 'vendor'], required=True)
    a = p.parse_args()
    print(json.dumps(audit(a.elf, a.map, a.label, a.expect_iq), indent=2))
