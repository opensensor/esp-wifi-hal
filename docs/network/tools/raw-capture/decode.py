"""Decode CRC-protected C3 capture records; raw captures contain private data."""
from pathlib import Path
import argparse
import json
import os
import struct
import zlib

MAGIC = b'RWCAP3\r\n'
HEADER = struct.Struct('<8sHBBIQ')
COUNTERS = ['seen', 'selected', 'enqueued', 'queue_dropped', 'oversize',
            'status_dropped', 'bad_commands', 'generation', 'bssid_set', 'station_set', 'running']

class Decoder:
    def __init__(self):
        self.buffer = bytearray()
        self.stats = dict(records=0, frames=0, prefix_bytes=0, corrupt_bytes=0,
                          crc_errors=0, sequence_gaps=0, sequence_regressions=0,
                          records_after_end=0)
        self.last_sequence = None
        self.final = None

    def discard(self, length):
        self.stats['prefix_bytes' if self.last_sequence is None else 'corrupt_bytes'] += length
        del self.buffer[:length]

    def feed(self, data):
        self.buffer.extend(data)
        while True:
            offset = self.buffer.find(MAGIC)
            if offset < 0:
                self.discard(max(0, len(self.buffer)-len(MAGIC)+1))
                return
            self.discard(offset)
            if len(self.buffer) < HEADER.size:
                return
            _, length, kind, version, sequence, micros = HEADER.unpack_from(self.buffer)
            if length > 1604 or kind not in (1, 2, 3, 4) or version != 1:
                self.discard(1)
                continue
            end = HEADER.size + length
            if len(self.buffer) < end + 4:
                return
            if zlib.crc32(self.buffer[:end]) != struct.unpack_from('<I', self.buffer, end)[0]:
                self.stats['crc_errors'] += 1
                self.discard(1)
                continue
            payload = bytes(self.buffer[HEADER.size:end])
            del self.buffer[:end+4]
            if self.last_sequence is not None:
                gap = (sequence-self.last_sequence-1) & 0xffffffff
                if gap > 0x7fffffff:
                    self.stats['sequence_regressions'] += 1
                else:
                    self.stats['sequence_gaps'] += gap
            else:
                self.stats['sequence_gaps'] += sequence
            self.last_sequence = sequence
            self.stats['records'] += 1
            if self.final is not None:
                self.stats['records_after_end'] += 1
            if kind == 1:
                self.stats['frames'] += 1
            elif kind == 3:
                self.final = counters(payload)
            yield kind, sequence, micros, payload

def counters(payload):
    if len(payload) != 4*len(COUNTERS):
        raise ValueError('Invalid counter record length')
    return dict(zip(COUNTERS, struct.unpack('<'+'I'*len(COUNTERS), payload)))

def radiotap(payload):
    if len(payload) < 52:
        raise ValueError('Missing DMA metadata')
    length, channel = struct.unpack_from('<HB', payload)
    raw = payload[4:]
    if length < 24 or length > len(raw)-48 or not 1 <= channel <= 14:
        raise ValueError('Invalid MPDU bounds or channel')
    freq = 2484 if channel == 14 else 2407 + 5*channel
    # Flags (no FCS), channel and RSSI. Timestamps are host-readable MCU delivery
    # time; the original 48-byte metadata remains in the raw record archive.
    header = struct.pack('<BBHIBxHHb', 0, 0, 15, 0x2a, 0, freq, 0x80, struct.unpack('b', raw[:1])[0])
    assert len(header) == 15
    return header + raw[48:48+length]

def pcap_header():
    return struct.pack('<IHHIIII', 0xa1b2c3d4, 2, 4, 0, 0, 4096, 127)

def write_frame(stream, micros, frame):
    stream.write(struct.pack('<IIII', micros//1000000, micros%1000000, len(frame), len(frame)))
    stream.write(frame)

def validate(decoder):
    final = decoder.final
    return bool(final and not final['running'] and final['enqueued'] == decoder.stats['frames']
        and final['selected'] == final['enqueued'] and final['seen'] >= final['selected']
        and not any(final[k] for k in ['queue_dropped', 'oversize', 'status_dropped', 'bad_commands'])
        and not any(decoder.stats[k] for k in ['corrupt_bytes', 'crc_errors', 'sequence_gaps', 'sequence_regressions', 'records_after_end'])
        and not decoder.buffer)

def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('raw', type=Path); parser.add_argument('pcap', type=Path)
    parser.add_argument('--summary', type=Path, required=True)
    args = parser.parse_args(); os.umask(0o077)
    decoder = Decoder()
    with args.raw.open('rb') as source, args.pcap.open('xb') as out:
        out.write(pcap_header())
        while data := source.read(65536):
            for kind, _, micros, payload in decoder.feed(data):
                if kind == 1:
                    write_frame(out, micros, radiotap(payload))
    summary = dict(decoder.stats, final=decoder.final, transport_complete=validate(decoder),
                   trailing_bytes=len(decoder.buffer),
                   limitation='Transport validity does not prove RF, DMA or hardware-filter capture coverage.')
    args.summary.write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps(summary))
    return 0 if summary['transport_complete'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
