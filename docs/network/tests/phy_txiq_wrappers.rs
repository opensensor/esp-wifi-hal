#[path = "../../../esp-wifi-hal/src/phy_txiq_wrappers.rs"]
mod wrappers;
use std::io::{self, BufRead};
use wrappers::{Access, Output};
struct Host<const S3: bool> {
    param: Vec<u8>,
    table: u32,
    slots: [u32; 4],
    analog: [u32; 2],
    returns: [u32; 7],
    effects: [[u32; 5]; 7],
    calls: usize,
    trace: Vec<String>,
}
impl<const S3: bool> Host<S3> {
    fn put(&mut self, offset: usize, width: usize, value: u32) {
        self.param[offset..offset + width].copy_from_slice(&value.to_le_bytes()[..width]);
    }
    fn read(&mut self, offset: usize, width: usize) -> u32 {
        let mut bytes = [0u8; 4];
        bytes[..width].copy_from_slice(&self.param[offset..offset + width]);
        let value = u32::from_le_bytes(bytes);
        self.trace
            .push(format!("[\"read\",{width},[\"param\",{offset}],{value}]"));
        value
    }
    fn set_slots(&mut self, v: u32) {
        for t in 0..2 {
            for w in 0..2 {
                self.slots[t * 2 + w] = 0x320000 + t as u32 * 256 + v * 32 + w as u32 * 16;
            }
        }
    }
    fn call(&mut self, name: &str, args: &[u32]) -> u32 {
        self.trace.push(format!("[\"call\",\"{name}\",{args:?}]"));
        let effect = self.effects[self.calls];
        let result = self.returns[self.calls];
        self.calls += 1;
        if name.starts_with("write") {
            self.analog[(args[2] - 28) as usize] = args[3];
        }
        if name == "rfcal_txiq" {
            if args[1] != 0x210000 {
                for i in 0..4 {
                    self.put(
                        (args[1] - 0x200000) as usize + i * 2,
                        2,
                        effect[4].wrapping_add(i as u32 * 257),
                    );
                }
            }
            self.put((args[2] - 0x200000) as usize, 2, effect[4] >> 16);
        }
        self.put(288, 4, effect[0]);
        self.put(216, 1, effect[1]);
        self.table = 0x310000 + (effect[2] & 1) * 1024;
        self.set_slots(effect[3] & 1);
        self.trace.push(format!("[\"effect\",{effect:?}]"));
        result
    }
    fn name(callback: u32, write: bool) -> String {
        let raw = callback - 0x320000;
        let table = raw / 256;
        let version = (raw % 256) / 32;
        assert_eq!(
            callback,
            0x320000 + table * 256 + version * 32 + u32::from(write) * 16
        );
        assert!(table < 2 && version < 2);
        format!(
            "{}{}",
            if write { "write" } else { "read" },
            table * 2 + version
        )
    }
}
impl<const S3: bool> Access for Host<S3> {
    const S3: bool = S3;
    fn read_flags(&mut self) -> u32 {
        self.read(288, 4)
    }
    fn write_flags(&mut self, value: u32) {
        self.trace
            .push(format!("[\"write\",4,[\"param\",288],{value}]"));
        self.put(288, 4, value);
    }
    fn read_attenuation(&mut self) -> u8 {
        self.read(216, 1) as u8
    }
    fn table(&mut self) -> u32 {
        self.trace
            .push(format!("[\"read\",4,[\"table\"],{}]", self.table));
        self.table
    }
    fn slot(&mut self, table: u32, offset: u32) -> u32 {
        let t = (table - 0x310000) / 1024;
        let read = if S3 { 0x188 } else { 0x1ac };
        assert!(t < 2 && (offset == read || offset == read + 8));
        let v = self.slots[(t * 2 + (offset - read) / 8) as usize];
        self.trace
            .push(format!("[\"read\",4,[\"slot\",{t},{offset}],{v}]"));
        v
    }
    fn read_analog(&mut self, callback: u32, block: u32, host: u32, register: u32) -> u32 {
        self.call(&Self::name(callback, false), &[block, host, register])
    }
    fn write_analog(&mut self, callback: u32, block: u32, host: u32, register: u32, value: u32) {
        self.call(&Self::name(callback, true), &[block, host, register, value]);
    }
    fn calibrate(
        &mut self,
        output1: Output,
        output2: usize,
        tone: u32,
        attenuation: i32,
        mode: u32,
    ) {
        let p = match output1 {
            Output::Parameter(o) => 0x200000 + o as u32,
            Output::Scratch => 0x210000,
        };
        self.call(
            "rfcal_txiq",
            &[
                0,
                p,
                0x200000 + output2 as u32,
                tone,
                attenuation as u32,
                mode,
            ],
        );
    }
}
fn run<const S3: bool>(v: &[u32]) {
    assert_eq!(v.len(), 46);
    let mut h = Host::<S3> {
        param: (0..if S3 { 740 } else { 848 })
            .map(|i| v[3].wrapping_add(i * 17) as u8)
            .collect(),
        table: 0x310000,
        slots: [0; 4],
        analog: [0xa5a5a5a5, 0x5a5a5a5a],
        returns: v[4..11].try_into().unwrap(),
        effects: [[0; 5]; 7],
        calls: 0,
        trace: Vec::new(),
    };
    h.put(288, 4, v[1]);
    h.put(216, 1, v[2]);
    h.set_slots(0);
    for i in 0..7 {
        h.effects[i] = v[11 + i * 5..16 + i * 5].try_into().unwrap();
    }
    match v[0] {
        0 => wrappers::initialize(&mut h),
        1 => wrappers::bluetooth(&mut h),
        _ => panic!("Unknown operation"),
    }
    println!(
        "[[{}],[{:?},{},{:?},{:?}]]",
        h.trace.join(","),
        h.param,
        h.table,
        h.slots,
        h.analog
    );
}
fn main() {
    let chip = std::env::args().nth(1).unwrap();
    assert!(chip == "esp32c3" || chip == "esp32s3");
    for line in io::stdin().lock().lines() {
        let v: Vec<u32> = line
            .unwrap()
            .split_whitespace()
            .map(|v| v.parse().unwrap())
            .collect();
        if chip == "esp32s3" {
            run::<true>(&v)
        } else {
            run::<false>(&v)
        }
    }
}
