# Preserve an MPDU's identity on retransmission

The async driver retried MAC failures without setting the IEEE 802.11 Retry
flag. If a peer received a frame but its ACK was lost, a subsequent attempt
could therefore look like another original frame. A peer's duplicate filter
needs the Retry flag together with the retained sequence control value to
suppress that second delivery.

The correction restores the historical software behavior in
`AsyncTransmitExt::transmit_with_retry`: after a `TxError::MacProtocol` result,
set bit 3 of the second frame-control byte for subsequent attempts. Initial
`TxError::ChannelAccess` failures do not set it: the driver's documented
contract says nothing has been transmitted at that point. A later channel
failure does not clear a flag already set by a MAC failure.

Frame preparation still runs once, before the retry loop. Sequence control,
CCMP packet number, other frame bytes, retry limits, ACK policy and rate
fallback remain unchanged. The existing final Retry clear remains in place
on normal return. This does not add cancellation cleanup if the future is
dropped during an awaited retry. Raw callers can still supply an initially
set Retry flag; this patch does not clear it before the first attempt.

## History and protocol evidence

- [4d37bbeacc112cf26edca2e795a1e03c98894cf5](https://github.com/opensensor/esp-wifi-hal/commit/4d37bbeacc112cf26edca2e795a1e03c98894cf5),
  2025-03-13, added the software Retry set in `wmac.rs`. It distinguished the
  top-level channel timeout/collision cases from the remaining MAC errors.
- [d5a840b41d4922adb50a32c771d9444d86cdedd3](https://github.com/opensensor/esp-wifi-hal/commit/d5a840b41d4922adb50a32c771d9444d86cdedd3),
  2026-02-07, replaced that implementation with `async_driver.rs`. The new
  loop retained the final clear but omitted the set after a MAC failure.
- Linux's [non-QoS unicast duplicate check](https://github.com/torvalds/linux/blob/v6.12/net/mac80211/rx.c)
  in `ieee80211_rx_h_check_dup` tests Retry plus the last sequence-control
  value. The host regression models this bounded case; it does not emulate
  every AP, QoS reordering, or hardware cryptography.
- The inspected [ESP-IDF WPA supplicant implementation](https://github.com/espressif/esp-idf/blob/67c1de1eebe095d554d281952fde63c16ee2dca0/components/wpa_supplicant/src/crypto/ccmp.c),
  `ccmp_aad_nonce`, masks
  `WLAN_FC_RETRY` out of CCMP additional authenticated data. Setting Retry does
  not change those authentication bytes. The patch preserves the sequence
  and packet number of the same MPDU; it does not generate a new nonce or
  reserialize EAPOL.

All current MAC error variants follow the existing historical policy,
including CTS and RTS failures, invalid key ID and unknown errors. This is a
restoration of that policy, not a change to error classification.

## Reproducible host regression

Run from the repository root with stable Rust installed:

```sh
sh docs/network/tests/run-mac-retry.sh
sh docs/network/tests/run-mac-retry.sh --release
```

The harness's build script extracts the **actual production retry method**,
its parameter/error definitions and rate iterator with `syn`. It includes
the actual EDCA contention implementation. Only the preparation, DMA/radio,
PHY-rate representation and RNG boundaries are replaced for host execution.
The fake radio yields before completing each attempt and records the frame
bytes presented to it. Missing or ambiguous production definitions fail the
build rather than falling back to a copied loop.

The 11 cases cover lost-ACK duplicate suppression, channel failures before
and after MAC failures, all current MAC error classes, fresh frame reuse,
retry exhaustion, drop policy, rate fallback, an initially set raw-caller
flag and short-buffer bounds. Assertions preserve every byte other than
Retry, including sequence control and the packet number. Short-buffer tests
deliberately bypass normal frame validation to exercise the retry method's
`get_mut` guards; they do not claim that malformed frames can be transmitted.

All 11 pass in debug and release. Running the same harness against the
unchanged source at `a165b04eb64a4dc4d76d10111d1c757b0a2e7cb8` produces seven
failures. The lost-ACK case specifically observes two peer deliveries where
one is required. CI runs both corrected configurations.

## Device evidence and remaining limits

Before this change, the S3 sequence-assignment validation recorded one
duplicate host reply with exactly one request and one reply at the embassy
boundary: queue generation 13, assigned sequence 13, completion `Ok(1)`.
That supports testing retry duplicate handling below IP. It does not prove
the transmitted Retry bit's value without an on-air capture.

The same run's six missing gateway replies corresponded to request
generations 133, 239, 291, 345, 381 and 493, all `Ok(0)`. Those losses are
separate evidence and are not explained by changing a flag on a subsequent
attempt. A later repeat also saw a missing reply after `Ok(2)`; completion
success alone does not establish peer delivery to IP. This patch does not
change periodic PHY power-control cadence, ordering, receive processing or
RF configuration.

The C3 and S3 `sta_smoke` release builds link with `foa-smoke` and
`foa/tx-trace`, using compile-only dummy credentials. The S3 link retains the
existing RWX LOAD-segment warning. These builds and host tests are
preparation for a dedicated device check.
Hardware validation of this patch is pending. Compare original versus
retransmitted sequence/Retry values with a monitor capture when available,
and retain host/gateway loss and duplicate counts separately. A clean ping
run alone does not prove that the retransmission contract is correct.
