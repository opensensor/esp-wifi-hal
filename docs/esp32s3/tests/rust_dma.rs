//! Exercise the production DMA-list algorithm with host descriptors and MMIO stubs.
#![allow(dead_code)]
extern crate self as esp_hal;

macro_rules! trace {
    ($($arg:tt)*) => {};
}
macro_rules! debug {
    ($($arg:tt)*) => {};
}
macro_rules! info {
    ($($arg:tt)*) => {};
}

// The fields, completion bit and reset semantics used here match esp-hal 1.1.2.
pub mod dma {
    #[derive(Clone, Copy)]
    pub struct DmaDescriptorFlags(pub u32);
    impl DmaDescriptorFlags {
        pub fn suc_eof(&self) -> bool {
            self.0 & (1 << 30) != 0
        }
    }
    pub enum Owner {
        Cpu,
        Dma,
    }
    #[derive(Clone, Copy)]
    pub struct DmaDescriptor {
        pub flags: DmaDescriptorFlags,
        pub buffer: *mut u8,
        pub next: *mut DmaDescriptor,
    }
    impl DmaDescriptor {
        pub fn reset_for_rx(&mut self) {
            self.set_owner(Owner::Dma);
            self.flags.0 &= !(1 << 30);
            self.set_length(0);
        }
        pub fn set_size(&mut self, size: usize) {
            self.flags.0 = (self.flags.0 & !0xfff) | size as u32;
        }
        pub fn set_length(&mut self, len: usize) {
            self.flags.0 = (self.flags.0 & !0xfff000) | ((len as u32) << 12);
        }
        pub fn len(&self) -> usize {
            ((self.flags.0 >> 12) & 0xfff) as usize
        }
        pub fn set_owner(&mut self, owner: Owner) {
            self.flags.0 =
                (self.flags.0 & !(1 << 31)) | ((matches!(owner, Owner::Dma) as u32) << 31);
        }
    }
}
mod borrowed_buffer {
    pub struct BorrowedBuffer;
    impl BorrowedBuffer {
        pub const RX_CONTROL_HEADER_LENGTH: usize = 48;
    }
}
mod ll {
    use super::dma::DmaDescriptor;
    use std::{
        cell::{Cell, RefCell},
        ptr::NonNull,
    };
    #[derive(Default)]
    pub struct LowLevelDriver {
        pub base: Cell<Option<NonNull<DmaDescriptor>>>,
        pub reloads: RefCell<Vec<Option<NonNull<DmaDescriptor>>>>,
        pub next: Cell<Option<NonNull<DmaDescriptor>>>,
        pub last: Cell<Option<NonNull<DmaDescriptor>>>,
    }
    impl LowLevelDriver {
        pub fn start_rx(&self, base: NonNull<DmaDescriptor>) {
            self.base.set(Some(base));
        }
        pub fn stop_rx(&self) {
            self.base.set(None);
        }
        pub fn set_base_rx_descriptor(&self, base: NonNull<DmaDescriptor>) {
            self.base.set(Some(base));
            self.reloads.borrow_mut().push(Some(base));
        }
        pub fn clear_base_rx_descriptor(&self) {
            self.base.set(None);
        }
        pub fn reload_hw_rx_descriptors(&self) {
            self.reloads.borrow_mut().push(self.base.get());
        }
        pub fn next_rx_descriptor(&self) -> Option<NonNull<DmaDescriptor>> {
            self.next.get()
        }
        pub fn last_rx_descriptor(&self) -> Option<NonNull<DmaDescriptor>> {
            self.last.get()
        }
    }
}
#[path = "../../../esp-wifi-hal/src/dma_list.rs"]
mod dma_list;

use dma_list::{DmaBufferSlab, DmaList};
use std::ptr::NonNull;

fn setup() -> (
    DmaList,
    &'static ll::LowLevelDriver,
    NonNull<dma::DmaDescriptor>,
) {
    let driver = Box::leak(Box::new(ll::LowLevelDriver::default()));
    let slab = Box::leak(Box::new(DmaBufferSlab::<3, 1600>::new()));
    let (base, last) = unsafe { slab.init() };
    (DmaList::new(base, last, driver), driver, base)
}

#[test]
fn completed_short_descriptor_is_returned_for_recycling_before_the_next_frame() {
    for length in [0, 1, 24, 47] {
        let (mut list, driver, mut first) = setup();
        let second = unsafe { NonNull::new(first.as_ref().next).unwrap() };
        unsafe {
            first.as_mut().set_length(length);
            first.as_mut().flags.0 |= 1 << 30;
            (*second.as_ptr()).set_length(72);
            (*second.as_ptr()).flags.0 |= 1 << 30;
        }
        let discarded = list.take_first().expect("Completed short head stalled RX");
        assert_eq!(discarded.len(), length);
        driver.next.set(Some(second));
        list.recycle(discarded);
        let valid = list
            .take_first()
            .expect("Frame behind short descriptor was stranded");
        assert_eq!(valid.len(), 72);
    }
}

#[test]
fn incomplete_descriptor_is_left_for_hardware() {
    let (mut list, driver, base) = setup();
    assert!(list.take_first().is_none());
    assert_eq!(driver.base.get(), Some(base));
}

#[test]
fn empty_s3_hardware_queue_restarts_from_returned_descriptor() {
    let (mut list, driver, first) = setup();
    unsafe {
        let mut current = Some(first);
        while let Some(mut ptr) = current {
            ptr.as_mut().set_length(72);
            ptr.as_mut().flags.0 |= 1 << 30;
            current = NonNull::new(ptr.as_ref().next);
        }
    }
    let returned = list.take_first().unwrap();
    let _held_second = list.take_first().unwrap();
    let _held_third = list.take_first().unwrap();
    driver.next.set(None); // S3 zero offset means hardware queue empty.
    driver.last.set(None);
    list.recycle(returned);
    assert_eq!(driver.base.get(), Some(first));
}

#[test]
fn hardware_empty_append_preserves_pending_frames_and_the_new_software_tail() {
    let (mut list, driver, mut first) = setup();
    let mut second = unsafe { NonNull::new(first.as_ref().next).unwrap() };
    let mut third = unsafe { NonNull::new(second.as_ref().next).unwrap() };
    unsafe {
        for (descriptor, length) in [(&mut first, 72), (&mut second, 84), (&mut third, 96)] {
            descriptor.as_mut().set_length(length);
            descriptor.as_mut().flags.0 |= 1 << 30;
        }
    }
    let returned = list.take_first().unwrap();
    driver.next.set(None); // Hardware reached the null tail after completing all three.
    driver.last.set(Some(third));
    list.recycle(returned);
    assert_eq!(
        driver.base.get(),
        Some(first),
        "Hardware must resume at the returned buffer"
    );

    let pending = list
        .take_first()
        .expect("Restart discarded an unread completed frame");
    assert_eq!(pending as *mut _, second.as_ptr());
    assert_eq!(pending.len(), 84);
    driver.next.set(Some(first));
    list.recycle(pending);
    unsafe {
        assert_eq!(
            third.as_ref().next,
            first.as_ptr(),
            "An old software tail overwrote the live chain"
        );
        assert_eq!(first.as_ref().next, second.as_ptr());
        assert!(second.as_ref().next.is_null());
    }
    let pending = list
        .take_first()
        .expect("Second unread completion disappeared");
    assert_eq!(pending as *mut _, third.as_ptr());
    assert_eq!(pending.len(), 96);
}

#[test]
fn returns_never_link_to_borrowed_descriptors_or_form_a_cycle() {
    for reverse in [false, true] {
        let (mut list, driver, mut first) = setup();
        let second = unsafe { NonNull::new(first.as_ref().next).unwrap() };
        let third = unsafe { NonNull::new(second.as_ref().next).unwrap() };
        unsafe {
            first.as_mut().set_length(72);
            first.as_mut().flags.0 |= 1 << 30;
            (*second.as_ptr()).set_length(72);
            (*second.as_ptr()).flags.0 |= 1 << 30;
        }
        let a = list.take_first().unwrap();
        let b = list.take_first().unwrap();
        let (returned, borrowed, returned_ptr, borrowed_ptr) = if reverse {
            (b, a, second, first)
        } else {
            (a, b, first, second)
        };
        driver.next.set(Some(third));
        list.recycle(returned);
        unsafe {
            assert_eq!((*third.as_ptr()).next, returned_ptr.as_ptr());
            assert!(
                (*returned_ptr.as_ptr()).next.is_null(),
                "Recycled descriptor points to a borrowed buffer"
            );
        }
        list.recycle(borrowed);
        unsafe {
            assert_eq!((*returned_ptr.as_ptr()).next, borrowed_ptr.as_ptr());
            assert!(
                (*borrowed_ptr.as_ptr()).next.is_null(),
                "Stale next link makes a hardware loop"
            );
        }
    }
}

#[test]
fn consuming_completions_does_not_rewind_active_dma_or_replay_unread_frames() {
    let (mut list, driver, first) = setup();
    let second = unsafe { NonNull::new(first.as_ref().next).unwrap() };
    let third = unsafe { NonNull::new(second.as_ref().next).unwrap() };
    unsafe {
        for ptr in [first, second] {
            (*ptr.as_ptr()).set_length(72);
            (*ptr.as_ptr()).flags.0 |= 1 << 30;
        }
    }
    driver.next.set(Some(third));
    driver.last.set(Some(second));
    let a = list.take_first().unwrap();
    assert_eq!(a as *mut _, first.as_ptr());
    assert!(
        driver.reloads.borrow().is_empty(),
        "Dequeue rewound DMA onto an unread completion"
    );
    list.recycle(a);
    assert!(
        driver.reloads.borrow().is_empty(),
        "Append replayed the completed software head"
    );
    unsafe {
        assert_eq!(third.as_ref().next, first.as_ptr());
        (*third.as_ptr()).set_length(84);
        (*third.as_ptr()).flags.0 |= 1 << 30;
    }
    // Hardware had cached the old null tail before the append. Its completion
    // wakes the consumer, which must restart at the fresh returned descriptor.
    driver.next.set(None);
    driver.last.set(Some(third));
    let b = list.take_first().unwrap();
    assert_eq!(b as *mut _, second.as_ptr());
    assert_eq!(*driver.reloads.borrow(), vec![Some(first)]);
    assert!(unsafe { third.as_ref().flags.suc_eof() });
}

#[test]
fn exhausted_dma_waits_when_only_unread_completions_remain() {
    let (mut list, driver, first) = setup();
    let second = unsafe { NonNull::new(first.as_ref().next).unwrap() };
    let third = unsafe { NonNull::new(second.as_ref().next).unwrap() };
    for ptr in [first, second, third] {
        unsafe {
            (*ptr.as_ptr()).set_length(72);
            (*ptr.as_ptr()).flags.0 |= 1 << 30;
        }
    }
    driver.next.set(None);
    driver.last.set(Some(third));
    let held_first = list.take_first().unwrap();
    let held_second = list.take_first().unwrap();
    assert!(driver.reloads.borrow().is_empty());
    assert!(unsafe { third.as_ref().flags.suc_eof() });
    list.recycle(held_second);
    assert_eq!(*driver.reloads.borrow(), vec![Some(second)]);
    assert_eq!(list.take_first().unwrap() as *mut _, third.as_ptr());
    assert!(held_first.next.is_null());
}

#[test]
fn exhausted_dma_restarts_the_oldest_available_buffer() {
    let (mut list, driver, first) = setup();
    let second = unsafe { NonNull::new(first.as_ref().next).unwrap() };
    unsafe {
        (*first.as_ptr()).set_length(72);
        (*first.as_ptr()).flags.0 |= 1 << 30;
    }
    driver.next.set(Some(second));
    let held = list.take_first().unwrap();
    driver.next.set(None);
    list.recycle(held);
    assert_eq!(*driver.reloads.borrow(), vec![Some(second)]);
    driver.reloads.borrow_mut().clear();
    assert!(list.take_first().is_none());
    assert_eq!(*driver.reloads.borrow(), vec![Some(second)]);
}
