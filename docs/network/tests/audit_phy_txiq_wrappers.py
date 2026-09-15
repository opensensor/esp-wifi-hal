"""Check TX IQ wrapper ownership after all earlier source gates."""
import argparse
import json
from pathlib import Path
import audit_phy_tx_iq_measure as previous

SELECTED = previous.previous.TX_IQ_WRAPPER_SELECTED
RETAINED = tuple(name for name in previous.RETAINED if name not in SELECTED)


def audit(elf_path, map_path, label, expected):
    prior = previous.audit(elf_path, map_path, label, 'source', expected_wrappers=expected)
    return {**prior, 'schema': 'phy-txiq-wrappers-allocation-audit-v1',
            'previous_source_gates': {**prior['previous_source_gates'], 'tx_iq_measure': True}}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--elf', type=Path, required=True)
    p.add_argument('--map', type=Path, required=True)
    p.add_argument('--label', required=True)
    p.add_argument('--expect-wrappers', choices=['source', 'vendor'], required=True)
    a = p.parse_args()
    print(json.dumps(audit(a.elf, a.map, a.label, a.expect_wrappers), indent=2))
