#[path = "../../../esp-wifi-hal/src/phy_tx_iq_measure.rs"]
mod phy_tx_iq_measure;
use phy_tx_iq_measure::Access;
use std::io::{self, BufRead};
struct Host<const S3: bool> {
    regs: [u32; 2],
    out: [u8; 8],
    table: usize,
    samples: [u32; 6],
    limits: [u32; 6],
    effects: [[u32; 5]; 32],
    calls: usize,
    sample: usize,
    limit: usize,
    trace: Vec<String>,
}
impl<const S3: bool> Host<S3> {
    fn call(&mut self, name: &str, args: &[u32]) -> i32 {
        self.trace.push(format!("[\"call\",\"{name}\",{args:?}]"));
        let result = match name {
            "txtone_linear_pwr" | "get_power_db" => {
                let v = self.samples[self.sample];
                self.sample += 1;
                v
            }
            "limit0" | "limit1" => {
                let v = self.limits[self.limit];
                self.limit += 1;
                v
            }
            _ => 0xabcdef00,
        };
        let e = self.effects[self.calls];
        self.calls += 1;
        self.regs = [e[0], e[1]];
        self.out[0..2].copy_from_slice(&(e[2] as u16).to_le_bytes());
        self.out[2..4].copy_from_slice(&(e[3] as u16).to_le_bytes());
        self.table = (e[4] & 1) as usize;
        self.trace.push(format!("[\"effect\",{e:?}]"));
        result as i32
    }
}
impl<const S3: bool> Access for Host<S3> {
    const S3: bool = S3;
    fn read_register(&mut self, a: u32) -> u32 {
        let v = self.regs[((a - 0x60006040) / 16) as usize];
        self.trace.push(format!("[\"read\",4,[\"reg\",{a}],{v}]"));
        v
    }
    fn write_register(&mut self, a: u32, v: u32) {
        self.trace.push(format!("[\"write\",4,[\"reg\",{a}],{v}]"));
        self.regs[((a - 0x60006040) / 16) as usize] = v;
    }
    fn write_sample(&mut self, a: u32, v: u16) {
        let offset = (a - 0x200000) as usize;
        self.trace
            .push(format!("[\"write\",2,[\"out\",{offset}],{v}]"));
        self.out[offset..offset + 2].copy_from_slice(&v.to_le_bytes());
    }
    fn delay(&mut self) {
        self.call("ets_delay_us", &[2]);
    }
    fn linear(&mut self) -> i32 {
        self.call("txtone_linear_pwr", &[])
    }
    fn tone(&mut self, tone: i32, code: u8) {
        self.call(
            "start_tx_tone_step",
            &[1, tone as u32, code as u32, 0, 0, 0],
        );
    }
    fn power_db(&mut self, offset: u32) -> i32 {
        self.call("get_power_db", &[offset])
    }
    fn log(&mut self, i: i32, a: i32, s: i32, t: i32, d: i32) {
        self.call(
            "phy_printf",
            &[i as u32, a as u32, s as u32, t as u32, d as u32],
        );
    }
    fn limit(&mut self, d: i32) -> i32 {
        let table = 0x210000 + self.table * 256;
        let call = 0x220000 + self.table * 256;
        self.trace.push(format!("[\"read\",4,[\"table\"],{table}]"));
        self.trace
            .push(format!("[\"read\",4,[\"slot\",{}],{call}]", self.table));
        self.call(
            if self.table == 0 { "limit0" } else { "limit1" },
            &[d as u32, 20, (-20i32) as u32],
        )
    }
}
fn run<const S3: bool>(v: &[u32]) {
    assert_eq!(v.len(), 180);
    let mut h = Host::<S3> {
        regs: [v[6], v[7]],
        out: [0xa5; 8],
        table: 0,
        samples: v[8..14].try_into().unwrap(),
        limits: v[14..20].try_into().unwrap(),
        effects: [[0; 5]; 32],
        calls: 0,
        sample: 0,
        limit: 0,
        trace: Vec::new(),
    };
    for i in 0..32 {
        h.effects[i] = v[20 + i * 5..25 + i * 5].try_into().unwrap();
    }
    if v[0] == 0 {
        phy_tx_iq_measure::measure(&mut h, v[1], v[2], v[3] as i32, v[4], v[5]);
    } else {
        let result = phy_tx_iq_measure::attenuation(
            &mut h,
            v[1] as i32,
            v[2] as i32,
            v[3] as i32,
            v[4],
            v[5],
        );
        h.trace.push(format!("[\"return\",{}]", result as u32));
    }
    println!(
        "[[{}],[{},{},{},{},{}]]",
        h.trace.join(","),
        h.regs[0],
        h.regs[1],
        u32::from_le_bytes(h.out[0..4].try_into().unwrap()),
        u32::from_le_bytes(h.out[4..8].try_into().unwrap()),
        0x210000 + h.table * 256
    );
}
fn main() {
    let s3 = std::env::args().nth(1).unwrap() == "esp32s3";
    for line in io::stdin().lock().lines() {
        let line = line.unwrap();
        let v: Vec<u32> = line
            .split_whitespace()
            .map(|v| v.parse().unwrap())
            .collect();
        if s3 {
            run::<true>(&v)
        } else {
            run::<false>(&v)
        }
    }
}
