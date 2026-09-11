//! Optional cumulative latency counters. Read snapshots while traffic is idle.
//! Independent atomic fields are not a transactional snapshot. Counts and total
//! microseconds wrap at u32::MAX; use for bounded diagnostic runs, not uptime.

use portable_atomic::{AtomicU32, Ordering};

/// Bounded, allocation-free timing histogram, with no console output.
pub struct Metric {
    count: AtomicU32,
    total: AtomicU32,
    maximum: AtomicU32,
    buckets: [AtomicU32; 5],
}
impl Default for Metric {
    fn default() -> Self {
        Self::new()
    }
}
impl Metric {
    /// Construct an empty counter.
    pub const fn new() -> Self {
        Self {
            count: AtomicU32::new(0),
            total: AtomicU32::new(0),
            maximum: AtomicU32::new(0),
            buckets: [const { AtomicU32::new(0) }; 5],
        }
    }
    /// Record elapsed microseconds. Buckets end at 100, 1000, 10000, 100000 us.
    pub fn record(&self, us: u32) {
        self.count.fetch_add(1, Ordering::Relaxed);
        self.total.fetch_add(us, Ordering::Relaxed);
        self.maximum.fetch_max(us, Ordering::Relaxed);
        let bucket = match us {
            0..100 => 0,
            100..1000 => 1,
            1000..10000 => 2,
            10000..100000 => 3,
            _ => 4,
        };
        self.buckets[bucket].fetch_add(1, Ordering::Relaxed);
    }
    /// Return count, total us, maximum us, followed by the five bucket counts.
    pub fn snapshot(&self) -> [u32; 8] {
        let mut out = [0; 8];
        out[0] = self.count.load(Ordering::Relaxed);
        out[1] = self.total.load(Ordering::Relaxed);
        out[2] = self.maximum.load(Ordering::Relaxed);
        for (value, bucket) in out[3..].iter_mut().zip(&self.buckets) {
            *value = bucket.load(Ordering::Relaxed);
        }
        out
    }
}
/// Elapsed PHY background tracking time, including any preemption.
pub static PHY_TRACKING: Metric = Metric::new();
/// Time from the latest slot interrupt signal to its task consuming success.
pub static TX_RESUME: Metric = Metric::new();
/// Wrapping MAC counter minus RX metadata timestamp at driver delivery.
/// This is diagnostic: the hardware timestamp's precise sampling point matters.
pub static RX_AGE: Metric = Metric::new();
static TX_IRQ: [AtomicU32; 5] = [const { AtomicU32::new(0) }; 5];

/// Low 32 bits of system monotonic microseconds, for short wrapping intervals.
pub fn now() -> u32 {
    esp_hal::time::Instant::now()
        .duration_since_epoch()
        .as_micros() as u32
}
pub(crate) fn tx_irq(slot: usize) {
    TX_IRQ[slot].store(now(), Ordering::Relaxed);
}
pub(crate) fn tx_resume(slot: usize) {
    TX_RESUME.record(now().wrapping_sub(TX_IRQ[slot].load(Ordering::Relaxed)));
}
