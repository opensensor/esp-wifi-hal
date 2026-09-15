/// Indicates, that the chip has the WIFI_PWR interrupt.
const PWR_INTERRUPT_PRESENT: &str = "pwr_interrupt_present";
/// The OS adapter is required by MAC initialization and retained binary helpers.
/// Populate callbacks used by each chip even when the rest of the table is unused.
const OSI_FUNCS_REQUIRED: &str = "osi_funcs_required";
const NOMAC_CHANNEL_SET: &str = "nomac_channel_set";
/// `g_osi_funcs_p` is a variable in the ROM data area (parts of the Wi-Fi stack live in ROM), so it
/// must be written at runtime instead of being defined by us.
const OSI_FUNCS_IN_ROM: &str = "osi_funcs_in_rom";
/// The TSF counters, TSF timers and TBTT generator are known.
const TSF_TIMER_PRESENT: &str = "tsf_timer_present";

const ESP32S3_META: &[&str] = &[
    "esp32s3",
    PWR_INTERRUPT_PRESENT,
    OSI_FUNCS_REQUIRED,
    "osi_funcs_in_rom",
];

const ESP32_META: &[&str] = &["esp32", NOMAC_CHANNEL_SET];
const ESP32S2_META: &[&str] = &["esp32s2", PWR_INTERRUPT_PRESENT, OSI_FUNCS_REQUIRED];
const ESP32C3_META: &[&str] = &[
    "esp32c3",
    PWR_INTERRUPT_PRESENT,
    OSI_FUNCS_REQUIRED,
    OSI_FUNCS_IN_ROM,
    TSF_TIMER_PRESENT,
];

fn main() {
    let meta = if cfg!(feature = "esp32") {
        ESP32_META
    } else if cfg!(feature = "esp32s2") {
        ESP32S2_META
    } else if cfg!(feature = "esp32s3") {
        ESP32S3_META
    } else if cfg!(feature = "esp32c3") {
        ESP32C3_META
    } else {
        panic!("You must select exactly one chip.");
    };
    for item in meta {
        println!("cargo:rustc-cfg={item}");
    }

    if cfg!(any(feature = "esp32c3", feature = "esp32s3")) {
        // Strong assignments redirect same-object calls as well as external
        // references and installed callbacks. --wrap only handles undefined
        // references, leaving C3 get_temp_init's vendor reader active.
        // As in esp-phy, an archive-named linker script propagates to consumers.
        let out = std::path::PathBuf::from(std::env::var_os("OUT_DIR").unwrap());
        let names = if cfg!(feature = "esp32c3") {
            [
                "tsens_dac_to_index",
                "tsens_dac_cal1",
                "tsens_temp_read1",
                "phy_get_tsens_value",
                "rom1_tsens_temp_read",
            ]
        } else {
            [
                "tsens_dac_to_index",
                "tsens_dac_cal_new",
                "ram_tsens_temp_read_new",
                "phy_get_tsens_value",
                "ram_tsens_temp_read",
            ]
        };
        let mut script = String::new();
        for (original, suffix) in names
            .into_iter()
            .zip(["decode", "range", "inner", "forward", "outer"])
        {
            script.push_str(&format!(
                "EXTERN(__opensensor_tsens_{suffix});\n{original} = __opensensor_tsens_{suffix};\n"
            ));
        }
        let lifecycle: &[(&str, &str)] = if cfg!(feature = "esp32c3") {
            &[
                ("phy_set_tsens_power", "power"),
                ("phy_xpd_tsens", "xpd"),
                ("rom2_tsens_read_init1", "init"),
                ("rom2_temp_to_power1", "temp_to_power"),
                ("get_temp_init", "get_init"),
                ("phy_tsens_attribute", "attribute"),
            ]
        } else {
            &[
                ("phy_set_tsens_power", "power"),
                ("phy_xpd_tsens", "xpd"),
                ("tsens_read_init_new", "init"),
                ("ram_tsens_code_read", "code"),
                ("ram_temp_to_power", "temp_to_power"),
                ("get_temp_init", "get_init"),
                ("phy_tsens_attribute", "attribute"),
            ]
        };
        for (original, suffix) in lifecycle {
            script.push_str(&format!(
                "EXTERN(__opensensor_tsens_{suffix});\n{original} = __opensensor_tsens_{suffix};\n"
            ));
        }
        std::fs::write(out.join("libesp-wifi-hal-temperature.a"), script).unwrap();
        println!("cargo:rustc-link-search={}", out.display());
        println!("cargo:rustc-link-lib=esp-wifi-hal-temperature");

        // Redirect the PBUS member's internal save call as well as external
        // references and callback installation, then let section GC remove it.
        let mut reg = String::new();
        for (original, suffix) in [
            if cfg!(feature = "esp32c3") {
                ("ram1_set_pbus_reg", "pbus")
            } else {
                ("ram_set_pbus_reg", "pbus")
            },
            if cfg!(feature = "esp32c3") {
                ("rom1_tx_paon_set", "paon")
            } else {
                ("ram_wifi_tx_dig_gain_reg", "digital_gain")
            },
            ("btbb_wifi_bb_cfg2", "btbb"),
            ("rx_agc_reg_opt", "agc_options"),
            ("rx_11b_opt", "options_11b"),
            if cfg!(feature = "esp32c3") {
                ("rom1_disable_wifi_agc", "disable_agc")
            } else {
                ("ram_disable_wifi_agc", "disable_agc")
            },
            if cfg!(feature = "esp32c3") {
                ("rom1_enable_wifi_agc", "enable_agc")
            } else {
                ("ram_enable_wifi_agc", "enable_agc")
            },
            if cfg!(feature = "esp32c3") {
                ("ram1_fe_i2c_reg_renew", "renew")
            } else {
                ("ram_fe_i2c_reg_renew", "renew")
            },
            ("phy_wifi_enable_set", "wifi_enable"),
            ("txiq_set_reg", "tx_iq"),
            ("rxiq_set_reg", "rx_iq"),
            ("start_tx_tone_step", "start_tone"),
            ("stop_tx_tone", "stop_tone"),
            if cfg!(feature = "esp32c3") {
                ("rom1_set_noise_floor", "noise_floor")
            } else {
                ("ram_set_noise_floor", "noise_floor")
            },
            ("phy_freq_correct", "frequency_correct"),
            ("force_txrx_off", "force_off"),
        ] {
            reg.push_str(&format!(
                "EXTERN(__opensensor_reg_{suffix});\n{original} = __opensensor_reg_{suffix};\n"
            ));
        }
        for (original, suffix) in [
            ("gen_rx_gain_table", "generate"),
            ("wr_rx_gain_mem", "write_memory"),
            ("set_rx_gain_param", "set_param"),
            ("set_rx_gain_table", "set_table"),
            ("phy_rx_table_init", "initialize"),
        ] {
            reg.push_str(&format!("EXTERN(__opensensor_rx_gain_{suffix});\n{original} = __opensensor_rx_gain_{suffix};\n"));
        }
        let tx_gain_names: &[(&str, &str)] = if cfg!(feature = "esp32c3") {
            &[
                ("rom1_wifi_tx_dig_gain", "digital"),
                ("bt_chan_pwr_interp", "interpolate"),
                ("rom1_get_rate_fcc_index", "fcc"),
                ("rom1_get_chan_target_power", "limits"),
                ("rom2_get_tx_gain_value1", "lookup"),
                ("rom1_bt_get_tx_gain_new", "bt_get"),
                ("rom1_wifi_get_tx_gain", "wifi_get"),
                ("ram1_wifi_set_tx_gain", "wifi_set"),
                ("rom1_bt_set_tx_gain", "bt_set"),
                ("bt_tx_gain_init", "bt_initialize"),
                ("txcal_gain_check", "calibration_tables"),
            ]
        } else {
            &[
                ("ram_wifi_tx_dig_gain", "digital"),
                ("bt_chan_pwr_interp", "interpolate"),
                ("ram_get_rate_fcc_index", "fcc"),
                ("ram_get_chan_target_power", "limits"),
                ("get_tx_gain_value", "lookup"),
                ("ram_bt_get_tx_gain", "bt_get"),
                ("ram_wifi_get_tx_gain", "wifi_get"),
                ("ram_wifi_set_tx_gain", "wifi_set"),
                ("ram_bt_set_tx_gain", "bt_set"),
                ("bt_tx_gain_init", "bt_initialize"),
                ("tx_gain_set", "calibration_tables"),
                ("dig_gain_check", "dig_check"),
            ]
        };
        for (original, suffix) in tx_gain_names {
            reg.push_str(&format!("EXTERN(__opensensor_tx_gain_{suffix});\n{original} = __opensensor_tx_gain_{suffix};\n"));
        }
        for (original, suffix) in [
            ("rfrx_sat_rst", "reset"),
            ("phy_force_rx_gain_trig", "trigger"),
            ("ram_iq_est_enable", "estimate"),
            ("phy_check_rx_sat", "check"),
        ] {
            reg.push_str(&format!("EXTERN(__opensensor_rx_controls_{suffix});\n{original} = __opensensor_rx_controls_{suffix};\n"));
        }
        for (original, suffix) in [
            ("rxiq_get_mis", "mismatch"),
            ("rxiq_cover_mg_mp", "correct"),
        ] {
            reg.push_str(&format!(
                "EXTERN(__opensensor_rx_iq_{suffix});\n{original} = __opensensor_rx_iq_{suffix};\n"
            ));
        }
        for (original, suffix) in [("rfcal_rxiq", "sample"), ("get_rfcal_rxiq_data", "collect")] {
            reg.push_str(&format!(
                "EXTERN(__opensensor_rf_iq_{suffix});\n{original} = __opensensor_rf_iq_{suffix};\n"
            ));
        }
        let minimum = if cfg!(feature = "esp32c3") {
            "rxdc_est_min_new"
        } else {
            "rxdc_est_min"
        };
        for (original, suffix) in [(minimum, "minimum"), ("rx_chan_dc_sort", "sort")] {
            reg.push_str(&format!(
                "EXTERN(__opensensor_rx_dc_{suffix});\n{original} = __opensensor_rx_dc_{suffix};\n"
            ));
        }
        let one_step = if cfg!(feature = "esp32c3") {
            "pbus_rx_dco_cal_1step_new"
        } else {
            "pbus_rx_dco_cal_1step"
        };
        for (original, suffix) in [("pbus_rx_dco_cal", "general"), (one_step, "one_step")] {
            reg.push_str(&format!("EXTERN(__opensensor_dc_search_{suffix});\n{original} = __opensensor_dc_search_{suffix};\n"));
        }
        for (original, suffix) in [("set_rx_gain_cal_iq", "iq"), ("set_rx_gain_cal_dc", "dc")] {
            reg.push_str(&format!("EXTERN(__opensensor_rx_gain_cal_{suffix});\n{original} = __opensensor_rx_gain_cal_{suffix};\n"));
        }

        if cfg!(feature = "esp32s3") {
            for (original, suffix) in [("spur_coef_cfg_new", "config"), ("phy_2448m_spur_pwr", "power")] {
                reg.push_str(&format!("EXTERN(__opensensor_spur_{suffix});\n{original} = __opensensor_spur_{suffix};\n"));
            }
        }

        for (original, suffix) in [("pwdet_ref_code", "reference"), ("pwdet_code_cal", "calibrate")] {
            reg.push_str(&format!("EXTERN(__opensensor_tx_detector_{suffix});\n{original} = __opensensor_tx_detector_{suffix};\n"));
        }

        for (original, suffix) in [("txiq_get_mis_pwr", "measure"), ("get_power_atten", "attenuation")] {
            reg.push_str(&format!("EXTERN(__opensensor_txiq_{suffix});\n{original} = __opensensor_txiq_{suffix};\n"));
        }

        for (original, suffix) in [("txiq_cal_init", "initialize"), ("bt_txiq_cal", "bluetooth")] {
            reg.push_str(&format!("EXTERN(__opensensor_txiq_{suffix});\n{original} = __opensensor_txiq_{suffix};\n"));
        }

        let init_names: &[(&str, &str)] = if cfg!(feature = "esp32c3") {
            &[
                ("phy_get_romfunc_addr", "callbacks"),
                ("rf_init", "rf"),
                ("register_chipv7_phy_init_param", "init_param"),
                ("phy_set_mac_data", "mac_data"),
                ("phy_rfcal_data_sub", "transfer"),
                ("rf_cal_data_recovery", "recovery"),
                ("phy_rfcal_data_check_value", "check_value"),
                ("rf_cal_data_backup", "backup"),
                ("phy_rfcal_data_check", "check"),
                ("rf_cal_level_check", "level"),
                ("bb_init", "bb"),
                ("register_chipv7_phy", "register"),
                ("get_txcap_data", "txcap"),
                ("ram1_phy_wakeup_init", "wakeup"),
                ("ram1_phy_close_rf", "close"),
            ]
        } else {
            &[
                ("phy_get_romfunc_addr", "callbacks"),
                ("rf_init", "rf"),
                ("register_chipv7_phy_init_param", "init_param"),
                ("phy_set_mac_data", "mac_data"),
                ("phy_rfcal_data_sub", "transfer"),
                ("rf_cal_data_recovery", "recovery"),
                ("phy_rfcal_data_check_value", "check_value"),
                ("rf_cal_data_backup", "backup"),
                ("phy_rfcal_data_check", "check"),
                ("bb_init", "bb"),
                ("register_chipv7_phy", "register"),
                ("pwr_limit_force", "power_limits"),
                ("esp_phy_efuse_get_chip_ver_pkg", "package"),
                ("get_chip_version", "chip_version"),
                ("ram_phy_wakeup_init", "wakeup"),
                ("ram_phy_close_rf", "close"),
            ]
        };
        for (old, suffix) in init_names {
            reg.push_str(&format!(
                "EXTERN(__opensensor_init_{suffix});\n{old} = __opensensor_init_{suffix};\n"
            ));
        }
        for (old, suffix) in [
            ("phy_param", "parameters"),
            ("chip7_phy_init_ctrl", "control"),
            ("g_phyFuns", "table"),
        ] {
            reg.push_str(&format!(
                "EXTERN(__opensensor_init_{suffix});\n{old} = __opensensor_init_{suffix};\n"
            ));
        }
        std::fs::write(out.join("libesp-wifi-hal-reg.a"), reg).unwrap();
        println!("cargo:rustc-link-lib=esp-wifi-hal-reg");

        let mut pbus = String::new();
        for (original, suffix) in [
            ("txcal_debuge_mode", "debug_mode"),
            ("txcal_work_mode", "work_mode"),
            ("save_pbus_reg", "save"),
            ("set_pbus_mem", "mem"),
        ]
        .into_iter()
        .chain(cfg!(feature = "esp32c3").then_some(("ram_pbus_force_mode", "force_mode")))
        {
            pbus.push_str(&format!(
                "EXTERN(__opensensor_pbus_{suffix});\n{original} = __opensensor_pbus_{suffix};\n"
            ));
        }
        std::fs::write(out.join("libesp-wifi-hal-pbus.a"), pbus).unwrap();
        println!("cargo:rustc-link-lib=esp-wifi-hal-pbus");

        let mut i2c = String::new();
        for (original, suffix) in [
            ("phy_get_i2c_data", "get_data"),
            ("bias_reg_set", "bias"),
            ("i2c_bbpll_set", "bbpll"),
            ("phy_i2c_init2", "init2"),
        ] {
            i2c.push_str(&format!(
                "EXTERN(__opensensor_i2c_{suffix});\n{original} = __opensensor_i2c_{suffix};\n"
            ));
        }
        let iram: &[(&str, &str)] = if cfg!(feature = "esp32c3") {
            &[
                ("phy_i2c_enter_critical", "enter"),
                ("phy_i2c_exit_critical", "exit"),
                ("rom1_get_i2c_hostid", "hostid"),
                ("rom1_chip_i2c_readReg", "read"),
                ("rom1_chip_i2c_writeReg", "write"),
                ("rom1_phy_i2c_init1", "init1"),
                ("phy_i2c_bbtop_wakeup", "wakeup"),
                ("bias_dreg_i2c_set", "bias_dreg"),
            ]
        } else {
            &[
                ("phy_i2c_enter_critical", "enter"),
                ("phy_i2c_exit_critical", "exit"),
                ("ram_get_i2c_hostid", "hostid"),
                ("ram_chip_i2c_readReg", "read"),
                ("ram_chip_i2c_writeReg", "write"),
                ("ram_phy_i2c_init1", "init1"),
                ("phy_i2c_bbtop_wakeup", "wakeup"),
                ("ram_set_txcap_reg", "txcap"),
            ]
        };
        for (original, suffix) in iram {
            i2c.push_str(&format!(
                "EXTERN(__opensensor_i2c_{suffix});\n{original} = __opensensor_i2c_{suffix};\n"
            ));
        }
        std::fs::write(out.join("libesp-wifi-hal-i2c.a"), i2c).unwrap();
        println!("cargo:rustc-link-lib=esp-wifi-hal-i2c");
        let mut api = String::new();
        let mut entries = vec![
            ("phy_wakeup_init", "wakeup"),
            ("phy_close_rf", "close"),
            ("phy_get_rf_cal_version", "calibration_version"),
        ];
        if cfg!(feature = "esp32s3") {
            entries.push(("phy_set_tx_seed", "tx_seed"));
        }
        for (original, suffix) in entries {
            api.push_str(&format!(
                "EXTERN(__opensensor_api_{suffix});\n{original} = __opensensor_api_{suffix};\n"
            ));
        }
        std::fs::write(out.join("libesp-wifi-hal-api.a"), api).unwrap();
        println!("cargo:rustc-link-lib=esp-wifi-hal-api");
        let mut basic = String::new();
        let mut entries = vec![
            (
                if cfg!(feature = "esp32c3") {
                    "rom1_i2c_master_reset"
                } else {
                    "ram_i2c_master_reset"
                },
                "reset",
            ),
            ("chan14_mic_cfg", "channel14"),
        ];
        if cfg!(feature = "esp32s3") {
            entries.push(("ram_set_chan_cal_interp", "interpolate"));
        }
        for (original, suffix) in entries {
            basic.push_str(&format!(
                "EXTERN(__opensensor_basic_{suffix});\n{original} = __opensensor_basic_{suffix};\n"
            ));
        }
        std::fs::write(out.join("libesp-wifi-hal-basic.a"), basic).unwrap();
        println!("cargo:rustc-link-lib=esp-wifi-hal-basic");
        let mut feature = String::new();
        for (original, suffix) in [
            ("phy_dig_reg_backup", "dig"),
            ("phy_freq_mem_backup", "freq"),
            ("phy_set_most_tpw", "power"),
            ("phy_11p_set", "mode"),
        ] {
            feature.push_str(&format!(
                "EXTERN(__opensensor_feature_{suffix});\n{original} = __opensensor_feature_{suffix};\n"
            ));
        }
        std::fs::write(out.join("libesp-wifi-hal-feature.a"), feature).unwrap();
        println!("cargo:rustc-link-lib=esp-wifi-hal-feature");
        let mut debug = String::new();
        for (original, suffix) in [
            ("get_iq_value", "iq"),
            ("get_bias_ref_code", "bias"),
            ("phy_get_vdd33", "voltage"),
        ] {
            debug.push_str(&format!(
                "EXTERN(__opensensor_debug_{suffix});\n{original} = __opensensor_debug_{suffix};\n"
            ));
        }
        std::fs::write(out.join("libesp-wifi-hal-debug.a"), debug).unwrap();
        println!("cargo:rustc-link-lib=esp-wifi-hal-debug");
        let mut pwdet = String::new();
        let mut selected = vec![
            ("phy_set_pwdet_power", "power"),
            ("get_sar_sig_ref", "reference"),
            ("pwdet_tone_start", "tone"),
            ("get_tone_sar_dout", "samples"),
            ("get_fm_sar_dout", "fm"),
            ("txtone_linear_pwr", "linear"),
            ("get_power_db", "db"),
        ];
        if cfg!(feature = "esp32c3") {
            selected.extend([
                ("ram_pkdet_vol_start", "pkdet"),
                ("rom1_read_sar2_code", "read"),
            ]);
        } else {
            selected.push(("ram_read_sar2_code", "read"));
        }
        for (original, suffix) in selected {
            pwdet.push_str(&format!(
                "EXTERN(__opensensor_pwdet_{suffix});\n{original} = __opensensor_pwdet_{suffix};\n"
            ));
        }
        std::fs::write(out.join("libesp-wifi-hal-pwdet.a"), pwdet).unwrap();
        println!("cargo:rustc-link-lib=esp-wifi-hal-pwdet");
        let mut analog = String::new();
        let mut entries = vec![("get_rc_dout", "measurement"), ("rc_cal", "calibrate")];
        if cfg!(feature = "esp32c3") {
            entries.extend([("wifi_ht20", "ht20"), ("wifi_ht40", "ht40")]);
        }
        for (original, suffix) in entries {
            analog.push_str(&format!("EXTERN(__opensensor_analog_{suffix});\n{original} = __opensensor_analog_{suffix};\n"));
        }
        std::fs::write(out.join("libesp-wifi-hal-analog.a"), analog).unwrap();
        println!("cargo:rustc-link-lib=esp-wifi-hal-analog");
        let entries = if cfg!(feature = "esp32c3") {
            vec![
                ("rom2_wait_hw_freq_busy", "wait"),
                ("rom2_ulp_ext_code_set", "ulp_set"),
                ("rom2_ulp_code_track", "ulp"),
                ("ram2_rfpll_cap_track", "pll"),
                ("rom1_txpwr_cal_track", "power"),
                ("txpwr_offset", "offset"),
                ("rfcal_track", "rfcal"),
            ]
        } else {
            vec![
                ("wait_hw_freq_busy", "wait"),
                ("ulp_ext_code_set", "ulp_set"),
                ("ulp_code_track", "ulp"),
                ("rfpll_cap_track", "pll"),
                ("ram_txpwr_cal_track", "power"),
                ("txpwr_offset", "offset"),
                ("ram_wifi_track_tx_power", "wifi"),
                ("ram_bt_track_tx_power", "bt"),
            ]
        };
        let mut track = String::new();
        for (original, suffix) in entries {
            track.push_str(&format!(
                "EXTERN(__opensensor_track_{suffix});\n{original} = __opensensor_track_{suffix};\n"
            ));
        }
        std::fs::write(out.join("libesp-wifi-hal-track.a"), track).unwrap();
        println!("cargo:rustc-link-lib=esp-wifi-hal-track");
        let mut entries = vec![
            ("restart_cal", "restart"),
            ("write_rfpll_sdm", "sdm"),
            ("wait_rfpll_cal_end", "wait"),
            ("rfpll_set_freq", "frequency"),
            ("correct_rfpll_offset", "correct_offset"),
            ("rfpll_cap_init_cal", "init_cap"),
            ("set_rfpll_freq", "set"),
            ("set_rf_freq_offset", "set_offset"),
            ("set_channel_rfpll_freq", "set_channel"),
            ("chip_v7_set_chan_misc", "misc"),
            ("chip_v7_set_chan", "channel"),
            ("chip_v7_set_chan_offset", "channel_offset"),
            ("chip_v7_set_chan_ana", "channel_analog"),
        ];
        if cfg!(feature = "esp32c3") {
            entries.extend([
                ("rom2_write_pll_cap", "write_cap"),
                ("rom2_read_pll_cap", "read_cap"),
                ("ram2_rfpll_cap_correct", "correct_cap"),
            ]);
        } else {
            entries.extend([
                ("ram_write_pll_cap", "write_cap"),
                ("read_pll_cap", "read_cap"),
                ("rfpll_cap_correct", "correct_cap"),
                ("phy_set_freq", "phy_frequency"),
                ("ram_pll_vol_cal", "voltage"),
            ]);
        }
        let mut rfpll = String::new();
        for (original, suffix) in entries {
            rfpll.push_str(&format!(
                "EXTERN(__opensensor_rfpll_{suffix});\n{original} = __opensensor_rfpll_{suffix};\n"
            ));
        }
        std::fs::write(out.join("libesp-wifi-hal-rfpll.a"), rfpll).unwrap();
        println!("cargo:rustc-link-lib=esp-wifi-hal-rfpll");
        let mut entries = vec![
            ("wait_freq_set_busy", "wait"),
            ("wr_rf_freq_mem", "memory"),
            ("freq_i2c_write_set", "write_i2c"),
            ("get_rf_freq_init", "initialize"),
            ("freq_get_i2c_data", "read_i2c"),
            ("freq_i2c_data_write", "program_i2c"),
            ("set_chan_freq_hw_init", "hardware_init"),
            ("set_chan_freq_sw_start", "software_start"),
        ];
        if cfg!(feature = "esp32c3") {
            entries.extend([
                ("ram1_phy_dis_hw_set_freq", "disable"),
                ("rom1_phy_en_hw_set_freq", "enable"),
                ("rom2_pll_cap_mem_update", "cap_memory"),
            ]);
        } else {
            entries.extend([
                ("ram_phy_dis_hw_set_freq", "disable"),
                ("ram_phy_en_hw_set_freq", "enable"),
                ("pll_cap_mem_update", "cap_memory"),
            ]);
        }
        let mut hw_freq = String::new();
        for (original, suffix) in entries {
            hw_freq.push_str(&format!(
                "EXTERN(__opensensor_hw_freq_{suffix});\n{original} = __opensensor_hw_freq_{suffix};\n"
            ));
        }
        std::fs::write(out.join("libesp-wifi-hal-hw-freq.a"), hw_freq).unwrap();
        println!("cargo:rustc-link-lib=esp-wifi-hal-hw-freq");
    }
}
