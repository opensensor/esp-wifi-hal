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
        std::fs::write(out.join("libesp-wifi-hal-i2c.a"), i2c).unwrap();
        println!("cargo:rustc-link-lib=esp-wifi-hal-i2c");
    }
}
