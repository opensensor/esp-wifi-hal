//! Bounded passive C3 capture with asynchronous USB transport and loss counters.
//! Commands: B<12 hex BSSID>, M<12 hex station>, D<1..3600 seconds>, S (stop).
//! No radio transmit calls or hardware filters for the observed station are used.
#![no_std]
#![no_main]

use core::cell::RefCell;
use embassy_executor::Spawner;
use embassy_futures::{
    select::{Either, select},
    yield_now,
};
use embassy_sync::{
    blocking_mutex::{Mutex, raw::CriticalSectionRawMutex},
    channel::Channel,
};
use embassy_time::{Duration, Instant, Timer};
use embedded_io_async::{Read, Write};
use esp_backtrace as _;
use esp_hal::{
    Async,
    usb_serial_jtag::{UsbSerialJtag, UsbSerialJtagRx, UsbSerialJtagTx},
};
use esp_wifi_hal::prelude::*;
use examples::{common_init, embassy_init, get_test_channel, mk_static};

#[path = "../capture_protocol.rs"]
mod protocol;

#[derive(Clone, Copy)]
struct Settings {
    bssid: Option<[u8; 6]>,
    station: Option<[u8; 6]>,
    seconds: u32,
    generation: u32,
    bad_commands: u32,
    stop: bool,
}
static SETTINGS: Mutex<CriticalSectionRawMutex, RefCell<Settings>> =
    Mutex::new(RefCell::new(Settings {
        bssid: None,
        station: None,
        seconds: 1200,
        generation: 0,
        bad_commands: 0,
        stop: false,
    }));
struct Record {
    kind: u8,
    sequence: u32,
    micros: u64,
    len: usize,
    payload: [u8; protocol::MAX_PAYLOAD],
}
static OUTPUT: Channel<CriticalSectionRawMutex, Record, 16> = Channel::new();

fn address(text: &[u8]) -> Option<[u8; 6]> {
    if text.len() != 12 {
        return None;
    }
    let mut result = [0; 6];
    for (out, pair) in result.iter_mut().zip(text.chunks_exact(2)) {
        let digit = |b: u8| match b {
            b'0'..=b'9' => Some(b - b'0'),
            b'a'..=b'f' => Some(b - b'a' + 10),
            b'A'..=b'F' => Some(b - b'A' + 10),
            _ => None,
        };
        *out = (digit(pair[0])? << 4) | digit(pair[1])?;
    }
    if result[0] & 1 != 0 || result == [0; 6] {
        return None;
    }
    Some(result)
}
fn command(line: &[u8]) {
    SETTINGS.lock(|cell| {
        let mut s = cell.borrow_mut();
        let accepted = match line.first() {
            Some(b'B') => address(&line[1..]).map(|mac| s.bssid = Some(mac)).is_some(),
            Some(b'M') => address(&line[1..])
                .map(|mac| s.station = Some(mac))
                .is_some(),
            Some(b'D') => core::str::from_utf8(&line[1..])
                .ok()
                .and_then(|n| n.parse::<u32>().ok())
                .filter(|n| (1..=3600).contains(n))
                .map(|n| s.seconds = n)
                .is_some(),
            Some(b'S') if line.len() == 1 => {
                s.stop = true;
                true
            }
            _ => false,
        };
        if accepted {
            s.generation += 1;
        } else {
            s.bad_commands += 1;
        }
    });
}
#[embassy_executor::task]
async fn commands(mut rx: UsbSerialJtagRx<'static, Async>) {
    let mut input = [0; 64];
    let mut line = [0; 32];
    let mut used = 0;
    let mut overflow = false;
    loop {
        let count = rx.read(&mut input).await.unwrap();
        for &byte in &input[..count] {
            if byte == b'\n' {
                if overflow {
                    command(b"?");
                } else {
                    command(&line[..used]);
                }
                used = 0;
                overflow = false;
            } else if byte != b'\r' {
                if used < line.len() {
                    line[used] = byte;
                    used += 1;
                } else {
                    overflow = true;
                }
            }
        }
    }
}
#[embassy_executor::task]
async fn output(mut tx: UsbSerialJtagTx<'static, Async>) {
    let mut wire = [0u8; protocol::HEADER_LEN + protocol::MAX_PAYLOAD + 4];
    loop {
        let record = OUTPUT.receive().await;
        wire[..protocol::HEADER_LEN].copy_from_slice(&protocol::header(
            record.kind,
            record.len,
            record.sequence,
            record.micros,
        ));
        let end = protocol::HEADER_LEN + record.len;
        wire[protocol::HEADER_LEN..end].copy_from_slice(&record.payload[..record.len]);
        let crc = protocol::crc32(&wire[..end]);
        wire[end..end + 4].copy_from_slice(&crc.to_le_bytes());
        tx.write_all(&wire[..end + 4]).await.unwrap();
        tx.flush().await.unwrap();
    }
}
fn record(kind: u8, sequence: &mut u32) -> Record {
    let result = Record {
        kind,
        sequence: *sequence,
        micros: Instant::now().as_micros(),
        len: 0,
        payload: [0; protocol::MAX_PAYLOAD],
    };
    *sequence = sequence.wrapping_add(1);
    result
}
fn status(kind: u8, sequence: &mut u32, counts: &[u32; 6], s: Settings, running: bool) -> Record {
    let mut r = record(kind, sequence);
    let values = [
        counts[0],
        counts[1],
        counts[2],
        counts[3],
        counts[4],
        counts[5],
        s.bad_commands,
        s.generation,
        s.bssid.is_some() as u32,
        s.station.is_some() as u32,
        running as u32,
    ];
    for (chunk, value) in r.payload.chunks_mut(4).zip(values) {
        chunk.copy_from_slice(&value.to_le_bytes());
    }
    r.len = values.len() * 4;
    r
}
fn selected(mpdu: &[u8], s: Settings) -> bool {
    if mpdu.len() < 24 {
        return false;
    }
    let Some(bssid) = s.bssid else {
        return false;
    };
    if ![4, 10, 16].iter().any(|&o| mpdu[o..o + 6] == bssid) {
        return false;
    }
    if let Some(station) = s.station {
        return [4, 10, 16].iter().any(|&o| mpdu[o..o + 6] == station);
    }
    // Before the host identifies the randomized station, retain management and
    // clear EAPOL only. Other clients' encrypted data is excluded.
    let kind = (mpdu[0] >> 2) & 3;
    if kind == 0 {
        return (mpdu[0] >> 4) != 8 && (mpdu[0] >> 4) != 5;
    }
    let qos = mpdu[0] & 0x80 != 0;
    let header = if qos { 26 } else { 24 };
    kind == 2 && mpdu.get(header..header + 8) == Some(&[0xaa, 0xaa, 3, 0, 0, 0, 0x88, 0x8e])
}

#[esp_rtos::main]
async fn main(spawner: Spawner) {
    let peripherals = common_init();
    embassy_init(peripherals.TIMG0, peripherals.SW_INTERRUPT);
    // The host must build with ESP_LOG=off. After this point only this transport
    // owns USB; binary records include CRCs to detect any unexpected text.
    assert!(
        log::max_level() == log::LevelFilter::Off,
        "build raw_capture with ESP_LOG=off"
    );
    let (rx, tx) = UsbSerialJtag::new(peripherals.USB_DEVICE)
        .into_async()
        .split();
    spawner.spawn(commands(rx).unwrap());
    spawner.spawn(output(tx).unwrap());
    let mut wifi = WiFi::new(
        peripherals.WIFI,
        mk_static!(WiFiResources<32>, WiFiResources::new()),
    );
    let channel = get_test_channel();
    assert!((1..=14).contains(&channel));
    wifi.set_channel(channel).unwrap();
    for interface in 0..INTERFACE_COUNT {
        wifi.clear_filter(interface, RxFilterBank::ReceiverAddress)
            .unwrap();
        wifi.clear_filter(interface, RxFilterBank::Bssid).unwrap();
    }
    wifi.set_scanning_mode(0, ScanningMode::ManagementAndData)
        .unwrap();
    wifi.set_filtered_address_types(0, false, false).unwrap();
    wifi.set_filter_bssid_check(0, false).unwrap();
    let mut sequence = 0;
    // Counts: valid DMA frames seen, selected, enqueued, queue drops, oversize,
    // status records dropped. Hardware/filter losses require external coverage.
    let mut counts = [0u32; 6];
    let start = Instant::now();
    let mut next_status = start;
    loop {
        let settings = SETTINGS.lock(|s| *s.borrow());
        let now = Instant::now();
        if settings.stop || now.duration_since(start).as_secs() >= settings.seconds as u64 {
            break;
        }
        if now >= next_status {
            if OUTPUT
                .try_send(status(2, &mut sequence, &counts, settings, true))
                .is_err()
            {
                counts[5] += 1;
            }
            next_status = now + Duration::from_secs(1);
        }
        match select(wifi.receive(), Timer::at(next_status)).await {
            Either::First(frame) => {
                counts[0] += 1;
                if option_env!("SNIFFER_DIAG_HEADS") == Some("1") && counts[0] <= 32 {
                    let mut r = record(4, &mut sequence);
                    r.len = frame.padded_buffer().len().min(72) + 4;
                    r.payload[2] = channel;
                    r.payload[4..r.len].copy_from_slice(&frame.padded_buffer()[..r.len - 4]);
                    if OUTPUT.try_send(r).is_err() {
                        counts[5] += 1;
                    }
                }
                if selected(frame.mpdu_buffer(), settings) {
                    counts[1] += 1;
                    if frame.padded_buffer().len() > 1600 {
                        counts[4] += 1;
                    } else {
                        let mut r = record(1, &mut sequence);
                        r.payload[..2]
                            .copy_from_slice(&(frame.mpdu_buffer().len() as u16).to_le_bytes());
                        r.payload[2] = channel;
                        r.len = frame.padded_buffer().len() + 4;
                        r.payload[4..r.len].copy_from_slice(frame.padded_buffer());
                        drop(frame);
                        if OUTPUT.try_send(r).is_ok() {
                            counts[2] += 1;
                        } else {
                            counts[3] += 1;
                        }
                    }
                }
            }
            Either::Second(_) => {}
        }
        yield_now().await;
    }
    wifi.set_rx_status(false);
    let settings = SETTINGS.lock(|s| *s.borrow());
    OUTPUT
        .send(status(3, &mut sequence, &counts, settings, false))
        .await;
    loop {
        Timer::after_secs(60).await;
    }
}
