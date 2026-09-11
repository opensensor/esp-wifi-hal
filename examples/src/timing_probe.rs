//! Bounded timing experiment: TIMING_LOG_PROFILE=trace reproduces the reviewed
//! target filters; info reproduces the legacy INFO packet-output comparison;
//! quiet keeps boundary/error logs and counters. Packet metadata now uses TRACE,
//! so the first two profiles explicitly enable that target for reproduction.
//! No handshake key dumps are enabled. Samples accumulate without new packet logs.
use esp_wifi_hal::timing::{self, Metric};
use log::{Level, LevelFilter, Log, Metadata, Record};

static LOGGER: TimingLogger = TimingLogger;
static PRINT_TIME: Metric = Metric::new();
struct TimingLogger;
fn profile() -> &'static str {
    option_env!("TIMING_LOG_PROFILE").unwrap_or("quiet")
}
fn traced() -> bool {
    profile() == "trace"
}
impl Log for TimingLogger {
    fn enabled(&self, metadata: &Metadata<'_>) -> bool {
        let target = metadata.target();
        if profile() == "quiet" && target == "examples::packet_trace" {
            return false;
        }
        let ceiling = if target == "examples::packet_trace" {
            Level::Trace
        } else if traced()
            && (target.starts_with("embassy_net")
                || target.starts_with("smoltcp")
                || target.starts_with("foa::tx_queue"))
        {
            Level::Trace
        } else if traced() && (target == "foa" || target.starts_with("foa::")) {
            Level::Debug
        } else {
            Level::Info
        };
        metadata.level() <= ceiling
    }
    fn log(&self, record: &Record<'_>) {
        if !self.enabled(record.metadata()) {
            return;
        }
        let color = match record.level() {
            Level::Error => "\x1b[31m",
            Level::Warn => "\x1b[33m",
            Level::Info => "\x1b[32m",
            Level::Debug => "\x1b[34m",
            Level::Trace => "\x1b[35m",
        };
        let start = timing::now();
        // Same formatter and locked USB printer as esp-println 0.16.1's logger.
        esp_println::println!("{}{} - {}\x1b[0m", color, record.level(), record.args());
        PRINT_TIME.record(timing::now().wrapping_sub(start));
    }
    fn flush(&self) {}
}
pub fn init() {
    assert!(matches!(
        option_env!("TIMING_LOG_PROFILE"),
        None | Some("trace") | Some("info") | Some("quiet")
    ));
    unsafe {
        log::set_logger_racy(&LOGGER).unwrap();
        log::set_max_level_racy(LevelFilter::Trace);
    }
}
pub fn report(cycle: u32) {
    report_inner(cycle, false);
}
pub fn report_failure(cycle: u32) {
    report_inner(cycle, true);
}
fn report_inner(cycle: u32, _failed: bool) {
    #[cfg(feature = "handshake-probe")]
    {
        let h = foa_sta::handshake_probe::snapshot();
        esp_println::println!(
            "stage=handshake cycle={} phase={} phases_us={:?} queues={:?} eapol_routed={} eapol_dropped={} route_failures={} events={}",
            cycle, h.phase, h.phase_us, h.queues, h.eapol_routed, h.eapol_dropped, h.route_failures, h.total_events);
        if _failed || h.phase != 10 || h.eapol_routed > 2 {
            for index in h.total_events.saturating_sub(64)..h.total_events {
                let e = h.events[index as usize % 64];
                esp_println::println!("stage=handshake_event cycle={} index={} us={} phase={} kind={} a={} b={}",
                    cycle, index, e.us, e.phase, e.kind, e.a, e.b);
            }
        }
    }
    let sys = timing::now();
    let mac = unsafe { esp_wifi_hal::ll::LowLevelDriver::mac_time() }
        .duration_since_epoch()
        .as_micros();
    esp_println::println!(
        "stage=timing cycle={} profile={} cpu_mhz={} sys_us={} mac_us={} print={:?} phy={:?} tx_resume={:?} rx_age={:?}",
        cycle,
        profile(),
        esp_hal::clock::cpu_clock().as_mhz(),
        sys,
        mac,
        PRINT_TIME.snapshot(),
        timing::PHY_TRACKING.snapshot(),
        timing::TX_RESUME.snapshot(),
        timing::RX_AGE.snapshot()
    );
}
