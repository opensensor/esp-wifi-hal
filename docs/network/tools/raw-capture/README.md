# C3 raw capture over native USB

`examples/src/bin/raw_capture.rs` receives management/data frames on one
2.4-GHz channel and streams selected DMA buffers through asynchronous USB
Serial/JTAG. It does not associate, install keys, call the radio transmit API,
or install the observed station's address in a hardware filter. Control
frames, including ACKs, are excluded. This is a separate receiver for examining
an S3 station; the production station firmware is unchanged.

The example explicitly disables unicast/multicast blocking and BSSID checking
on interface 0. `ScanningMode::ManagementAndData` alone received beacons but
none of the selected station traffic in the initial paired trial. All address
filter banks remain disabled; selection happens in software.

## Build and record

With the repository's Espressif toolchains installed, build from `examples`:

```sh
CHANNEL=3 ESP_LOG=off cargo +esp build --release --locked \
  --target riscv32imc-unknown-none-elf --features esp32c3 --bin raw_capture
```

The channel must match the observed AP. Logging must be off because the framed
stream owns native USB. Package the ELF and install it in the board's existing
application slot using that board's security and partition configuration.
The validated C3 uses an existing 1-MiB slot at `0x10000`, with security disabled;
that offset is not a default for other boards. The S3's signed application and
security configuration are separate from the receiver.

Use a Python environment with `pyserial`. Put selectors in a private JSON file
(outside the checkout) rather than embedding site addresses in source:

```json
{"bssid":"02:00:00:00:00:01","station":"02:00:00:00:00:02"}
```

Restart the receiver app, then run from the repository root:

```sh
python3 docs/network/tools/raw-capture/capture.py \
  --port "$C3_USB_PORT" --selector "$PRIVATE_SELECTOR_JSON" \
  --out "$PRIVATE_CAPTURE_DIRECTORY" --seconds 1200
```

The output directory must not already exist. Its `ready` file indicates that
firmware has processed the BSSID and duration commands. It does not assert
station identity or RF coverage. If the station randomizes its MAC, omit
`station` initially and atomically replace the selector file once the current
identity is known. Before that update, the receiver retains only non-beacon,
non-probe-response management and clear EAPOL frames from the selected BSSID.
Encrypted traffic before station selection is deliberately absent. Wait for
`station_set` in `progress.json` before beginning traffic when full coverage
from the first packet is required.

The duration is measured from firmware startup. Touch the output directory's
`stop` file, or press Ctrl-C once, to request a final counter record. A second
Ctrl-C or USB disconnection leaves an incomplete capture. After the bounded
run the receiver stops RX; restart the app for another run.

`stream.bin` preserves original records, `radio.pcap` contains Radiotap/802.11,
and `result.json` records hashes, counters and transport validity. Files are
created with private permissions. Keep raw frames and selectors private.
To repeat the decode without a board:

```sh
python3 docs/network/tools/raw-capture/decode.py "$RAW_STREAM" "$NEW_PCAP" \
  --summary "$NEW_SUMMARY_JSON"
```

For encrypted data, supply Wireshark/TShark with the test network's WPA2 key
through a private profile and capture its handshake. The C3 receives encrypted
frames without knowing the password. The validation compares decrypted echo
source/destination, identifier, sequence and the complete payload against host
and AP captures, deduplicating retries. No key or decrypted capture is included
in this repository.

## Framing and limits

Each record contains a 24-byte little-endian header (`<8sHBBIQ`): magic
`RWCAP3\r\n`, payload length, kind, version 1, sequence, and MCU delivery time
in microseconds. A little-endian IEEE CRC32 follows the payload and covers
header plus payload. Sequence starts at zero. Boot text before the first
record is counted separately; corruption, missing records, records after the
end marker and an incomplete final record invalidate the transport result.

Kinds 1/2/3 are frame/status/end. A frame payload starts with MPDU length
(`u16`), configured channel (`u8`) and a reserved byte, followed by the original
48-byte C3 RX metadata and padded DMA data. Radiotap conversion retains the
MPDU, excludes DMA padding, supplies RSSI and the configured channel, and does
not assert that an FCS is present. PCAP time is MCU delivery time, not UTC or
an RF timestamp; the original metadata remains in `stream.bin`.

Status/end payloads contain eleven `u32` counters: DMA frames seen, selected,
enqueued, queue drops, oversize frames, status drops, bad commands, command
generation, BSSID configured, station configured, and running. Optional
`SNIFFER_DIAG_HEADS=1` emits kind 4 records for the first 32 received headers:
the four-byte prefix followed by at most 72 DMA bytes. These diagnose filtering
without exporting those frames' data payloads and are absent in the final
validation build.

Thirty-two DMA buffers feed a sixteen-record USB queue. The receiver copies
the selected buffer and releases its descriptor before USB transmission.
Queue exhaustion is counted rather than blocking RX on USB. Firmware rejects
oversize records; the decoder refuses incomplete or inconsistent streams.

**Transport validity does not prove RF coverage.** Hardware filtering, DMA
loss, receiver placement, startup selection and missing handshakes can all
hide frames while USB remains perfect. The initial trial demonstrated this:
zero selected frames and zero USB errors. A missing frame on an independent
receiver is not by itself evidence that the AP or station failed to receive it.
The example also does not provide ACK coverage. See
[`RAW-CAPTURE.md`](../../RAW-CAPTURE.md) for measured coverage and limitations.

## Host checks

```sh
rustc --edition 2024 --test examples/src/capture_protocol.rs -o /tmp/capture-tests
/tmp/capture-tests
python3 -m unittest discover -s docs/network/tools/raw-capture -p 'test_*.py'
```
