import struct
import unittest
import zlib
from decode import Decoder, HEADER, MAGIC, radiotap, validate

def record(sequence, kind=2, payload=b'\0'*44):
    message=HEADER.pack(MAGIC,len(payload),kind,1,sequence,123456)+payload
    return message+struct.pack('<I',zlib.crc32(message))

class TransportTests(unittest.TestCase):
    def test_fragmented_stream_noise_and_complete_counters(self):
        d=Decoder();data=b'boot text\r\n'+record(0)+record(1,3)
        messages=[]
        for byte in data:messages.extend(d.feed(bytes([byte])))
        self.assertEqual(len(messages),2)
        self.assertEqual(d.stats['prefix_bytes'],11)
        self.assertTrue(validate(d))

    def test_crc_error_recovers_and_never_passes(self):
        damaged=bytearray(record(1));damaged[30]^=1
        d=Decoder();messages=list(d.feed(record(0)+damaged+record(2,3)))
        self.assertEqual([r[1] for r in messages],[0,2])
        self.assertEqual(d.stats['crc_errors'],1)
        self.assertEqual(d.stats['sequence_gaps'],1)
        self.assertFalse(validate(d))

    def test_missing_frame_and_missing_end_fail(self):
        d=Decoder();list(d.feed(record(0)+record(2,3)))
        self.assertFalse(validate(d))
        d=Decoder();list(d.feed(record(0)))
        self.assertFalse(validate(d))

    def test_recorded_queue_drop_and_unwritten_frame_fail(self):
        for index in [2,3,4,5]:
            counts=[0]*11;counts[index]=1
            d=Decoder();list(d.feed(record(0,3,struct.pack('<11I',*counts))))
            self.assertFalse(validate(d))

    def test_lost_start_and_records_after_end_fail(self):
        for stream in [record(1,3), record(0,3)+record(1), record(0,3)+record(1,3)]:
            d=Decoder();list(d.feed(stream))
            self.assertFalse(validate(d))

    def test_inconsistent_selected_count_and_trailing_record_fail(self):
        counts=[0]*11;counts[1]=1
        d=Decoder();list(d.feed(record(0,3,struct.pack('<11I',*counts))))
        self.assertFalse(validate(d))
        d=Decoder();list(d.feed(record(0,3)+MAGIC))
        self.assertFalse(validate(d))

    def test_radiotap_preserves_mpdu_and_excludes_dma_padding(self):
        raw=bytearray(48);raw[0]=(-45)&255
        mpdu=bytes(range(25));payload=struct.pack('<HBB',len(mpdu),3,0)+raw+mpdu+b'\0'*3
        frame=radiotap(payload)
        self.assertEqual(frame[15:],mpdu)
        self.assertEqual(struct.unpack_from('<H',frame,10)[0],2422)
        self.assertEqual(struct.unpack_from('b',frame,14)[0],-45)

if __name__=='__main__': unittest.main()
