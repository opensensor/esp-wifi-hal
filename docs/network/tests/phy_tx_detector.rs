#[path = "../../../esp-wifi-hal/src/phy_tx_detector.rs"]
mod phy_tx_detector;
use phy_tx_detector::Access;
use std::io::{self, BufRead};

struct Host<const S3: bool> {
    register: u32,
    flags: u32,
    samples: [u16; 2],
    returns: [u32; 5],
    effects: [[u32; 4]; 5],
    calls: usize,
    trace: Vec<String>,
}

impl<const S3: bool> Host<S3> {
    fn call(&mut self, name: &str, args: &[u32]) -> u32 {
        self.trace.push(format!("[\"helper\",\"{name}\",{args:?}]"));
        let index = self.calls;
        self.calls += 1;
        let effect = self.effects[index];
        self.register = effect[0];
        self.flags = effect[1];
        self.samples = [effect[2] as u16, effect[3] as u16];
        self.trace
            .push(format!("[\"helper_effect\",{index},{effect:?}]"));
        self.returns[index]
    }
    fn event(&mut self, kind: &str, width: usize, region: &str, offset: u32, value: u32) {
        self.trace.push(format!(
            "[\"{kind}\",{width},[\"{region}\",{offset}],{value}]"
        ));
    }
}

impl<const S3: bool> Access for Host<S3> {
    const S3: bool = S3;
    fn read_register(&mut self) -> u32 {
        self.event("read", 4, "register", 0x6000e05c, self.register);
        self.register
    }
    fn write_register(&mut self, value: u32) {
        self.event("write", 4, "register", 0x6000e05c, value);
        self.register = value;
    }
    fn read_flags(&mut self) -> u32 {
        self.event("read", 4, "param", 0x120, self.flags);
        self.flags
    }
    fn write_flags(&mut self, value: u32) {
        self.event("write", 4, "param", 0x120, value);
        self.flags = value;
    }
    fn write_sample(&mut self, index: usize, value: u16) {
        self.event("write", 2, "param", 218 + index as u32 * 2, value as u32);
        self.samples[index] = value;
    }
    fn tone(&mut self, code: u8) {
        self.call("start_tx_tone_step", &[1, 128, code as u32, 0, 0, 0]);
    }
    fn sample(&mut self) -> u32 {
        self.call("get_tone_sar_dout", &[4])
    }
    fn debug_mode(&mut self) {
        self.call("txcal_debuge_mode", &[]);
    }
    fn work_mode(&mut self) {
        self.call("txcal_work_mode", &[]);
    }
}

fn run<const S3: bool>(values: &[u32]) {
    assert_eq!(values.len(), 29);
    let mut host = Host::<S3> {
        register: values[3],
        flags: values[2],
        samples: [0x1234, 0x5678],
        returns: values[4..9].try_into().unwrap(),
        effects: [[0; 4]; 5],
        calls: 0,
        trace: Vec::new(),
    };
    for index in 0..5 {
        host.effects[index] = values[9 + index * 4..13 + index * 4].try_into().unwrap();
    }
    match values[0] {
        0 => phy_tx_detector::reference(&mut host, values[1] as u8),
        1 => phy_tx_detector::calibrate(&mut host),
        _ => panic!("invalid operation"),
    }
    println!(
        "[[{}],[{},{},{},{}]]",
        host.trace.join(","),
        host.register,
        host.flags,
        host.samples[0],
        host.samples[1]
    );
}

fn main() {
    let s3 = std::env::args().nth(1).unwrap() == "esp32s3";
    for line in io::stdin().lock().lines() {
        let line = line.unwrap();
        let values: Vec<u32> = line
            .split_whitespace()
            .map(|x| x.parse().unwrap())
            .collect();
        if s3 {
            run::<true>(&values);
        } else {
            run::<false>(&values);
        }
    }
}
