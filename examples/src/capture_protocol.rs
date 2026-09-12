//! Framing shared by the raw-capture example and host regression checks.
pub const MAGIC: &[u8; 8] = b"RWCAP3\r\n";
pub const HEADER_LEN: usize = 24;
pub const MAX_PAYLOAD: usize = 1604;

const fn crc_table() -> [u32; 256] {
    let mut table = [0; 256];
    let mut i = 0;
    while i < 256 {
        let mut value = i as u32;
        let mut bit = 0;
        while bit < 8 {
            value = (value >> 1) ^ (0xedb88320 & (0u32.wrapping_sub(value & 1)));
            bit += 1;
        }
        table[i] = value;
        i += 1;
    }
    table
}
const TABLE: [u32; 256] = crc_table();
pub fn crc32(bytes: &[u8]) -> u32 {
    !bytes.iter().fold(!0, |crc, byte| {
        (crc >> 8) ^ TABLE[((crc as u8) ^ byte) as usize]
    })
}
pub fn header(kind: u8, payload_len: usize, sequence: u32, micros: u64) -> [u8; HEADER_LEN] {
    assert!(payload_len <= MAX_PAYLOAD);
    let mut out = [0; HEADER_LEN];
    out[..8].copy_from_slice(MAGIC);
    out[8..10].copy_from_slice(&(payload_len as u16).to_le_bytes());
    out[10] = kind;
    out[11] = 1;
    out[12..16].copy_from_slice(&sequence.to_le_bytes());
    out[16..24].copy_from_slice(&micros.to_le_bytes());
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn standard_crc_vector_and_little_endian_header() {
        assert_eq!(crc32(b"123456789"), 0xcbf43926);
        let h = header(1, 600, 0x12345678, 0x1122334455667788);
        assert_eq!(&h[8..16], &[0x58, 2, 1, 1, 0x78, 0x56, 0x34, 0x12]);
        assert_eq!(&h[16..], &[0x88, 0x77, 0x66, 0x55, 0x44, 0x33, 0x22, 0x11]);
    }
}
