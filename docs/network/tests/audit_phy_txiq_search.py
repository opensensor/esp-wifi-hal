"""Check TX IQ search ownership after every earlier source gate."""
import argparse
import json
from pathlib import Path
import audit_phy_txiq_wrappers as previous
import audit_phy_tx_detector as detector

SELECTED = detector.TX_IQ_SEARCH_SELECTED
RETAINED = tuple(name for name in previous.RETAINED if name not in SELECTED)


def audit(elf_path, map_path, label, expected):
    prior = previous.audit(elf_path, map_path, label, 'source', expected_search=expected)
    return {**prior, 'schema': 'phy-txiq-search-allocation-audit-v1',
            'previous_source_gates': {**prior['previous_source_gates'], 'txiq_wrappers': True}}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--elf', type=Path, required=True)
    p.add_argument('--map', type=Path, required=True)
    p.add_argument('--label', required=True)
    p.add_argument('--expect-search', choices=['source', 'vendor'], required=True)
    a = p.parse_args()
    print(json.dumps(audit(a.elf, a.map, a.label, a.expect_search), indent=2))
