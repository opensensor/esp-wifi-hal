//! Chip-specific initialization, calibration-data handling and ROM callback setup.
//!
//! Calibration and ROM operations remain explicit boundaries. The caller supplies
//! the original input extents and serializes access to the global PHY state.
//! Original-instruction evidence and host checks live in
//! `docs/network/tests/phy-init-oracle`; native bindings own the original state.
#![allow(dead_code)]

pub(crate) trait Access {
    unsafe fn symbol(name: &str) -> usize;
    unsafe fn read(address: usize, width: usize) -> u32;
    unsafe fn write(address: usize, width: usize, value: u32);
    unsafe fn call(target: usize, args: &[usize], returns: bool) -> u32;
    unsafe fn local(pointer: *mut u32, tag: usize, size: usize) -> usize;
    unsafe fn copy(destination: usize, source: usize, size: usize);
    unsafe fn clear(destination: usize, size: usize);
    unsafe fn readonly(offset: usize) -> usize;
    unsafe fn child(kind: u32, args: &[usize]) -> u32;
}
const S3: bool = cfg!(esp32s3);
pub(crate) const PARAM_SIZE: usize = if S3 { 740 } else { 848 };
#[inline(always)]
fn byte(value: u32) -> u32 {
    if S3 { value as u8 as u32 } else { value }
}
#[inline(always)]
unsafe fn param<A: Access>() -> usize {
    unsafe { A::symbol("phy_param") }
}
#[inline(always)]
unsafe fn table<A: Access>() -> usize {
    unsafe { A::read(A::symbol("g_phyFuns"), 4) as usize }
}
#[inline(always)]
unsafe fn slot<A: Access>(offset: usize) -> usize {
    unsafe { A::read(table::<A>() + offset, 4) as usize }
}
#[inline(always)]
unsafe fn invoke<A: Access>(name: &str, args: &[usize], returns: bool) -> u32 {
    unsafe { A::call(A::symbol(name), args, returns) }
}
#[inline(always)]
unsafe fn callback<A: Access>(offset: usize, args: &[usize], returns: bool) -> u32 {
    unsafe { A::call(slot::<A>(offset), args, returns) }
}

#[inline(always)]
pub(crate) unsafe fn callbacks<A: Access>() {
    macro_rules! patches {
        ($table:expr; $(($offset:expr,$name:literal)),* $(,)?) => {
            $(A::write($table+$offset,4,A::symbol($name) as u32);)*
        };
    }
    unsafe {
        let t = invoke::<A>("phy_get_romfuncs", &[], true) as usize;
        A::write(A::symbol("g_phyFuns"), 4, t as u32);
        if S3 {
            patches!(t;
                (0x144, "ram_temp_to_power"),
                (0x208, "ram_pll_vol_cal"),
                (0x264, "ram_wifi_set_tx_gain"),
                (0x228, "ram_wifi_get_tx_gain"),
                (0x218, "ram_bt_get_tx_gain"),
                (0x15c, "ram_get_i2c_hostid"),
                (0x268, "ram_txpwr_cal_track"),
                (0x224, "ram_wifi_tx_dig_gain"),
                (8, "ram_disable_wifi_agc"),
                (12, "ram_enable_wifi_agc"),
                (0x128, "ram_read_sar2_code"),
                (0x22c, "ram_fe_i2c_reg_renew"),
                (0x20c, "ram_write_pll_cap"),
                (0x288, "ram_bt_track_tx_power"),
                (0x28c, "ram_wifi_track_tx_power"),
                (0x1e4, "ram_tsens_code_read"),
                (0x258, "ram_tsens_temp_read"),
                (0xc8, "ram_set_pbus_reg"),
                (0x204, "ram_phy_dis_hw_set_freq"),
                (0x200, "ram_phy_en_hw_set_freq"),
                (0x80, "ram_set_noise_floor"),
                (0x270, "ram_bt_set_tx_gain"),
                (0x18c, "ram_chip_i2c_writeReg"),
                (0x16c, "ram_chip_i2c_readReg"),
                (0x254, "ram_phy_i2c_init1"),
                (0x234, "ram_i2c_master_reset"),
                (0xfc, "ram_set_chan_cal_interp"),
                (0x54, "spur_coef_cfg_new"),
                (0x100, "ram_set_txcap_reg"),
                (0xf0, "ram_iq_est_enable"),
            );
            invoke::<A>("rom_phy_param_addr", &[param::<A>()], false);
        } else {
            let version = invoke::<A>("chip726_phyrom_version_num", &[], true);
            A::write(A::symbol("new_rom.4621"), 1, version);
            invoke::<A>("rom_phy_param_addr", &[param::<A>()], false);
            let version = A::read(A::symbol("new_rom.4621"), 1);
            let t = table::<A>();
            if version == 0 {
                patches!(t;
                    (0xb8, "rom_agc_reg_init"),
                    (0xbc, "rom_bb_reg_init"),
                    (0xe0, "rom_phy_xpd_rf"),
                    (0x114, "rom_set_txcap_reg"),
                    (0x124, "rom_write_txrate_power_offset"),
                    (0x1ec, "rom_pbus_xpd_tx_on"),
                    (0x1fc, "rom_open_i2c_xpd"),
                    (0x208, "rom_tsens_code_read"),
                    (0x48, "rom_set_tx_dig_gain"),
                    (0xec, "rom_txbbgain_to_index"),
                    (0xf0, "rom_index_to_txbbgain"),
                );
            } else {
                patches!(t;
                    (0x288, "ram1_wifi_set_tx_gain"),
                    (0x24c, "rom1_wifi_get_tx_gain"),
                    (0x23c, "rom1_bt_get_tx_gain_new"),
                    (0x28c, "rom1_txpwr_cal_track"),
                    (0x248, "rom1_wifi_tx_dig_gain"),
                );
            }
            let t = table::<A>();
            patches!(t;
                (0x180, "rom1_get_i2c_hostid"),
                (8, "rom1_disable_wifi_agc"),
                (12, "rom1_enable_wifi_agc"),
                (0x14c, "rom1_read_sar2_code"),
                (0x250, "ram1_fe_i2c_reg_renew"),
                (0x228, "ram1_phy_dis_hw_set_freq"),
                (0x224, "rom1_phy_en_hw_set_freq"),
                (0x8c, "rom1_set_noise_floor"),
                (0xa8, "rom1_tx_paon_set"),
                (0x1b0, "rom1_chip_i2c_writeReg"),
                (0x190, "rom1_chip_i2c_readReg"),
                (0x278, "rom1_phy_i2c_init1"),
                (0x258, "rom1_i2c_master_reset"),
                (0xd4, "ram1_set_pbus_reg"),
                (0x27c, "rom1_tsens_temp_read"),
                (0x210, "phy_get_tsens_value"),
                (0x130, "phy_set_tsens_power"),
                (0x138, "phy_i2c_enter_critical"),
                (0x30, "phy_i2c_exit_critical"),
                (0x1c0, "ram_pbus_force_mode"),
                (0x128, "rom1_get_rate_fcc_index"),
                (0x144, "ram_pkdet_vol_start"),
                (0x104, "ram_iq_est_enable"),
            );
        }
    }
}

#[inline(always)]
pub(crate) unsafe fn package<A: Access>() -> u32 {
    unsafe { (A::read(0x60007050, 4) >> 21) & 7 }
}
#[inline(always)]
pub(crate) unsafe fn chip_version<A: Access>() {
    unsafe {
        let v = A::child(14, &[]);
        A::write(param::<A>() + 525, 1, v);
    }
}
#[inline(always)]
pub(crate) unsafe fn power_limits<A: Access>(input: usize) {
    unsafe {
        let mut storage = core::mem::MaybeUninit::<[u32; 7]>::uninit();
        let b = A::local(storage.as_mut_ptr().cast(), 0, 28);
        A::copy(b + 14, A::readonly(0), 14);
        A::copy(b, A::readonly(14), 14);
        for i in 0..14 {
            let index = if A::read(param::<A>() + 525, 1) == 1 {
                0
            } else {
                14
            };
            let v = A::read(b + index + i, 1);
            A::write(input + 2 + i, 1, v);
        }
    }
}
#[inline(always)]
pub(crate) unsafe fn init_param<A: Access>(input: usize) {
    unsafe {
        let p = param::<A>();
        let mut storage = core::mem::MaybeUninit::<[u32; 5]>::uninit();
        let b = A::local(storage.as_mut_ptr().cast(), 1, 20);
        if S3 {
            A::clear(b, 20);
        }
        seed_defaults::<A>(b, if S3 { 0 } else { 2 });
        if !S3 {
            A::write(b + 16, 4, 0);
        }
        let v = A::read(input, 1);
        A::write(p + 242, 1, v);
        let v = A::read(input + 1, 1);
        A::write(p + 243, 1, v);
        if S3 {
            A::child(13, &[b]);
        }
        for i in 2..16 {
            let v = A::read(input + i, 1);
            let limit = A::read(b + i, 1);
            A::write(p + 242 + i, 1, v);
            if (v as i8 as i32) > limit as i32 {
                A::write(p + 242 + i, 1, limit);
            }
        }
        let v = A::read(input + 18, 1);
        A::write(p + 260, 1, v);
        let ctrl = A::symbol("chip7_phy_init_ctrl");
        for group in 0..3 {
            for i in 0..14 {
                let v = A::read(input + 19 + 14 * group + i, 1);
                A::write(ctrl + 14 * group + i, 1, v);
            }
        }
        for i in 0..9 {
            let v = A::read(input + 61 + i, 1);
            A::write(p + 261 + i, 1, v);
        }
        let high = A::read(input + 70, 1);
        let low = A::read(input + 71, 1);
        A::write(p + 280, 2, (high << 8) | low);
        let v = A::read(input + 72, 1);
        A::write(p + 282, 1, v);
        let high = A::read(input + 73, 1);
        let low = A::read(input + 74, 1);
        A::write(p + 284, 2, ((high & 127) << 8) | low);
        let v = A::read(input + 75, 1);
        A::write(p + 286, 1, v);
        let v = A::read(input + 76, 1);
        A::write(p + 287, 1, v);
    }
}
#[inline(always)]
pub(crate) unsafe fn transfer<A: Access>(data: usize, save: u32) {
    unsafe {
        let p = param::<A>();
        for i in (0..PARAM_SIZE).step_by(4) {
            if byte(save) != 0 {
                // Reload for each byte, as the original does.
                for shift in 0..4 {
                    let v = A::read(p + i, 4);
                    A::write(data + 12 + i + shift, 1, v >> (shift * 8));
                }
            } else {
                let v = callback::<A>(if S3 { 0x98 } else { 0xa4 }, &[data + 12 + i], true);
                A::write(p + i, 4, v);
            }
        }
    }
}
#[inline(always)]
pub(crate) unsafe fn recovery<A: Access>(data: usize) {
    unsafe {
        let p = param::<A>();
        A::copy(p + 288, data + 300, if S3 { 236 } else { 244 });
        let first = A::read(data + 230, 2);
        if S3 {
            let second = A::read(data + 232, 2);
            A::write(p + 218, 2, first);
            A::write(p + 220, 2, second);
        } else {
            A::write(p + 218, 2, first);
            let second = A::read(data + 232, 2);
            A::write(p + 220, 2, second);
        }
    }
}
#[inline(always)]
pub(crate) unsafe fn backup<A: Access>(data: usize) {
    unsafe {
        A::child(4, &[data, 1]);
    }
}
#[inline(always)]
pub(crate) unsafe fn check<A: Access>(
    check_only: u32,
    data: usize,
    _input: usize,
    version: u32,
) -> u32 {
    unsafe {
        A::child(3, &[data, version as usize]);
        let mut sum = 0u32;
        for i in (0..PARAM_SIZE + 12).step_by(4) {
            sum = sum.wrapping_add(callback::<A>(
                if S3 { 0x98 } else { 0xa4 },
                &[data + i],
                true,
            ));
        }
        let expected = !sum;
        let actual = callback::<A>(
            if S3 { 0x98 } else { 0xa4 },
            &[data + PARAM_SIZE + 12],
            true,
        );
        if byte(check_only) != 0 {
            (expected != actual) as u32
        } else {
            for i in 0..4 {
                A::write(data + PARAM_SIZE + 12 + i, 1, expected >> (i * 8));
            }
            0
        }
    }
}
#[inline(always)]
pub(crate) unsafe fn level<A: Access>() {
    unsafe {
        let p = param::<A>();
        let mode = A::read(p + 162, 1);
        if mode.wrapping_sub(16) & 255 > 1 {
            return;
        }
        A::write(p + 163, 1, 9);
        A::write(p + 164, 1, 6);
        if mode != 17 {
            return;
        }
        A::write(p + 344, 4, 0x0b040d0b);
        A::write(p + 348, 4, 0x0d0b040d);
        A::write(p + 352, 1, 4);
        for i in (744..796).step_by(4) {
            A::write(p + i, 4, 0x01000100);
        }
        for i in (540..708).step_by(4) {
            A::write(p + i, 4, 0x01000100);
        }
        let flags = A::read(p + 288, 4);
        A::write(p + 288, 4, flags | 0x1c4400);
    }
}
#[inline(always)]
pub(crate) unsafe fn txcap<A: Access>() {
    unsafe {
        let p = param::<A>();
        let index = (A::read(p + 498, 1) >> 2).min(2) as usize;
        let high = A::read(p + 189, 1) & !15;
        let b = A::read(p + 345 + index * 3, 1);
        let c = A::read(p + 346 + index * 3, 1);
        let a = A::read(p + 344 + index * 3, 1);
        A::write(p + 189, 1, high | a);
        A::write(p + 190, 1, (c << 4) | b);
    }
}
#[inline(always)]
pub(crate) unsafe fn mac_data<A: Access>(data: usize, version: u32) {
    unsafe {
        for i in 0..4 {
            A::write(data + i, 1, version >> (i * 8));
        }
    }
}
#[inline(always)]
unsafe fn pulse_reset<A: Access>() {
    unsafe {
        let v = A::read(0x6000e130, 4);
        A::write(0x6000e130, 4, v & !0x20000);
        let v = A::read(0x6000e130, 4);
        A::write(0x6000e130, 4, v | 0x20000);
    }
}
#[inline(always)]
pub(crate) unsafe fn rf<A: Access>() {
    unsafe {
        let p = param::<A>();
        if S3 {
            A::child(15, &[]);
        }
        let bias = if S3 { 1 } else { A::read(p + 536, 1) };
        invoke::<A>("bias_reg_set", &[bias as usize], false);
        callback::<A>(if S3 { 0x1d8 } else { 0x1fc }, &[], false);
        invoke::<A>("i2c_bbpll_set", &[], false);
        pulse_reset::<A>();
        callback::<A>(if S3 { 0xa0 } else { 0xac }, &[], false);
        callback::<A>(if S3 { 0xa8 } else { 0xb4 }, &[], false);
        let dac = A::read(p + 170, 1);
        invoke::<A>(
            if S3 {
                "tsens_read_init_new"
            } else {
                "rom2_tsens_read_init1"
            },
            &[S3 as usize, dac as usize],
            false,
        );
        callback::<A>(if S3 { 0x13c } else { 0x160 }, &[], false);
        if S3 {
            callback::<A>(0x22c, &[], false);
        } else {
            invoke::<A>("ram1_fe_i2c_reg_renew", &[], false);
        }
        let v = A::read(0x60006110, 4);
        A::write(0x60006110, 4, v & !0x300);
        callback::<A>(if S3 { 0x1b0 } else { 0x1d4 }, &[], false);
        let mut storage = core::mem::MaybeUninit::<[u32; 2]>::uninit();
        let b = A::local(storage.as_mut_ptr().cast(), 2, 8);
        if S3 {
            let a = A::read(A::readonly(28), 2);
            let c = A::read(A::readonly(30), 2);
            A::write(b, 2, a);
            let d = A::read(A::readonly(32), 2);
            let e = A::read(A::readonly(34), 2);
            A::write(b + 4, 2, d);
            A::write(b + 6, 2, e);
            let t = table::<A>();
            A::write(b + 2, 2, c);
            let f = A::read(t + 0x1cc, 4) as usize;
            A::call(f, &[b], false);
        } else {
            let a = A::read(A::readonly(0), 4);
            let c = A::read(A::readonly(4), 4);
            A::write(b, 4, a);
            A::write(b + 4, 4, c);
            callback::<A>(0x1f0, &[b], false);
        }
        for offset in if S3 {
            [0x1c4, 0x1bc, 0x1b4]
        } else {
            [0x1e8, 0x1e0, 0x1d8]
        } {
            callback::<A>(offset, &[], false);
        }
        invoke::<A>("phy_get_i2c_data", &[], false);
        if S3 {
            callback::<A>(0x254, &[], false);
        } else {
            invoke::<A>("rom1_phy_i2c_init1", &[], false);
        }
        invoke::<A>("rc_cal", &[], false);
        invoke::<A>("phy_i2c_init2", &[], false);
        invoke::<A>("set_chan_freq_hw_init", &[2, 4], false);
    }
}
#[inline(always)]
pub(crate) unsafe fn bb<A: Access>() {
    unsafe {
        let p = param::<A>();
        invoke::<A>("phy_set_pwdet_power", &[1], false);
        if !S3 {
            A::child(9, &[]);
            invoke::<A>("txcal_gain_check", &[], false);
        }
        if A::read(p + 288, 4) & 0x10000 == 0 {
            invoke::<A>("set_pbus_mem", &[], false);
            let v = A::read(p + 288, 4);
            A::write(p + 288, 4, v | 0x10000);
        }
        if S3 {
            invoke::<A>("tx_gain_set", &[], false);
        }
        if A::read(p + 288, 4) & 0x80000 == 0 {
            invoke::<A>("txdc_cal_init", &[p + 292, 15, 32, 0], false);
            let v = A::read(p + 288, 4);
            A::write(p + 288, 4, v | 0x80000);
        }
        invoke::<A>("pwdet_code_cal", &[], false);
        invoke::<A>("tx_cap_init", &[], false);
        invoke::<A>("freq_i2c_data_write", &[], false);
        invoke::<A>("txpwr_offset", &[0], false);
        invoke::<A>("tx_pwctrl_init", &[0], false);
        invoke::<A>("txiq_cal_init", &[], false);
        callback::<A>(if S3 { 0x110 } else { 0x124 }, &[], false);
        invoke::<A>("bt_tx_gain_init", &[], false);
        if S3 {
            callback::<A>(0x258, &[], false);
        } else {
            invoke::<A>("rom1_tsens_temp_read", &[], false);
        }
        invoke::<A>("phy_rx_table_init", &[], false);
        invoke::<A>("rfrx_sat_rst", &[0], false);
        invoke::<A>("phy_check_rx_sat", &[], false);
        invoke::<A>("set_rx_gain_table", &[2437, 0], false);
        invoke::<A>("rfrx_sat_rst", &[1], false);
        if S3 {
            callback::<A>(0x248, &[], false);
        } else {
            invoke::<A>("rom_phy_reg_init", &[], false);
        }
        invoke::<A>("rx_11b_opt", &[1], false);
        if S3 {
            let seed = if A::read(p + 729, 1) != 0 { 76 } else { 37 };
            invoke::<A>("phy_set_tx_seed", &[seed], false);
        }
        callback::<A>(4, &[], false);
        if S3 {
            invoke::<A>("phy_2448m_spur_pwr", &[0], false);
        }
        A::write(p + 356, 2, (-384i32) as u32);
        A::write(p + 504, 2, (-384i32) as u32);
        invoke::<A>("chip_v7_set_chan", &[11, 0], false);
        invoke::<A>("phy_set_pwdet_power", &[0], false);
        if A::read(p + if S3 { 679 } else { 804 }, 1) != 0 {
            invoke::<A>("phy_wifi_enable_set", &[0], false);
        }
    }
}
#[inline(always)]
pub(crate) unsafe fn close<A: Access>() {
    unsafe {
        let p = param::<A>();
        if S3 {
            if A::read(p + 674, 1) == 0 {
                callback::<A>(0x258, &[], false);
            }
            callback::<A>(0xd4, &[], false);
            invoke::<A>("bias_reg_set", &[0], false);
        } else {
            callback::<A>(0xe0, &[], false);
            invoke::<A>("bias_dreg_i2c_set", &[0], false);
        }
        callback::<A>(
            if S3 { 0x190 } else { 0x1b4 },
            &[103, (!S3) as usize, 2, 6],
            false,
        );
        if S3 {
            callback::<A>(0x240, &[1], false);
        } else {
            invoke::<A>("rom_phy_bbpll_cal", &[1], false);
        }
        callback::<A>(if S3 { 0x204 } else { 0x228 }, &[], false);
        if S3 {
            A::write(p + 675, 1, 1);
        }
    }
}
#[inline(always)]
pub(crate) unsafe fn wakeup<A: Access>() {
    unsafe {
        let p = param::<A>();
        let saved = callback::<A>(if S3 { 0x160 } else { 0x184 }, &[], true);
        invoke::<A>(
            if S3 {
                "bias_reg_set"
            } else {
                "bias_dreg_i2c_set"
            },
            &[1],
            false,
        );
        pulse_reset::<A>();
        callback::<A>(if S3 { 0x204 } else { 0x228 }, &[], false);
        if S3 {
            invoke::<A>("phy_set_tsens_power", &[1], false);
        } else {
            let dac = A::read(p + 170, 1);
            invoke::<A>("rom2_tsens_read_init1", &[0, dac as usize], false);
        }
        let v = A::read(0x60006110, 4);
        A::write(0x60006110, 4, (v & !0x300) | 0x200);
        for i in 0..2 {
            let t = table::<A>();
            let (f, v) = if S3 && i == 0 {
                let f = A::read(t + 0x190, 4) as usize;
                (f, A::read(p + 209 + i, 1))
            } else {
                let v = A::read(p + 209 + i, 1);
                (A::read(t + if S3 { 0x190 } else { 0x1b4 }, 4) as usize, v)
            };
            A::call(f, &[102, 0, 9 + i, v as usize], false);
        }
        callback::<A>(if S3 { 0xc8 } else { 0xd4 }, &[], false);
        callback::<A>(if S3 { 0xa8 } else { 0xb4 }, &[], false);
        if S3 {
            callback::<A>(0x22c, &[], false);
        } else {
            invoke::<A>("ram1_fe_i2c_reg_renew", &[], false);
        }
        callback::<A>(if S3 { 0x110 } else { 0x124 }, &[], false);
        if S3 {
            callback::<A>(0x224, &[p + 442], false);
            callback::<A>(0x214, &[p + 426], false);
        } else {
            invoke::<A>("rom1_wifi_tx_dig_gain", &[p + 442], false);
            invoke::<A>("rom_bt_tx_dig_gain", &[p + 426], false);
        }
        callback::<A>(if S3 { 0xc0 } else { 0xcc }, &[], false);
        callback::<A>(if S3 { 0x13c } else { 0x160 }, &[], false);
        callback::<A>(if S3 { 0x1d8 } else { 0x1fc }, &[], false);
        if S3 {
            callback::<A>(0x254, &[], false);
        } else {
            invoke::<A>("rom1_phy_i2c_init1", &[], false);
        }
        let t = table::<A>();
        let v = A::read(p + 498, 1);
        let f = A::read(t + if S3 { 0xcc } else { 0xd8 }, 4) as usize;
        A::call(f, &[v as usize], false);
        if S3 {
            callback::<A>(0x248, &[], false);
        } else {
            invoke::<A>("rom_phy_reg_init", &[], false);
        }
        invoke::<A>("rx_11b_opt", &[1], false);
        if S3 {
            callback::<A>(0x24c, &[0], false);
        } else {
            invoke::<A>("rom_set_chan_reg", &[0], false);
        }
        invoke::<A>("wait_freq_set_busy", &[], false);
        invoke::<A>("phy_i2c_bbtop_wakeup", &[], false);
        let v = A::read(0x60006110, 4);
        A::write(0x60006110, 4, v & !0x200);
        callback::<A>(4, &[], false);
        callback::<A>(if S3 { 0x200 } else { 0x224 }, &[], false);
        if S3 {
            callback::<A>(0x240, &[0], false);
        } else {
            invoke::<A>("rom_phy_bbpll_cal", &[0], false);
        }
        let enabled;
        if S3 {
            A::write(p + 675, 1, 0);
            A::write(p + 674, 1, 0);
            enabled = A::read(p + 679, 1);
        } else {
            enabled = A::read(p + 804, 1);
            A::write(p + 800, 1, 0);
            A::write(p + 799, 1, 0);
        }
        if enabled != 0 {
            invoke::<A>("phy_wifi_enable_set", &[0], false);
        }
        callback::<A>(if S3 { 0x164 } else { 0x188 }, &[saved as usize], false);
    }
}
#[inline(always)]
pub(crate) unsafe fn check_value<A: Access>(data: usize, reference: usize, compare: u32) -> u32 {
    unsafe {
        let p = param::<A>();
        if byte(compare) == 0 {
            A::child(5, &[data]);
            for (source, dest, count, width) in [
                (292, 0, 20, 2),
                (386, 40, 12, 2),
                (332, 64, 6, 2),
                (384, 76, 1, 2),
                (370, 78, 3, 1),
                (374, 81, 3, 1),
                (344, 84, 9, 1),
            ] {
                for i in 0..count {
                    let v = A::read(p + source + i * width, width);
                    A::write(reference + dest + i * width, width, v);
                }
            }
            return 0;
        }
        let mut differences = 0u32;
        for (source, dest, count) in [(292, 0, 5), (386, 40, 3)] {
            for i in 0..count {
                for j in 0..2 {
                    let t = table::<A>();
                    let (a, b) = if S3 {
                        let b = A::read(p + source + i * 8 + j * 2, 2);
                        (A::read(reference + dest + i * 8 + j * 2, 2), b)
                    } else {
                        let a = A::read(reference + dest + i * 8 + j * 2, 2);
                        (a, A::read(p + source + i * 8 + j * 2, 2))
                    };
                    let f = A::read(t + if S3 { 0xec } else { 0x100 }, 4) as usize;
                    if A::call(f, &[a.wrapping_sub(b) as usize], true) as i32 > 4 {
                        differences = (differences + 1) & 65535;
                    }
                }
            }
        }
        let mut first_storage = core::mem::MaybeUninit::<u32>::uninit();
        let mut second_storage = core::mem::MaybeUninit::<u32>::uninit();
        let first = A::local(first_storage.as_mut_ptr(), 3, 2);
        let second = A::local(second_storage.as_mut_ptr(), 4, 2);
        for (source, dest, count, mode) in [(332, 64, 2, 0), (336, 68, 4, 1), (384, 76, 1, 0)] {
            for i in 0..count {
                let v = A::read(reference + dest + i * 2, 2);
                invoke::<A>("get_iq_value", &[first, v as usize, mode], false);
                let v = A::read(p + source + i * 2, 2);
                invoke::<A>("get_iq_value", &[second, v as usize, mode], false);
                for j in 0..2 {
                    let t;
                    let a;
                    let b;
                    if S3 {
                        a = A::read(first + j, 1);
                        t = table::<A>();
                        b = A::read(second + j, 1);
                    } else {
                        t = table::<A>();
                        a = A::read(first + j, 1);
                        b = A::read(second + j, 1);
                    }
                    let f = A::read(t + if S3 { 0xec } else { 0x100 }, 4) as usize;
                    let delta = (a as i8 as i32).wrapping_sub(b as i8 as i32);
                    if A::call(f, &[delta as u32 as usize], true) as i32 > 4 {
                        differences = (differences + 1) & 65535;
                    }
                }
            }
        }
        for (source, dest, count, is_signed) in
            [(370, 78, 3, true), (374, 81, 3, true), (344, 84, 9, false)]
        {
            for i in 0..count {
                let t = table::<A>();
                let a;
                let b;
                if S3 && !is_signed {
                    b = A::read(p + source + i, 1);
                    a = A::read(reference + dest + i, 1);
                } else {
                    a = A::read(reference + dest + i, 1);
                    b = A::read(p + source + i, 1);
                }
                let f = A::read(t + if S3 { 0xec } else { 0x100 }, 4) as usize;
                let delta = if is_signed {
                    (a as i8 as i32).wrapping_sub(b as i8 as i32) as u32
                } else {
                    a.wrapping_sub(b)
                };
                if A::call(f, &[delta as usize], true) as i32 > 4 {
                    differences = (differences + 1) & 65535;
                }
            }
        }
        differences
    }
}
#[inline(always)]
pub(crate) unsafe fn register<A: Access>(input: usize, data: usize, mode: u32) -> u32 {
    unsafe {
        let p = param::<A>();
        let mut defaults = core::mem::MaybeUninit::<[u32; 32]>::uninit();
        let d = A::local(defaults.as_mut_ptr().cast(), 5, 128);
        A::clear(d, 128);
        let mut scratch = core::mem::MaybeUninit::<[u32; 24]>::uninit();
        let s = A::local(scratch.as_mut_ptr().cast(), 6, 96);
        seed_defaults::<A>(d, if S3 { 0 } else { 2 });
        if S3 {
            A::child(15, &[]);
            A::child(13, &[d]);
        } else {
            A::write(d, 1, 2);
            A::write(p + 162, 1, mode);
        }
        A::child(0, &[]);
        let mut mode = byte(mode);
        callback::<A>(if S3 { 0x204 } else { 0x228 }, &[], false);
        if S3 {
            callback::<A>(0x234, &[], false);
        } else {
            invoke::<A>("rom1_i2c_master_reset", &[], false);
        }
        let cold = A::read(p + 229, 1) == 0;
        if cold {
            A::child(2, &[if input == 0 { d } else { input }]);
        }
        let mut status = 0;
        // S3 reloads the initialized flag even when the first read was nonzero.
        if (S3 || cold) && A::read(p + 229, 1) == 0 {
            let version = invoke::<A>("phy_get_rf_cal_version", &[], true);
            status = A::child(8, &[1, data, input, version as usize]);
            if mode == 1 && status != 0 {
                mode = 2;
            }
            if mode == 1 {
                A::child(5, &[data]);
                let flags = A::read(p + 288, 4);
                A::write(p + 288, 4, flags & 0xfffefddf);
            } else {
                if status == 0 {
                    A::child(6, &[data, s, 0]);
                }
                A::write(p + 288, 4, 0);
            }
        }
        let flags = A::read(p + 288, 4);
        A::child(1, &[]);
        A::child(10, &[]);
        invoke::<A>(
            "get_temp_init",
            &[
                (((flags >> 5) ^ 1) & 1) as usize,
                (((flags >> 20) ^ 1) & 1) as usize,
            ],
            false,
        );
        if A::read(p + 229, 1) == 0 && mode != 1 {
            if status == 0 {
                status = (A::child(6, &[data, s, 1]) != 0) as u32;
            }
            A::child(7, &[data]);
            let version = invoke::<A>("phy_get_rf_cal_version", &[], true);
            A::child(8, &[0, data, input, version as usize]);
        }
        if A::read(p + 229, 1) == 0 && A::read(p + 286, 1) != 0 {
            invoke::<A>("chip_v7_set_chan_offset", &[0], false);
        }
        if S3 {
            callback::<A>(0x240, &[0], false);
        } else {
            invoke::<A>("rom_phy_bbpll_cal", &[0], false);
        }
        A::write(0x6001cd0c, 4, 23);
        callback::<A>(if S3 { 0x188 } else { 0x1ac }, &[99, 1, 0], false);
        A::write(p + 229, 1, 1);
        callback::<A>(if S3 { 0x200 } else { 0x224 }, &[], false);
        status
    }
}

#[inline(always)]
pub(crate) unsafe fn dispatch<A: Access>(kind: u32, a: &[usize]) -> u32 {
    unsafe {
        match kind {
            0 => callbacks::<A>(),
            1 => rf::<A>(),
            2 => init_param::<A>(a[0]),
            3 => mac_data::<A>(a[0], a[1] as u32),
            4 => transfer::<A>(a[0], a[1] as u32),
            5 => recovery::<A>(a[0]),
            6 => return check_value::<A>(a[0], a[1], a[2] as u32),
            7 => backup::<A>(a[0]),
            8 => return check::<A>(a[0] as u32, a[1], a[2], a[3] as u32),
            9 => level::<A>(),
            10 => bb::<A>(),
            11 => return register::<A>(a[0], a[1], a[2] as u32),
            12 => txcap::<A>(),
            13 => power_limits::<A>(a[0]),
            14 => return package::<A>(),
            15 => chip_version::<A>(),
            16 => wakeup::<A>(),
            17 => close::<A>(),
            _ => panic!("unknown PHY init boundary"),
        }
        0
    }
}

#[inline(always)]
unsafe fn seed_defaults<A: Access>(b: usize, first: u32) {
    unsafe {
        A::write(b, 1, first);
        A::write(b + 1, 1, 0);
        A::write(b + 2, 1, 82);
        A::write(b + 3, 1, 82);
        A::write(b + 4, 1, 80);
        A::write(b + 5, 1, 76);
        A::write(b + 6, 1, 76);
        A::write(b + 7, 1, 72);
        A::write(b + 8, 1, 76);
        A::write(b + 9, 1, 72);
        A::write(b + 10, 1, 72);
        A::write(b + 11, 1, 70);
        A::write(b + 12, 1, 74);
        A::write(b + 13, 1, 70);
        A::write(b + 14, 1, 70);
        A::write(b + 15, 1, 68);
    }
}

include!("phy_init_native.rs");
