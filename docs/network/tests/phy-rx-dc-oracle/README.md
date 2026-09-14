# RX DC instruction oracle

The two per-chip instruction files contain exact original bodies and literal
values from the ACK-enabled baseline images. manifest.json and per-chip baseline
files pin the ELF/map and extraction hashes. The tests do not require private
firmware. Re-extraction uses extract.extract with the corresponding private
ELF, GNU objdump and pinned baseline. It verifies bytes, function bounds and
reachable PCs; the fixture decoder independently checks bytes and control flow.

verify_contract.py compares the original instructions with a reference model.
Its preparation_only/production_replacement_tested fields describe this
reference-model check, not the separate Rust harness. generate.py serializes
the original traces into 133-word cases and eight-word events for phy_rx_dc.rs,
which imports the actual production module. Callback and memory boundaries are
synthetic, not an emulation of the analog estimator or RF medium.

The C3 column-reset counterexample and signed-byte callback negative controls
must continue to fail the deliberately incorrect models. Full original PC and
conditional-edge coverage is required and trace digests are pinned. Future
corpus changes must update expectations with an explicit review of the changes.
