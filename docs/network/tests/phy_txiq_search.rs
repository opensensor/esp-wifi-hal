#[path = "../../../esp-wifi-hal/src/phy_txiq_search.rs"]
mod model;
use model::Access;
use std::{
    collections::BTreeMap,
    io::{self, BufRead},
};
const OUT: u32 = 0x200000;
const PARAM: u32 = 0x240000;
const TABLE: u32 = 0x250000;
const TABLES: [u32; 2] = [0x310000, 0x310800];
struct Host<const S3: bool> {
    memory: BTreeMap<u32, u8>,
    trace: Vec<String>,
    calls: usize,
    abs_calls: usize,
    returns: [u32; 48],
    effects: [[u32; 6]; 48],
    policy: u32,
    have_samples: bool,
    have_coefficients: bool,
}
impl<const S3: bool> Host<S3> {
    fn offsets() -> [u32; 5] {
        if S3 {
            [0xec, 36, 0x1a8, 0x1ac, 0x1cc]
        } else {
            [0x100, 36, 0x1cc, 0x1d0, 0x1f0]
        }
    }
    fn put(&mut self, a: u32, w: usize, v: u32) {
        for i in 0..w {
            self.memory.insert(a + i as u32, (v >> (8 * i)) as u8);
        }
    }
    fn get(&self, a: u32, w: usize) -> u32 {
        (0..w)
            .map(|i| (*self.memory.get(&(a + i as u32)).unwrap() as u32) << (8 * i))
            .sum()
    }
    fn set_slots(&mut self, v: u32) {
        for (i, t) in TABLES.iter().enumerate() {
            for (k, o) in Self::offsets().iter().enumerate() {
                self.put(
                    t + o,
                    4,
                    0x500000 + i as u32 * 4096 + v * 256 + k as u32 * 16,
                );
            }
        }
    }
    fn output_effect(&mut self, seed: u32) {
        for i in 0..32 {
            self.put(OUT + i, 1, seed.wrapping_add(i * 17));
        }
    }
    fn location(&self, a: u32, w: usize) -> String {
        if self.have_samples && [0x220000, 0x220002].contains(&a) && w == 2 {
            return format!("[\"sample\",{}]", (a - 0x220000) / 2);
        }
        if self.have_coefficients && (0x230000..0x230002).contains(&a) && w == 1 {
            return format!("[\"coefficient\",{}]", a - 0x230000);
        }
        if (OUT..OUT + 32).contains(&a) && a + w as u32 <= OUT + 32 {
            return format!("[\"out\",{}]", a - OUT);
        }
        if [0x60006040, 0x6000607c].contains(&a) && w == 4 {
            return format!("[\"reg\",{a}]");
        }
        if (PARAM..PARAM + if S3 { 740 } else { 848 }).contains(&a) {
            return format!("[\"param\",{}]", a - PARAM);
        }
        if a == TABLE && w == 4 {
            return "[\"table\"]".into();
        }
        for (i, t) in TABLES.iter().enumerate() {
            for o in Self::offsets() {
                if a == t + o && w == 4 {
                    return format!("[\"slot\",{i},{o}]");
                }
            }
        }
        panic!("Unknown location {a:x}/{w}");
    }
    fn callback(&mut self, p: u32, args: &[u32]) -> u32 {
        let raw = p.checked_sub(0x500000).unwrap();
        let table = raw / 4096;
        let version = (raw % 4096) / 256;
        let kind = (raw % 256) / 16;
        assert!(table < 2 && version < 2 && kind < 5 && raw % 16 == 0);
        let prefix = ["abs", "loopback", "pbus_write", "pbus_read", "dco"][kind as usize];
        self.helper(&format!("{prefix}{}", table * 2 + version), args)
    }
    fn helper(&mut self, name: &str, args: &[u32]) -> u32 {
        let effect = self.effects[self.calls];
        let mut result = self.returns[self.calls];
        self.calls += 1;
        if name == "txiq_get_mis_pwr" {
            self.have_samples = true;
        }
        if name == "txiq_cover" {
            self.have_coefficients = true;
        }
        self.trace.push(format!("[\"call\",\"{name}\",{args:?}]"));
        if name.starts_with("abs") {
            result = match self.policy {
                0 => (args[0] as i32).unsigned_abs(),
                1 => 0,
                2 => 2,
                3 => {
                    if self.abs_calls % 2 == 0 {
                        0
                    } else {
                        2
                    }
                }
                _ => result,
            };
            self.abs_calls += 1;
        }
        self.put(0x60006040, 4, effect[0]);
        self.put(0x6000607c, 4, effect[1]);
        self.put(PARAM + 162, 1, effect[2]);
        if !S3 {
            self.put(PARAM + 832, 2, effect[2] >> 16);
        }
        self.output_effect(effect[3]);
        self.put(TABLE, 4, TABLES[(effect[4] & 1) as usize]);
        self.set_slots((effect[4] >> 1) & 1);
        if self.have_samples {
            self.put(0x220000, 2, effect[5]);
            self.put(0x220002, 2, effect[5] >> 16);
        }
        if self.have_coefficients {
            self.put(0x230000, 1, effect[5]);
            self.put(0x230001, 1, effect[5] >> 16);
        }
        self.trace.push(format!("[\"effect\",{effect:?}]"));
        result
    }
}
impl<const S3: bool> Access for Host<S3> {
    const S3: bool = S3;
    fn read(&mut self, a: u32, w: usize) -> u32 {
        let loc = self.location(a, w);
        let v = self.get(a, w);
        self.trace.push(format!("[\"read\",{w},{loc},{v}]"));
        v
    }
    fn write(&mut self, a: u32, w: usize, v: u32) {
        let loc = self.location(a, w);
        let v = if w == 4 { v } else { v & ((1 << (w * 8)) - 1) };
        self.trace.push(format!("[\"write\",{w},{loc},{v}]"));
        self.put(a, w, v);
    }
    fn parameter(&mut self, o: usize, w: usize) -> u32 {
        self.read(PARAM + o as u32, w)
    }
    fn table(&mut self) -> u32 {
        self.read(TABLE, 4)
    }
    fn slot(&mut self, t: u32, o: u32) -> u32 {
        self.read(t + o, 4)
    }
    fn call1(&mut self, p: u32, a: u32) -> u32 {
        self.callback(p, &[a])
    }
    fn call2(&mut self, p: u32, a: u32, b: u32) -> u32 {
        self.callback(p, &[a, b])
    }
    fn call3(&mut self, p: u32, a: u32, b: u32, c: u32) -> u32 {
        self.callback(p, &[a, b, c])
    }
    fn set_correction(&mut self, c: i32, s: u32) -> i32 {
        self.helper("txiq_set_reg", &[c as u32, s]) as i32
    }
    fn measure(&mut self, s: u32, a: u32, t: i32) {
        self.helper("txiq_get_mis_pwr", &[s, a, t as u32, 0x220000, 0x220002]);
    }
    fn sample(&mut self, i: usize) -> i16 {
        self.read(0x220000 + i as u32 * 2, 2) as i16
    }
    fn debug_mode(&mut self) {
        self.helper("txcal_debuge_mode", &[]);
    }
    fn work_mode(&mut self) {
        self.helper("txcal_work_mode", &[]);
    }
    fn txdc(&mut self, d: u32) {
        self.helper("txdc_cal_v70", &[d]);
    }
    fn attenuation(&mut self, t: i32, a: i32, p: i32, o: u32) -> i32 {
        self.helper("get_power_atten", &[t as u32, a as u32, p as u32, o, 0]) as i32
    }
    fn cover(&mut self, c: u8, t: i32) {
        self.helper("txiq_cover", &[c as u32, t as u32, 0x230000]);
    }
    fn coefficient(&mut self, i: usize) -> u8 {
        self.read(0x230000 + i as u32, 1) as u8
    }
    fn write_coefficient(&mut self, i: usize, v: u8) {
        self.write(0x230000 + i as u32, 1, v as u32)
    }
}
fn run<const S3: bool>(v: &[u32]) {
    assert_eq!(v.len(), 349);
    let mut h = Host::<S3> {
        memory: BTreeMap::new(),
        trace: Vec::new(),
        calls: 0,
        abs_calls: 0,
        returns: v[13..61].try_into().unwrap(),
        effects: [[0; 6]; 48],
        policy: v[12],
        have_samples: false,
        have_coefficients: false,
    };
    for i in 0..if S3 { 740 } else { 848 } {
        h.put(PARAM + i, 1, v[9].wrapping_add(i * 17));
    }
    h.put(PARAM + 162, 1, v[7]);
    if !S3 {
        h.put(PARAM + 832, 2, v[8]);
    }
    h.put(0x60006040, 4, v[10]);
    h.put(0x6000607c, 4, v[11]);
    h.output_effect(v[9]);
    h.put(TABLE, 4, TABLES[0]);
    h.set_slots(0);
    for i in 0..48 {
        h.effects[i] = v[61 + i * 6..67 + i * 6].try_into().unwrap();
    }
    match v[0] {
        0 => model::search(&mut h, v[1], v[2] as i32, v[3]),
        1 => model::calibrate(&mut h, v[1], v[2], v[3], v[4], v[5], v[6]),
        _ => panic!("Unknown kind"),
    }
    let regs = [h.get(0x60006040, 4), h.get(0x6000607c, 4)];
    let out: Vec<_> = (0..32).map(|i| h.get(OUT + i, 1)).collect();
    let slots: Vec<_> = TABLES
        .iter()
        .flat_map(|t| Host::<S3>::offsets().map(|o| h.get(t + o, 4)))
        .collect();
    println!(
        "[[{}],[{:?},{:?},{},{},{},{:?}]]",
        h.trace.join(","),
        regs,
        out,
        h.get(PARAM + 162, 1),
        if S3 { 0 } else { h.get(PARAM + 832, 2) },
        h.get(TABLE, 4),
        slots
    );
}
fn main() {
    let chip = std::env::args().nth(1).unwrap();
    assert!(chip == "esp32c3" || chip == "esp32s3");
    for line in io::stdin().lock().lines() {
        let v: Vec<u32> = line
            .unwrap()
            .split_whitespace()
            .map(|x| x.parse().unwrap())
            .collect();
        if chip == "esp32s3" {
            run::<true>(&v)
        } else {
            run::<false>(&v)
        }
    }
}
