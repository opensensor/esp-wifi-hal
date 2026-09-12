"""Record a running C3 raw_capture app over native USB (requires pyserial)."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import time

import serial
from decode import Decoder, counters, pcap_header, radiotap, validate, write_frame


def address(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', value):
        raise ValueError('Expected a six-byte colon-separated address in selector JSON')
    raw = bytes.fromhex(value.replace(':', ''))
    if raw == bytes(6) or raw[0] & 1:
        raise ValueError('Selector must be a nonzero unicast address')
    return raw.hex()


def capture(port_name, selector_path, folder, seconds):
    os.umask(0o077)
    selector = json.loads(selector_path.read_text())
    bssid = address(selector['bssid'])
    station = address(selector['station']) if selector.get('station') else None
    folder.mkdir(mode=0o700)
    decoder = Decoder()
    last_status = None
    error = None
    stopped = False
    start = time.monotonic()
    deadline = start + seconds + 15
    next_selector = start
    raw_path, pcap_path = folder/'stream.bin', folder/'radio.pcap'
    try:
        connection = serial.Serial(port=None, baudrate=115200, timeout=.05)
        connection.dtr = False
        connection.rts = False
        connection.port = port_name
        with connection as port, raw_path.open('xb') as raw, pcap_path.open('xb') as pcap:
            pcap.write(pcap_header())
            command = f'D{seconds}\nB{bssid}\n'
            if station:
                command += f'M{station}\n'
            port.write(command.encode())
            port.flush()
            while time.monotonic() < deadline:
                try:
                    chunk = port.read(16384)
                except KeyboardInterrupt:
                    if stopped:
                        raise
                    port.write(b'S\n')
                    port.flush()
                    stopped = True
                    deadline = time.monotonic() + 10
                    continue
                if chunk:
                    raw.write(chunk)
                    raw.flush()
                    for kind, _, micros, payload in decoder.feed(chunk):
                        if kind == 1:
                            write_frame(pcap, micros, radiotap(payload))
                        elif kind in (2, 3):
                            last_status = counters(payload)
                            progress = dict(transport=decoder.stats, counters=last_status, micros=micros)
                            (folder/'progress.json').write_text(json.dumps(progress)+'\n')
                            if last_status['bssid_set'] and last_status['generation'] >= 2:
                                (folder/'ready').touch(exist_ok=True)
                    pcap.flush()
                if decoder.final is not None:
                    break
                now = time.monotonic()
                if now >= next_selector:
                    # Replace this file atomically when the station's randomized
                    # identity becomes known. BSSID stays fixed for this session.
                    updated = json.loads(selector_path.read_text())
                    if address(updated['bssid']) != bssid:
                        raise ValueError('BSSID changed during capture')
                    new_station = address(updated['station']) if updated.get('station') else None
                    if new_station and new_station != station:
                        port.write(f'M{new_station}\n'.encode())
                        port.flush()
                        station = new_station
                    next_selector = now + .1
                if (folder/'stop').exists() and not stopped:
                    port.write(b'S\n')
                    port.flush()
                    stopped = True
                    deadline = min(deadline, now + 10)
            if decoder.final is None:
                port.write(b'S\n')
    except (Exception, KeyboardInterrupt) as exc:
        # Keep partial data and distinguish it from a completed firmware stream.
        error = type(exc).__name__
    result = dict(transport=decoder.stats, final=decoder.final, last_status=last_status,
                  transport_complete=error is None and validate(decoder), error=error,
                  seconds=round(time.monotonic()-start, 3), trailing_bytes=len(decoder.buffer),
                  limitation='USB completeness does not prove RF/DMA coverage or an 802.11 ACK.')
    for path in [raw_path, pcap_path]:
        if path.exists():
            result[path.stem+'_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    (folder/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result))
    return 0 if result['transport_complete'] else 1


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--selector', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=1200)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 3600:
        parser.error('--seconds must be between 1 and 3600')
    return capture(args.port, args.selector, args.out, args.seconds)


if __name__ == '__main__':
    raise SystemExit(main())
