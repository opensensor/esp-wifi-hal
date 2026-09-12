"""Exercise the serial recorder on a POSIX pseudo-terminal, including interruption."""
import json
import os
from pathlib import Path
import pty
import select
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import zlib

try:
    import serial
except ImportError:
    serial = None

from decode import HEADER, MAGIC


def record(sequence, kind, payload):
    message = HEADER.pack(MAGIC, len(payload), kind, 1, sequence, 123456) + payload
    return message + struct.pack('<I', zlib.crc32(message))


@unittest.skipIf(serial is None, 'pyserial is needed for the optional PTY integration checks')
class SerialRecorderTests(unittest.TestCase):
    def test_complete_frame_and_terminal_counters(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            selector = root/'selector.json'
            selector.write_text(json.dumps({'bssid': '02:00:00:00:00:01'}))
            master, slave = pty.openpty()
            # PTYs have no modem-control ioctl; the recorder should also work
            # with real USB ports that omit these optional controls.
            try:
                proc = subprocess.Popen([sys.executable, str(Path(__file__).with_name('capture.py')),
                    '--port', os.ttyname(slave), '--selector', str(selector), '--out', str(root/'out'),
                    '--seconds', '1'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                commands = b''
                deadline = time.monotonic() + 5
                while b'B020000000001\n' not in commands and time.monotonic() < deadline:
                    if select.select([master], [], [], .1)[0]:
                        commands += os.read(master, 1024)
                    if proc.poll() is not None:
                        break
                self.assertIn(b'B020000000001\n', commands)
                metadata = bytes([211]) + bytes(47)
                mpdu = bytes(range(24))
                payload = struct.pack('<HBB',24,3,0)+metadata+mpdu
                counts = struct.pack('<11I',1,1,1,0,0,0,0,2,1,0,0)
                stream = b'boot text\r\n'+record(0,1,payload)+record(1,3,counts)
                for offset in range(0,len(stream),7):
                    os.write(master,stream[offset:offset+7])
                out, err = proc.communicate(timeout=5)
                self.assertEqual(proc.returncode,0,err.decode()+out.decode())
                result = json.loads((root/'out/result.json').read_text())
                self.assertTrue(result['transport_complete'])
                self.assertEqual(result['transport']['frames'],1)
                self.assertEqual((root/'out/stream.bin').read_bytes(),stream)
                self.assertEqual((root/'out/radio.pcap').stat().st_size,24+16+15+24)
            finally:
                if 'proc' in locals() and proc.poll() is None:
                    proc.kill();proc.communicate()
                os.close(master);os.close(slave)


if __name__ == '__main__':
    unittest.main()
