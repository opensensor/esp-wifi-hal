import copy, hashlib, json, unittest
import verify
import machine


class ContractTests(unittest.TestCase):
    def run_case(self, chip, operation=0, code=0, flags=0):
        case = copy.deepcopy(next(verify.cases()))
        case.update(operation=operation, code=code, flags=flags)
        evidence = json.loads((verify.ROOT / (chip + '-instructions.json')).read_text())
        original = verify.Original(chip, evidence, case)
        original.run()
        model = verify.Boundary(chip, evidence, case)
        verify.model(model)
        self.assertEqual(original.trace, model.trace)
        self.assertEqual(original.final(), model.final())
        return original

    def test_code_narrows_before_six_argument_tone(self):
        for chip in ('esp32c3', 'esp32s3'):
            for code in (0x100, 0x10001, 0x80000080, 0xffffffff):
                trial = self.run_case(chip, code=code)
                self.assertEqual(trial.trace[0], ['helper', 'start_tx_tone_step', [1, 128, code & 255, 0, 0, 0]])

    def test_cached_calibration_reads_only_flags(self):
        for chip in ('esp32c3', 'esp32s3'):
            trial = self.run_case(chip, 1, flags=0x81234567)
            self.assertEqual(trial.trace, [['read', 4, ['param', 0x120], 0x81234567]])

    def test_other_flags_do_not_skip(self):
        for chip in ('esp32c3', 'esp32s3'):
            trial = self.run_case(chip, 1, flags=0xfeffffff)
            self.assertEqual(trial.calls, 5)

    def test_chip_specific_calibration_tone(self):
        for chip, code in (('esp32c3', 120), ('esp32s3', 80)):
            trial = self.run_case(chip, 1)
            self.assertIn(['helper', 'start_tx_tone_step', [1, 128, code, 0, 0, 0]], trial.trace)

    def test_flag_update_uses_post_work_mode_state(self):
        for chip in ('esp32c3', 'esp32s3'):
            trial = self.run_case(chip, 1)
            changed = trial.case['effects'][4][1]
            self.assertEqual(trial.trace[-2:], [['read', 4, ['param', 0x120], changed], ['write', 4, ['param', 0x120], changed | (1 << 24)]])

    def test_sample_results_narrow_to_halfwords(self):
        for chip in ('esp32c3', 'esp32s3'):
            trial = self.run_case(chip, code=6)
            writes = [e for e in trial.trace if e[:2] == ['write', 2]]
            self.assertEqual([e[-1] for e in writes], [v & 65535 for v in trial.case['returns'][1:3]])

    def test_second_sample_read_store_order_is_chip_specific(self):
        for chip in ('esp32c3', 'esp32s3'):
            trial = self.run_case(chip)
            write = next(i for i, e in enumerate(trial.trace) if e[:3] == ['write', 2, ['param', 220]])
            read = max(i for i, e in enumerate(trial.trace) if e[:3] == ['read', 4, ['register', verify.REG]])
            self.assertEqual(write < read, chip == 'esp32s3')

    def test_register_high_half_reloaded_after_helpers(self):
        for chip in ('esp32c3', 'esp32s3'):
            trial = self.run_case(chip)
            writes = [e[-1] for e in trial.trace if e[:3] == ['write', 4, ['register', verify.REG]]]
            self.assertEqual(writes, [(trial.case['effects'][i][0] & 0xffff0000) | low for i, low in enumerate((0, 0x5555, 0xaaaa))])

    def test_reference_leaves_tone_running_and_final_pattern(self):
        for chip in ('esp32c3', 'esp32s3'):
            trial = self.run_case(chip)
            self.assertEqual([e[1] for e in trial.trace if e[0] == 'helper'], ['start_tx_tone_step', 'get_tone_sar_dout', 'get_tone_sar_dout'])
            self.assertEqual(trial.final()[0] & 65535, 0xaaaa)

    def outlined_evidence(self):
        evidence = json.loads((verify.ROOT / 'esp32s3-instructions.json').read_text())
        address = 0x42090000
        raw = bytes.fromhex('1df0')
        evidence['functions'].append(dict(name='declared_reference', address=hex(address), size_bytes=2,
            body_sha256=hashlib.sha256(raw).hexdigest(), code_hex=raw.hex(), instructions=['42090000: f01d retw.n']))
        evidence['internal_reference_helpers'] = [address]
        return evidence

    def test_undeclared_outlined_native_body_is_rejected(self):
        evidence = self.outlined_evidence()
        evidence.pop('internal_reference_helpers')
        with self.assertRaisesRegex(ValueError, 'Unexpected function count'):
            machine.decode(evidence)

    def test_mismatched_outlined_body_address_is_rejected(self):
        evidence = self.outlined_evidence()
        evidence['internal_reference_helpers'][0] += 3
        with self.assertRaisesRegex(ValueError, 'Unexpected internal reference bodies'):
            machine.decode(evidence)


if __name__ == '__main__':
    unittest.main()
