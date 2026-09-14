# C3/S3 transmit-gain programming

Rust replaces all 11 C3 and 12 S3 live functions in `phy_tx_gain.o`. The entry
names remain link aliases to real Rust bodies.

| Rust suffix | C3 original | S3 original |
|---|---|---|
| `digital` | `rom1_wifi_tx_dig_gain` | `ram_wifi_tx_dig_gain` |
| `interpolate` | `bt_chan_pwr_interp` | `bt_chan_pwr_interp` |
| `fcc` | `rom1_get_rate_fcc_index` | `ram_get_rate_fcc_index` |
| `limits` | `rom1_get_chan_target_power` | `ram_get_chan_target_power` |
| `lookup` | `rom2_get_tx_gain_value1` | `get_tx_gain_value` |
| `bt_get` | `rom1_bt_get_tx_gain_new` | `ram_bt_get_tx_gain` |
| `wifi_get` | `rom1_wifi_get_tx_gain` | `ram_wifi_get_tx_gain` |
| `wifi_set` | `ram1_wifi_set_tx_gain` | `ram_wifi_set_tx_gain` |
| `bt_set` | `rom1_bt_set_tx_gain` | `ram_bt_set_tx_gain` |
| `bt_initialize` | `bt_tx_gain_init` | `bt_tx_gain_init` |
| `calibration_tables` | `txcal_gain_check` | `tx_gain_set` |
| `dig_check` | — | `dig_gain_check` |

Rust entry names use the `__opensensor_tx_gain_` prefix. The digital-gain entry
remains in IRAM on both chips; the S3 Bluetooth setter also remains in IRAM.

The implementation preserves ordered volatile accesses, callback reloads,
signed byte/halfword narrowing, wrapping arithmetic, lookup iteration state,
logging arguments and existing calibration boundaries. C3 reloads interpolation
for every Wi-Fi entry; S3 calls its basic interpolator once and carries a lookup
index through the table. C3 clamps FCC limits to 82; S3 uses 100. The setters
retain their different disabled-path read order and digital-gain bounds.

C3 calibration rereads reference thresholds every iteration, including the
iteration that overwrites the reference itself. S3 selects and caches its
reference once. Combining these paths would change the generated gain tables.

The callback installer remains unchanged. C3 always patches FCC slot `0x128`;
the Wi-Fi/BT gain patches retain their nonzero-ROM-version condition. S3 patches
its Wi-Fi/BT setters and generators unconditionally after acquiring the ROM
table. Existing ROM-version-zero behavior and ROM callbacks remain dependencies.

No additional Bluetooth calibration, power policy, retries or timing adjustment
is introduced. The lifetime probe records entry addresses, callback bindings and
post-init table fingerprints without invoking gain/calibration routines.

Run `sh docs/network/tests/run-phy-tx-gain.sh` for the independent instruction
oracle and production Rust tests at O0/O2. The [oracle documentation](tests/phy-tx-gain-oracle/README.md)
describes coverage, input domains and the unused internal argument.

`audit_phy_tx_gain.py` composes all earlier ownership checks, requires the real
Rust bodies and aliases, and rejects remaining member allocations, strings or
overlap with vendor inputs. An explicit transition permits the C3 feature stage
to use the checked Rust Wi-Fi setter; earlier audit defaults still require the
vendor setter. Initialization, RX/TX calibration and ROM dependencies remain.

Native instruction and board validation are recorded separately. These checks
do not establish RF equivalence or solve the existing latency/loss observations.
