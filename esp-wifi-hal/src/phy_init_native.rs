#[cfg(all(not(test), any(target_arch = "riscv32", target_arch = "xtensa")))]
mod native {
    use super::*;
    use core::ptr::{read_volatile, write_volatile};
    struct Hardware;
    #[repr(C, align(4))]
    struct Parameters([u8; PARAM_SIZE]);
    #[cfg(esp32c3)]
    const fn initial_parameters() -> [u8; PARAM_SIZE] {
        let mut p = [0; PARAM_SIZE];
        p[152] = 100;
        p[156] = 1;
        p[157] = 1;
        p[170] = 2;
        p[174] = 196;
        p[175] = 255;
        p[176] = 75;
        p[178] = 196;
        p[179] = 255;
        p[180] = 75;
        p[182] = 238;
        p[183] = 238;
        p[184] = 238;
        p[185] = 21;
        p[186] = 21;
        p[187] = 21;
        p[209] = 158;
        p[210] = 1;
        p[212] = 64;
        p[213] = 48;
        p[214] = 28;
        p[216] = 80;
        p[228] = 48;
        p[241] = 254;
        p[803] = 1;
        p[832] = 244;
        p[836] = 60;
        p[837] = 50;
        p[838] = 22;
        p
    }
    #[cfg(esp32s3)]
    const fn initial_parameters() -> [u8; PARAM_SIZE] {
        let mut p = [0; PARAM_SIZE];
        p[104] = 127;
        p[105] = 111;
        p[106] = 95;
        p[107] = 79;
        p[108] = 63;
        p[109] = 47;
        p[110] = 31;
        p[111] = 15;
        p[112] = 11;
        p[113] = 7;
        p[114] = 3;
        p[115] = 2;
        p[116] = 1;
        p[118] = 43;
        p[120] = 40;
        p[122] = 35;
        p[124] = 29;
        p[126] = 22;
        p[128] = 13;
        p[132] = 233;
        p[133] = 255;
        p[134] = 222;
        p[135] = 255;
        p[136] = 208;
        p[137] = 255;
        p[138] = 184;
        p[139] = 255;
        p[140] = 176;
        p[141] = 255;
        p[142] = 164;
        p[143] = 255;
        p[144] = 140;
        p[145] = 255;
        p[152] = 100;
        p[156] = 1;
        p[157] = 1;
        p[170] = 2;
        p[174] = 216;
        p[175] = 255;
        p[176] = 95;
        p[178] = 216;
        p[179] = 255;
        p[180] = 85;
        p[182] = 237;
        p[183] = 237;
        p[184] = 237;
        p[185] = 37;
        p[186] = 37;
        p[187] = 37;
        p[209] = 158;
        p[210] = 1;
        p[212] = 59;
        p[213] = 46;
        p[214] = 28;
        p[216] = 80;
        p[228] = 48;
        p[241] = 254;
        p[732] = 48;
        p[733] = 36;
        p[734] = 23;
        p[735] = 6;
        p
    }
    #[unsafe(no_mangle)]
    static mut __opensensor_init_parameters: Parameters = Parameters(initial_parameters());
    #[unsafe(no_mangle)]
    static mut __opensensor_init_control: [u8; 42] = [0; 42];
    #[unsafe(no_mangle)]
    static mut __opensensor_init_table: usize = 0;
    #[cfg(esp32c3)]
    #[unsafe(no_mangle)]
    static mut __opensensor_init_rom_version: u8 = 0;
    #[cfg(esp32c3)]
    static READONLY: [u8; 8] = [0, 1, 0, 1, 0, 1, 0, 1];
    #[cfg(esp32s3)]
    static READONLY: [u8; 36] = [
        82, 82, 80, 76, 76, 72, 76, 72, 72, 70, 74, 70, 70, 68, 80, 80, 76, 74, 74, 70, 74, 70, 70,
        68, 72, 68, 68, 66, 0, 1, 0, 1, 0, 1, 0, 1,
    ];
    impl Access for Hardware {
        #[inline(always)]
        unsafe fn symbol(name: &str) -> usize {
            match name {
                "phy_param" => (&raw const __opensensor_init_parameters) as usize,
                "chip7_phy_init_ctrl" => (&raw const __opensensor_init_control) as usize,
                "g_phyFuns" => (&raw const __opensensor_init_table) as usize,
                #[cfg(esp32c3)]
                "new_rom.4621" => (&raw const __opensensor_init_rom_version) as usize,
                #[cfg(esp32c3)]
                "bias_dreg_i2c_set" => {
                    unsafe extern "C" {
                        fn bias_dreg_i2c_set();
                    }
                    bias_dreg_i2c_set as *const () as usize
                }
                #[cfg(esp32c3)]
                "bias_reg_set" => {
                    unsafe extern "C" {
                        fn bias_reg_set();
                    }
                    bias_reg_set as *const () as usize
                }
                #[cfg(esp32c3)]
                "bt_tx_gain_init" => {
                    unsafe extern "C" {
                        fn bt_tx_gain_init();
                    }
                    bt_tx_gain_init as *const () as usize
                }
                #[cfg(esp32c3)]
                "chip726_phyrom_version_num" => {
                    unsafe extern "C" {
                        fn chip726_phyrom_version_num();
                    }
                    chip726_phyrom_version_num as *const () as usize
                }
                #[cfg(esp32c3)]
                "chip_v7_set_chan" => {
                    unsafe extern "C" {
                        fn chip_v7_set_chan();
                    }
                    chip_v7_set_chan as *const () as usize
                }
                #[cfg(esp32c3)]
                "chip_v7_set_chan_offset" => {
                    unsafe extern "C" {
                        fn chip_v7_set_chan_offset();
                    }
                    chip_v7_set_chan_offset as *const () as usize
                }
                #[cfg(esp32c3)]
                "freq_i2c_data_write" => {
                    unsafe extern "C" {
                        fn freq_i2c_data_write();
                    }
                    freq_i2c_data_write as *const () as usize
                }
                #[cfg(esp32c3)]
                "get_iq_value" => {
                    unsafe extern "C" {
                        fn get_iq_value();
                    }
                    get_iq_value as *const () as usize
                }
                #[cfg(esp32c3)]
                "get_temp_init" => {
                    unsafe extern "C" {
                        fn get_temp_init();
                    }
                    get_temp_init as *const () as usize
                }
                #[cfg(esp32c3)]
                "i2c_bbpll_set" => {
                    unsafe extern "C" {
                        fn i2c_bbpll_set();
                    }
                    i2c_bbpll_set as *const () as usize
                }
                #[cfg(esp32c3)]
                "memcpy" => {
                    unsafe extern "C" {
                        fn memcpy();
                    }
                    memcpy as *const () as usize
                }
                #[cfg(esp32c3)]
                "memset" => {
                    unsafe extern "C" {
                        fn memset();
                    }
                    memset as *const () as usize
                }
                #[cfg(esp32c3)]
                "phy_check_rx_sat" => {
                    unsafe extern "C" {
                        fn phy_check_rx_sat();
                    }
                    phy_check_rx_sat as *const () as usize
                }
                #[cfg(esp32c3)]
                "phy_get_i2c_data" => {
                    unsafe extern "C" {
                        fn phy_get_i2c_data();
                    }
                    phy_get_i2c_data as *const () as usize
                }
                #[cfg(esp32c3)]
                "phy_get_rf_cal_version" => {
                    unsafe extern "C" {
                        fn phy_get_rf_cal_version();
                    }
                    phy_get_rf_cal_version as *const () as usize
                }
                #[cfg(esp32c3)]
                "phy_get_romfuncs" => {
                    unsafe extern "C" {
                        fn phy_get_romfuncs();
                    }
                    phy_get_romfuncs as *const () as usize
                }
                #[cfg(esp32c3)]
                "phy_get_tsens_value" => {
                    unsafe extern "C" {
                        fn phy_get_tsens_value();
                    }
                    phy_get_tsens_value as *const () as usize
                }
                #[cfg(esp32c3)]
                "phy_i2c_bbtop_wakeup" => {
                    unsafe extern "C" {
                        fn phy_i2c_bbtop_wakeup();
                    }
                    phy_i2c_bbtop_wakeup as *const () as usize
                }
                #[cfg(esp32c3)]
                "phy_i2c_enter_critical" => {
                    unsafe extern "C" {
                        fn phy_i2c_enter_critical();
                    }
                    phy_i2c_enter_critical as *const () as usize
                }
                #[cfg(esp32c3)]
                "phy_i2c_exit_critical" => {
                    unsafe extern "C" {
                        fn phy_i2c_exit_critical();
                    }
                    phy_i2c_exit_critical as *const () as usize
                }
                #[cfg(esp32c3)]
                "phy_i2c_init2" => {
                    unsafe extern "C" {
                        fn phy_i2c_init2();
                    }
                    phy_i2c_init2 as *const () as usize
                }
                #[cfg(esp32c3)]
                "phy_rx_table_init" => {
                    unsafe extern "C" {
                        fn phy_rx_table_init();
                    }
                    phy_rx_table_init as *const () as usize
                }
                #[cfg(esp32c3)]
                "phy_set_pwdet_power" => {
                    unsafe extern "C" {
                        fn phy_set_pwdet_power();
                    }
                    phy_set_pwdet_power as *const () as usize
                }
                #[cfg(esp32c3)]
                "phy_set_tsens_power" => {
                    unsafe extern "C" {
                        fn phy_set_tsens_power();
                    }
                    phy_set_tsens_power as *const () as usize
                }
                #[cfg(esp32c3)]
                "phy_wifi_enable_set" => {
                    unsafe extern "C" {
                        fn phy_wifi_enable_set();
                    }
                    phy_wifi_enable_set as *const () as usize
                }
                #[cfg(esp32c3)]
                "pwdet_code_cal" => {
                    unsafe extern "C" {
                        fn pwdet_code_cal();
                    }
                    pwdet_code_cal as *const () as usize
                }
                #[cfg(esp32c3)]
                "ram1_fe_i2c_reg_renew" => {
                    unsafe extern "C" {
                        fn ram1_fe_i2c_reg_renew();
                    }
                    ram1_fe_i2c_reg_renew as *const () as usize
                }
                #[cfg(esp32c3)]
                "ram1_phy_dis_hw_set_freq" => {
                    unsafe extern "C" {
                        fn ram1_phy_dis_hw_set_freq();
                    }
                    ram1_phy_dis_hw_set_freq as *const () as usize
                }
                #[cfg(esp32c3)]
                "ram1_set_pbus_reg" => {
                    unsafe extern "C" {
                        fn ram1_set_pbus_reg();
                    }
                    ram1_set_pbus_reg as *const () as usize
                }
                #[cfg(esp32c3)]
                "ram1_wifi_set_tx_gain" => {
                    unsafe extern "C" {
                        fn ram1_wifi_set_tx_gain();
                    }
                    ram1_wifi_set_tx_gain as *const () as usize
                }
                #[cfg(esp32c3)]
                "ram_iq_est_enable" => {
                    unsafe extern "C" {
                        fn ram_iq_est_enable();
                    }
                    ram_iq_est_enable as *const () as usize
                }
                #[cfg(esp32c3)]
                "ram_pbus_force_mode" => {
                    unsafe extern "C" {
                        fn ram_pbus_force_mode();
                    }
                    ram_pbus_force_mode as *const () as usize
                }
                #[cfg(esp32c3)]
                "ram_pkdet_vol_start" => {
                    unsafe extern "C" {
                        fn ram_pkdet_vol_start();
                    }
                    ram_pkdet_vol_start as *const () as usize
                }
                #[cfg(esp32c3)]
                "rc_cal" => {
                    unsafe extern "C" {
                        fn rc_cal();
                    }
                    rc_cal as *const () as usize
                }
                #[cfg(esp32c3)]
                "rfrx_sat_rst" => {
                    unsafe extern "C" {
                        fn rfrx_sat_rst();
                    }
                    rfrx_sat_rst as *const () as usize
                }
                #[cfg(esp32c3)]
                "rom1_bt_get_tx_gain_new" => {
                    unsafe extern "C" {
                        fn rom1_bt_get_tx_gain_new();
                    }
                    rom1_bt_get_tx_gain_new as *const () as usize
                }
                #[cfg(esp32c3)]
                "rom1_chip_i2c_readReg" => {
                    unsafe extern "C" {
                        fn rom1_chip_i2c_readReg();
                    }
                    rom1_chip_i2c_readReg as *const () as usize
                }
                #[cfg(esp32c3)]
                "rom1_chip_i2c_writeReg" => {
                    unsafe extern "C" {
                        fn rom1_chip_i2c_writeReg();
                    }
                    rom1_chip_i2c_writeReg as *const () as usize
                }
                #[cfg(esp32c3)]
                "rom1_disable_wifi_agc" => {
                    unsafe extern "C" {
                        fn rom1_disable_wifi_agc();
                    }
                    rom1_disable_wifi_agc as *const () as usize
                }
                #[cfg(esp32c3)]
                "rom1_enable_wifi_agc" => {
                    unsafe extern "C" {
                        fn rom1_enable_wifi_agc();
                    }
                    rom1_enable_wifi_agc as *const () as usize
                }
                #[cfg(esp32c3)]
                "rom1_get_i2c_hostid" => {
                    unsafe extern "C" {
                        fn rom1_get_i2c_hostid();
                    }
                    rom1_get_i2c_hostid as *const () as usize
                }
                #[cfg(esp32c3)]
                "rom1_get_rate_fcc_index" => {
                    unsafe extern "C" {
                        fn rom1_get_rate_fcc_index();
                    }
                    rom1_get_rate_fcc_index as *const () as usize
                }
                #[cfg(esp32c3)]
                "rom1_i2c_master_reset" => {
                    unsafe extern "C" {
                        fn rom1_i2c_master_reset();
                    }
                    rom1_i2c_master_reset as *const () as usize
                }
                #[cfg(esp32c3)]
                "rom1_phy_en_hw_set_freq" => {
                    unsafe extern "C" {
                        fn rom1_phy_en_hw_set_freq();
                    }
                    rom1_phy_en_hw_set_freq as *const () as usize
                }
                #[cfg(esp32c3)]
                "rom1_phy_i2c_init1" => {
                    unsafe extern "C" {
                        fn rom1_phy_i2c_init1();
                    }
                    rom1_phy_i2c_init1 as *const () as usize
                }
                #[cfg(esp32c3)]
                "rom1_read_sar2_code" => {
                    unsafe extern "C" {
                        fn rom1_read_sar2_code();
                    }
                    rom1_read_sar2_code as *const () as usize
                }
                #[cfg(esp32c3)]
                "rom1_set_noise_floor" => {
                    unsafe extern "C" {
                        fn rom1_set_noise_floor();
                    }
                    rom1_set_noise_floor as *const () as usize
                }
                #[cfg(esp32c3)]
                "rom1_tsens_temp_read" => {
                    unsafe extern "C" {
                        fn rom1_tsens_temp_read();
                    }
                    rom1_tsens_temp_read as *const () as usize
                }
                #[cfg(esp32c3)]
                "rom1_tx_paon_set" => {
                    unsafe extern "C" {
                        fn rom1_tx_paon_set();
                    }
                    rom1_tx_paon_set as *const () as usize
                }
                #[cfg(esp32c3)]
                "rom1_txpwr_cal_track" => {
                    unsafe extern "C" {
                        fn rom1_txpwr_cal_track();
                    }
                    rom1_txpwr_cal_track as *const () as usize
                }
                #[cfg(esp32c3)]
                "rom1_wifi_get_tx_gain" => {
                    unsafe extern "C" {
                        fn rom1_wifi_get_tx_gain();
                    }
                    rom1_wifi_get_tx_gain as *const () as usize
                }
                #[cfg(esp32c3)]
                "rom1_wifi_tx_dig_gain" => {
                    unsafe extern "C" {
                        fn rom1_wifi_tx_dig_gain();
                    }
                    rom1_wifi_tx_dig_gain as *const () as usize
                }
                #[cfg(esp32c3)]
                "rom2_tsens_read_init1" => {
                    unsafe extern "C" {
                        fn rom2_tsens_read_init1();
                    }
                    rom2_tsens_read_init1 as *const () as usize
                }
                #[cfg(esp32c3)]
                "rom_agc_reg_init" => {
                    unsafe extern "C" {
                        fn rom_agc_reg_init();
                    }
                    rom_agc_reg_init as *const () as usize
                }
                #[cfg(esp32c3)]
                "rom_bb_reg_init" => {
                    unsafe extern "C" {
                        fn rom_bb_reg_init();
                    }
                    rom_bb_reg_init as *const () as usize
                }
                #[cfg(esp32c3)]
                "rom_bt_filter_reg" => {
                    unsafe extern "C" {
                        fn rom_bt_filter_reg();
                    }
                    rom_bt_filter_reg as *const () as usize
                }
                #[cfg(esp32c3)]
                "rom_bt_tx_dig_gain" => {
                    unsafe extern "C" {
                        fn rom_bt_tx_dig_gain();
                    }
                    rom_bt_tx_dig_gain as *const () as usize
                }
                #[cfg(esp32c3)]
                "rom_index_to_txbbgain" => {
                    unsafe extern "C" {
                        fn rom_index_to_txbbgain();
                    }
                    rom_index_to_txbbgain as *const () as usize
                }
                #[cfg(esp32c3)]
                "rom_open_i2c_xpd" => {
                    unsafe extern "C" {
                        fn rom_open_i2c_xpd();
                    }
                    rom_open_i2c_xpd as *const () as usize
                }
                #[cfg(esp32c3)]
                "rom_pbus_xpd_tx_on" => {
                    unsafe extern "C" {
                        fn rom_pbus_xpd_tx_on();
                    }
                    rom_pbus_xpd_tx_on as *const () as usize
                }
                #[cfg(esp32c3)]
                "rom_phy_ant_init" => {
                    unsafe extern "C" {
                        fn rom_phy_ant_init();
                    }
                    rom_phy_ant_init as *const () as usize
                }
                #[cfg(esp32c3)]
                "rom_phy_bbpll_cal" => {
                    unsafe extern "C" {
                        fn rom_phy_bbpll_cal();
                    }
                    rom_phy_bbpll_cal as *const () as usize
                }
                #[cfg(esp32c3)]
                "rom_phy_param_addr" => {
                    unsafe extern "C" {
                        fn rom_phy_param_addr();
                    }
                    rom_phy_param_addr as *const () as usize
                }
                #[cfg(esp32c3)]
                "rom_phy_reg_init" => {
                    unsafe extern "C" {
                        fn rom_phy_reg_init();
                    }
                    rom_phy_reg_init as *const () as usize
                }
                #[cfg(esp32c3)]
                "rom_phy_xpd_rf" => {
                    unsafe extern "C" {
                        fn rom_phy_xpd_rf();
                    }
                    rom_phy_xpd_rf as *const () as usize
                }
                #[cfg(esp32c3)]
                "rom_set_chan_reg" => {
                    unsafe extern "C" {
                        fn rom_set_chan_reg();
                    }
                    rom_set_chan_reg as *const () as usize
                }
                #[cfg(esp32c3)]
                "rom_set_tx_dig_gain" => {
                    unsafe extern "C" {
                        fn rom_set_tx_dig_gain();
                    }
                    rom_set_tx_dig_gain as *const () as usize
                }
                #[cfg(esp32c3)]
                "rom_set_txcap_reg" => {
                    unsafe extern "C" {
                        fn rom_set_txcap_reg();
                    }
                    rom_set_txcap_reg as *const () as usize
                }
                #[cfg(esp32c3)]
                "rom_tsens_code_read" => {
                    unsafe extern "C" {
                        fn rom_tsens_code_read();
                    }
                    rom_tsens_code_read as *const () as usize
                }
                #[cfg(esp32c3)]
                "rom_txbbgain_to_index" => {
                    unsafe extern "C" {
                        fn rom_txbbgain_to_index();
                    }
                    rom_txbbgain_to_index as *const () as usize
                }
                #[cfg(esp32c3)]
                "rom_wifi_agc_sat_gain" => {
                    unsafe extern "C" {
                        fn rom_wifi_agc_sat_gain();
                    }
                    rom_wifi_agc_sat_gain as *const () as usize
                }
                #[cfg(esp32c3)]
                "rom_write_txrate_power_offset" => {
                    unsafe extern "C" {
                        fn rom_write_txrate_power_offset();
                    }
                    rom_write_txrate_power_offset as *const () as usize
                }
                #[cfg(esp32c3)]
                "rx_11b_opt" => {
                    unsafe extern "C" {
                        fn rx_11b_opt();
                    }
                    rx_11b_opt as *const () as usize
                }
                #[cfg(esp32c3)]
                "set_chan_freq_hw_init" => {
                    unsafe extern "C" {
                        fn set_chan_freq_hw_init();
                    }
                    set_chan_freq_hw_init as *const () as usize
                }
                #[cfg(esp32c3)]
                "set_pbus_mem" => {
                    unsafe extern "C" {
                        fn set_pbus_mem();
                    }
                    set_pbus_mem as *const () as usize
                }
                #[cfg(esp32c3)]
                "set_rx_gain_table" => {
                    unsafe extern "C" {
                        fn set_rx_gain_table();
                    }
                    set_rx_gain_table as *const () as usize
                }
                #[cfg(esp32c3)]
                "tx_cap_init" => {
                    unsafe extern "C" {
                        fn tx_cap_init();
                    }
                    tx_cap_init as *const () as usize
                }
                #[cfg(esp32c3)]
                "tx_pwctrl_init" => {
                    unsafe extern "C" {
                        fn tx_pwctrl_init();
                    }
                    tx_pwctrl_init as *const () as usize
                }
                #[cfg(esp32c3)]
                "txcal_gain_check" => {
                    unsafe extern "C" {
                        fn txcal_gain_check();
                    }
                    txcal_gain_check as *const () as usize
                }
                #[cfg(esp32c3)]
                "txdc_cal_init" => {
                    unsafe extern "C" {
                        fn txdc_cal_init();
                    }
                    txdc_cal_init as *const () as usize
                }
                #[cfg(esp32c3)]
                "txiq_cal_init" => {
                    unsafe extern "C" {
                        fn txiq_cal_init();
                    }
                    txiq_cal_init as *const () as usize
                }
                #[cfg(esp32c3)]
                "txpwr_offset" => {
                    unsafe extern "C" {
                        fn txpwr_offset();
                    }
                    txpwr_offset as *const () as usize
                }
                #[cfg(esp32c3)]
                "wait_freq_set_busy" => {
                    unsafe extern "C" {
                        fn wait_freq_set_busy();
                    }
                    wait_freq_set_busy as *const () as usize
                }
                #[cfg(esp32s3)]
                "bias_reg_set" => {
                    unsafe extern "C" {
                        fn bias_reg_set();
                    }
                    bias_reg_set as *const () as usize
                }
                #[cfg(esp32s3)]
                "bt_tx_gain_init" => {
                    unsafe extern "C" {
                        fn bt_tx_gain_init();
                    }
                    bt_tx_gain_init as *const () as usize
                }
                #[cfg(esp32s3)]
                "chip_v7_set_chan" => {
                    unsafe extern "C" {
                        fn chip_v7_set_chan();
                    }
                    chip_v7_set_chan as *const () as usize
                }
                #[cfg(esp32s3)]
                "chip_v7_set_chan_offset" => {
                    unsafe extern "C" {
                        fn chip_v7_set_chan_offset();
                    }
                    chip_v7_set_chan_offset as *const () as usize
                }
                #[cfg(esp32s3)]
                "freq_i2c_data_write" => {
                    unsafe extern "C" {
                        fn freq_i2c_data_write();
                    }
                    freq_i2c_data_write as *const () as usize
                }
                #[cfg(esp32s3)]
                "get_iq_value" => {
                    unsafe extern "C" {
                        fn get_iq_value();
                    }
                    get_iq_value as *const () as usize
                }
                #[cfg(esp32s3)]
                "get_temp_init" => {
                    unsafe extern "C" {
                        fn get_temp_init();
                    }
                    get_temp_init as *const () as usize
                }
                #[cfg(esp32s3)]
                "i2c_bbpll_set" => {
                    unsafe extern "C" {
                        fn i2c_bbpll_set();
                    }
                    i2c_bbpll_set as *const () as usize
                }
                #[cfg(esp32s3)]
                "memcpy" => {
                    unsafe extern "C" {
                        fn memcpy();
                    }
                    memcpy as *const () as usize
                }
                #[cfg(esp32s3)]
                "memset" => {
                    unsafe extern "C" {
                        fn memset();
                    }
                    memset as *const () as usize
                }
                #[cfg(esp32s3)]
                "phy_2448m_spur_pwr" => {
                    unsafe extern "C" {
                        fn phy_2448m_spur_pwr();
                    }
                    phy_2448m_spur_pwr as *const () as usize
                }
                #[cfg(esp32s3)]
                "phy_check_rx_sat" => {
                    unsafe extern "C" {
                        fn phy_check_rx_sat();
                    }
                    phy_check_rx_sat as *const () as usize
                }
                #[cfg(esp32s3)]
                "phy_get_i2c_data" => {
                    unsafe extern "C" {
                        fn phy_get_i2c_data();
                    }
                    phy_get_i2c_data as *const () as usize
                }
                #[cfg(esp32s3)]
                "phy_get_rf_cal_version" => {
                    unsafe extern "C" {
                        fn phy_get_rf_cal_version();
                    }
                    phy_get_rf_cal_version as *const () as usize
                }
                #[cfg(esp32s3)]
                "phy_get_romfuncs" => {
                    unsafe extern "C" {
                        fn phy_get_romfuncs();
                    }
                    phy_get_romfuncs as *const () as usize
                }
                #[cfg(esp32s3)]
                "phy_i2c_bbtop_wakeup" => {
                    unsafe extern "C" {
                        fn phy_i2c_bbtop_wakeup();
                    }
                    phy_i2c_bbtop_wakeup as *const () as usize
                }
                #[cfg(esp32s3)]
                "phy_i2c_init2" => {
                    unsafe extern "C" {
                        fn phy_i2c_init2();
                    }
                    phy_i2c_init2 as *const () as usize
                }
                #[cfg(esp32s3)]
                "phy_rx_table_init" => {
                    unsafe extern "C" {
                        fn phy_rx_table_init();
                    }
                    phy_rx_table_init as *const () as usize
                }
                #[cfg(esp32s3)]
                "phy_set_pwdet_power" => {
                    unsafe extern "C" {
                        fn phy_set_pwdet_power();
                    }
                    phy_set_pwdet_power as *const () as usize
                }
                #[cfg(esp32s3)]
                "phy_set_tsens_power" => {
                    unsafe extern "C" {
                        fn phy_set_tsens_power();
                    }
                    phy_set_tsens_power as *const () as usize
                }
                #[cfg(esp32s3)]
                "phy_set_tx_seed" => {
                    unsafe extern "C" {
                        fn phy_set_tx_seed();
                    }
                    phy_set_tx_seed as *const () as usize
                }
                #[cfg(esp32s3)]
                "phy_wifi_enable_set" => {
                    unsafe extern "C" {
                        fn phy_wifi_enable_set();
                    }
                    phy_wifi_enable_set as *const () as usize
                }
                #[cfg(esp32s3)]
                "pwdet_code_cal" => {
                    unsafe extern "C" {
                        fn pwdet_code_cal();
                    }
                    pwdet_code_cal as *const () as usize
                }
                #[cfg(esp32s3)]
                "ram_bt_get_tx_gain" => {
                    unsafe extern "C" {
                        fn ram_bt_get_tx_gain();
                    }
                    ram_bt_get_tx_gain as *const () as usize
                }
                #[cfg(esp32s3)]
                "ram_bt_set_tx_gain" => {
                    unsafe extern "C" {
                        fn ram_bt_set_tx_gain();
                    }
                    ram_bt_set_tx_gain as *const () as usize
                }
                #[cfg(esp32s3)]
                "ram_bt_track_tx_power" => {
                    unsafe extern "C" {
                        fn ram_bt_track_tx_power();
                    }
                    ram_bt_track_tx_power as *const () as usize
                }
                #[cfg(esp32s3)]
                "ram_chip_i2c_readReg" => {
                    unsafe extern "C" {
                        fn ram_chip_i2c_readReg();
                    }
                    ram_chip_i2c_readReg as *const () as usize
                }
                #[cfg(esp32s3)]
                "ram_chip_i2c_writeReg" => {
                    unsafe extern "C" {
                        fn ram_chip_i2c_writeReg();
                    }
                    ram_chip_i2c_writeReg as *const () as usize
                }
                #[cfg(esp32s3)]
                "ram_disable_wifi_agc" => {
                    unsafe extern "C" {
                        fn ram_disable_wifi_agc();
                    }
                    ram_disable_wifi_agc as *const () as usize
                }
                #[cfg(esp32s3)]
                "ram_enable_wifi_agc" => {
                    unsafe extern "C" {
                        fn ram_enable_wifi_agc();
                    }
                    ram_enable_wifi_agc as *const () as usize
                }
                #[cfg(esp32s3)]
                "ram_fe_i2c_reg_renew" => {
                    unsafe extern "C" {
                        fn ram_fe_i2c_reg_renew();
                    }
                    ram_fe_i2c_reg_renew as *const () as usize
                }
                #[cfg(esp32s3)]
                "ram_get_i2c_hostid" => {
                    unsafe extern "C" {
                        fn ram_get_i2c_hostid();
                    }
                    ram_get_i2c_hostid as *const () as usize
                }
                #[cfg(esp32s3)]
                "ram_i2c_master_reset" => {
                    unsafe extern "C" {
                        fn ram_i2c_master_reset();
                    }
                    ram_i2c_master_reset as *const () as usize
                }
                #[cfg(esp32s3)]
                "ram_iq_est_enable" => {
                    unsafe extern "C" {
                        fn ram_iq_est_enable();
                    }
                    ram_iq_est_enable as *const () as usize
                }
                #[cfg(esp32s3)]
                "ram_phy_dis_hw_set_freq" => {
                    unsafe extern "C" {
                        fn ram_phy_dis_hw_set_freq();
                    }
                    ram_phy_dis_hw_set_freq as *const () as usize
                }
                #[cfg(esp32s3)]
                "ram_phy_en_hw_set_freq" => {
                    unsafe extern "C" {
                        fn ram_phy_en_hw_set_freq();
                    }
                    ram_phy_en_hw_set_freq as *const () as usize
                }
                #[cfg(esp32s3)]
                "ram_phy_i2c_init1" => {
                    unsafe extern "C" {
                        fn ram_phy_i2c_init1();
                    }
                    ram_phy_i2c_init1 as *const () as usize
                }
                #[cfg(esp32s3)]
                "ram_pll_vol_cal" => {
                    unsafe extern "C" {
                        fn ram_pll_vol_cal();
                    }
                    ram_pll_vol_cal as *const () as usize
                }
                #[cfg(esp32s3)]
                "ram_read_sar2_code" => {
                    unsafe extern "C" {
                        fn ram_read_sar2_code();
                    }
                    ram_read_sar2_code as *const () as usize
                }
                #[cfg(esp32s3)]
                "ram_set_chan_cal_interp" => {
                    unsafe extern "C" {
                        fn ram_set_chan_cal_interp();
                    }
                    ram_set_chan_cal_interp as *const () as usize
                }
                #[cfg(esp32s3)]
                "ram_set_noise_floor" => {
                    unsafe extern "C" {
                        fn ram_set_noise_floor();
                    }
                    ram_set_noise_floor as *const () as usize
                }
                #[cfg(esp32s3)]
                "ram_set_pbus_reg" => {
                    unsafe extern "C" {
                        fn ram_set_pbus_reg();
                    }
                    ram_set_pbus_reg as *const () as usize
                }
                #[cfg(esp32s3)]
                "ram_set_txcap_reg" => {
                    unsafe extern "C" {
                        fn ram_set_txcap_reg();
                    }
                    ram_set_txcap_reg as *const () as usize
                }
                #[cfg(esp32s3)]
                "ram_temp_to_power" => {
                    unsafe extern "C" {
                        fn ram_temp_to_power();
                    }
                    ram_temp_to_power as *const () as usize
                }
                #[cfg(esp32s3)]
                "ram_tsens_code_read" => {
                    unsafe extern "C" {
                        fn ram_tsens_code_read();
                    }
                    ram_tsens_code_read as *const () as usize
                }
                #[cfg(esp32s3)]
                "ram_tsens_temp_read" => {
                    unsafe extern "C" {
                        fn ram_tsens_temp_read();
                    }
                    ram_tsens_temp_read as *const () as usize
                }
                #[cfg(esp32s3)]
                "ram_txpwr_cal_track" => {
                    unsafe extern "C" {
                        fn ram_txpwr_cal_track();
                    }
                    ram_txpwr_cal_track as *const () as usize
                }
                #[cfg(esp32s3)]
                "ram_wifi_get_tx_gain" => {
                    unsafe extern "C" {
                        fn ram_wifi_get_tx_gain();
                    }
                    ram_wifi_get_tx_gain as *const () as usize
                }
                #[cfg(esp32s3)]
                "ram_wifi_set_tx_gain" => {
                    unsafe extern "C" {
                        fn ram_wifi_set_tx_gain();
                    }
                    ram_wifi_set_tx_gain as *const () as usize
                }
                #[cfg(esp32s3)]
                "ram_wifi_track_tx_power" => {
                    unsafe extern "C" {
                        fn ram_wifi_track_tx_power();
                    }
                    ram_wifi_track_tx_power as *const () as usize
                }
                #[cfg(esp32s3)]
                "ram_wifi_tx_dig_gain" => {
                    unsafe extern "C" {
                        fn ram_wifi_tx_dig_gain();
                    }
                    ram_wifi_tx_dig_gain as *const () as usize
                }
                #[cfg(esp32s3)]
                "ram_write_pll_cap" => {
                    unsafe extern "C" {
                        fn ram_write_pll_cap();
                    }
                    ram_write_pll_cap as *const () as usize
                }
                #[cfg(esp32s3)]
                "rc_cal" => {
                    unsafe extern "C" {
                        fn rc_cal();
                    }
                    rc_cal as *const () as usize
                }
                #[cfg(esp32s3)]
                "rfrx_sat_rst" => {
                    unsafe extern "C" {
                        fn rfrx_sat_rst();
                    }
                    rfrx_sat_rst as *const () as usize
                }
                #[cfg(esp32s3)]
                "rom_phy_param_addr" => {
                    unsafe extern "C" {
                        fn rom_phy_param_addr();
                    }
                    rom_phy_param_addr as *const () as usize
                }
                #[cfg(esp32s3)]
                "rom_phy_reg_init" => {
                    unsafe extern "C" {
                        fn rom_phy_reg_init();
                    }
                    rom_phy_reg_init as *const () as usize
                }
                #[cfg(esp32s3)]
                "rom_phy_xpd_rf" => {
                    unsafe extern "C" {
                        fn rom_phy_xpd_rf();
                    }
                    rom_phy_xpd_rf as *const () as usize
                }
                #[cfg(esp32s3)]
                "rx_11b_opt" => {
                    unsafe extern "C" {
                        fn rx_11b_opt();
                    }
                    rx_11b_opt as *const () as usize
                }
                #[cfg(esp32s3)]
                "set_chan_freq_hw_init" => {
                    unsafe extern "C" {
                        fn set_chan_freq_hw_init();
                    }
                    set_chan_freq_hw_init as *const () as usize
                }
                #[cfg(esp32s3)]
                "set_pbus_mem" => {
                    unsafe extern "C" {
                        fn set_pbus_mem();
                    }
                    set_pbus_mem as *const () as usize
                }
                #[cfg(esp32s3)]
                "set_rx_gain_table" => {
                    unsafe extern "C" {
                        fn set_rx_gain_table();
                    }
                    set_rx_gain_table as *const () as usize
                }
                #[cfg(esp32s3)]
                "spur_coef_cfg_new" => {
                    unsafe extern "C" {
                        fn spur_coef_cfg_new();
                    }
                    spur_coef_cfg_new as *const () as usize
                }
                #[cfg(esp32s3)]
                "tsens_read_init_new" => {
                    unsafe extern "C" {
                        fn tsens_read_init_new();
                    }
                    tsens_read_init_new as *const () as usize
                }
                #[cfg(esp32s3)]
                "tx_cap_init" => {
                    unsafe extern "C" {
                        fn tx_cap_init();
                    }
                    tx_cap_init as *const () as usize
                }
                #[cfg(esp32s3)]
                "tx_gain_set" => {
                    unsafe extern "C" {
                        fn tx_gain_set();
                    }
                    tx_gain_set as *const () as usize
                }
                #[cfg(esp32s3)]
                "tx_pwctrl_init" => {
                    unsafe extern "C" {
                        fn tx_pwctrl_init();
                    }
                    tx_pwctrl_init as *const () as usize
                }
                #[cfg(esp32s3)]
                "txdc_cal_init" => {
                    unsafe extern "C" {
                        fn txdc_cal_init();
                    }
                    txdc_cal_init as *const () as usize
                }
                #[cfg(esp32s3)]
                "txiq_cal_init" => {
                    unsafe extern "C" {
                        fn txiq_cal_init();
                    }
                    txiq_cal_init as *const () as usize
                }
                #[cfg(esp32s3)]
                "txpwr_offset" => {
                    unsafe extern "C" {
                        fn txpwr_offset();
                    }
                    txpwr_offset as *const () as usize
                }
                #[cfg(esp32s3)]
                "wait_freq_set_busy" => {
                    unsafe extern "C" {
                        fn wait_freq_set_busy();
                    }
                    wait_freq_set_busy as *const () as usize
                }
                _ => panic!("unknown initialization symbol"),
            }
        }
        #[inline(always)]
        unsafe fn read(a: usize, w: usize) -> u32 {
            unsafe {
                match w {
                    1 => read_volatile(a as *const u8) as u32,
                    2 => read_volatile(a as *const u16) as u32,
                    4 => read_volatile(a as *const u32),
                    _ => unreachable!(),
                }
            }
        }
        #[inline(always)]
        unsafe fn write(a: usize, w: usize, v: u32) {
            unsafe {
                match w {
                    1 => write_volatile(a as *mut u8, v as u8),
                    2 => write_volatile(a as *mut u16, v as u16),
                    4 => write_volatile(a as *mut u32, v),
                    _ => unreachable!(),
                }
            }
        }
        #[inline(always)]
        unsafe fn local(p: *mut u32, _tag: usize, _size: usize) -> usize {
            p as usize
        }
        #[inline(always)]
        unsafe fn readonly(offset: usize) -> usize {
            (&raw const READONLY) as usize + offset
        }
        #[inline(always)]
        unsafe fn clear(d: usize, n: usize) {
            unsafe {
                unsafe extern "C" {
                    fn memset(d: *mut u8, v: i32, n: usize) -> *mut u8;
                }
                memset(d as *mut u8, 0, n);
            }
        }
        #[inline(always)]
        unsafe fn copy(d: usize, s: usize, n: usize) {
            unsafe {
                unsafe extern "C" {
                    fn memcpy(d: *mut u8, s: *const u8, n: usize) -> *mut u8;
                }
                memcpy(d as *mut u8, s as *const u8, n);
            }
        }
        #[inline(always)]
        unsafe fn call(target: usize, a: &[usize], returns: bool) -> u32 {
            unsafe {
                if returns {
                    match a.len() {
                        0 => core::mem::transmute::<usize, unsafe extern "C" fn() -> u32>(target)(),
                        1 => core::mem::transmute::<usize, unsafe extern "C" fn(usize) -> u32>(
                            target,
                        )(a[0]),
                        2 => {
                            core::mem::transmute::<usize, unsafe extern "C" fn(usize, usize) -> u32>(
                                target,
                            )(a[0], a[1])
                        }
                        3 => core::mem::transmute::<
                            usize,
                            unsafe extern "C" fn(usize, usize, usize) -> u32,
                        >(target)(a[0], a[1], a[2]),
                        4 => core::mem::transmute::<
                            usize,
                            unsafe extern "C" fn(usize, usize, usize, usize) -> u32,
                        >(target)(a[0], a[1], a[2], a[3]),
                        _ => unreachable!(),
                    }
                } else {
                    match a.len() {
                        0 => core::mem::transmute::<usize, unsafe extern "C" fn()>(target)(),
                        1 => {
                            core::mem::transmute::<usize, unsafe extern "C" fn(usize)>(target)(a[0])
                        }
                        2 => core::mem::transmute::<usize, unsafe extern "C" fn(usize, usize)>(
                            target,
                        )(a[0], a[1]),
                        3 => {
                            core::mem::transmute::<usize, unsafe extern "C" fn(usize, usize, usize)>(
                                target,
                            )(a[0], a[1], a[2])
                        }
                        4 => core::mem::transmute::<
                            usize,
                            unsafe extern "C" fn(usize, usize, usize, usize),
                        >(target)(a[0], a[1], a[2], a[3]),
                        _ => unreachable!(),
                    }
                    0
                }
            }
        }
        #[inline(always)]
        unsafe fn child(kind: u32, a: &[usize]) -> u32 {
            unsafe {
                match kind {
                    0 => {
                        __opensensor_init_callbacks();
                        0
                    }
                    1 => {
                        __opensensor_init_rf();
                        0
                    }
                    2 => {
                        __opensensor_init_init_param(a[0]);
                        0
                    }
                    3 => {
                        __opensensor_init_mac_data(a[0], a[1]);
                        0
                    }
                    4 => {
                        __opensensor_init_transfer(a[0], a[1]);
                        0
                    }
                    5 => {
                        __opensensor_init_recovery(a[0]);
                        0
                    }
                    6 => __opensensor_init_check_value(a[0], a[1], a[2]),
                    7 => {
                        __opensensor_init_backup(a[0]);
                        0
                    }
                    8 => __opensensor_init_check(a[0], a[1], a[2], a[3]),
                    #[cfg(esp32c3)]
                    9 => {
                        __opensensor_init_level();
                        0
                    }
                    10 => {
                        __opensensor_init_bb();
                        0
                    }
                    11 => __opensensor_init_register(a[0], a[1], a[2]),
                    #[cfg(esp32c3)]
                    12 => {
                        __opensensor_init_txcap();
                        0
                    }
                    #[cfg(esp32s3)]
                    13 => {
                        __opensensor_init_power_limits(a[0]);
                        0
                    }
                    #[cfg(esp32s3)]
                    14 => __opensensor_init_package(),
                    #[cfg(esp32s3)]
                    15 => {
                        __opensensor_init_chip_version();
                        0
                    }
                    16 => {
                        __opensensor_init_wakeup();
                        0
                    }
                    17 => {
                        __opensensor_init_close();
                        0
                    }
                    _ => unreachable!(),
                }
            }
        }
    }
    #[unsafe(no_mangle)]
    #[inline(never)]
    pub(crate) unsafe extern "C" fn __opensensor_init_callbacks() {
        unsafe {
            let value = super::dispatch::<Hardware>(0, &[]);
            let _ = value;
        }
    }
    #[unsafe(no_mangle)]
    #[inline(never)]
    pub(crate) unsafe extern "C" fn __opensensor_init_rf() {
        unsafe {
            let value = super::dispatch::<Hardware>(1, &[]);
            let _ = value;
        }
    }
    #[unsafe(no_mangle)]
    #[inline(never)]
    pub(crate) unsafe extern "C" fn __opensensor_init_init_param(a0: usize) {
        unsafe {
            let value = super::dispatch::<Hardware>(2, &[a0]);
            let _ = value;
        }
    }
    #[unsafe(no_mangle)]
    #[inline(never)]
    pub(crate) unsafe extern "C" fn __opensensor_init_mac_data(a0: usize, a1: usize) {
        unsafe {
            let value = super::dispatch::<Hardware>(3, &[a0, a1]);
            let _ = value;
        }
    }
    #[unsafe(no_mangle)]
    #[inline(never)]
    pub(crate) unsafe extern "C" fn __opensensor_init_transfer(a0: usize, a1: usize) {
        unsafe {
            let value = super::dispatch::<Hardware>(4, &[a0, a1]);
            let _ = value;
        }
    }
    #[unsafe(no_mangle)]
    #[inline(never)]
    pub(crate) unsafe extern "C" fn __opensensor_init_recovery(a0: usize) {
        unsafe {
            let value = super::dispatch::<Hardware>(5, &[a0]);
            let _ = value;
        }
    }
    #[unsafe(no_mangle)]
    #[inline(never)]
    pub(crate) unsafe extern "C" fn __opensensor_init_check_value(
        a0: usize,
        a1: usize,
        a2: usize,
    ) -> u32 {
        unsafe {
            let value = super::dispatch::<Hardware>(6, &[a0, a1, a2]);
            value
        }
    }
    #[unsafe(no_mangle)]
    #[inline(never)]
    pub(crate) unsafe extern "C" fn __opensensor_init_backup(a0: usize) {
        unsafe {
            let value = super::dispatch::<Hardware>(7, &[a0]);
            let _ = value;
        }
    }
    #[unsafe(no_mangle)]
    #[inline(never)]
    pub(crate) unsafe extern "C" fn __opensensor_init_check(
        a0: usize,
        a1: usize,
        a2: usize,
        a3: usize,
    ) -> u32 {
        unsafe {
            let value = super::dispatch::<Hardware>(8, &[a0, a1, a2, a3]);
            value
        }
    }
    #[cfg(esp32c3)]
    #[unsafe(no_mangle)]
    #[inline(never)]
    pub(crate) unsafe extern "C" fn __opensensor_init_level() {
        unsafe {
            let value = super::dispatch::<Hardware>(9, &[]);
            let _ = value;
        }
    }
    #[unsafe(no_mangle)]
    #[inline(never)]
    pub(crate) unsafe extern "C" fn __opensensor_init_bb() {
        unsafe {
            let value = super::dispatch::<Hardware>(10, &[]);
            let _ = value;
        }
    }
    #[unsafe(no_mangle)]
    #[inline(never)]
    pub(crate) unsafe extern "C" fn __opensensor_init_register(
        a0: usize,
        a1: usize,
        a2: usize,
    ) -> u32 {
        unsafe {
            let value = super::dispatch::<Hardware>(11, &[a0, a1, a2]);
            value
        }
    }
    #[cfg(esp32c3)]
    #[unsafe(no_mangle)]
    #[inline(never)]
    pub(crate) unsafe extern "C" fn __opensensor_init_txcap() {
        unsafe {
            let value = super::dispatch::<Hardware>(12, &[]);
            let _ = value;
        }
    }
    #[cfg(esp32s3)]
    #[unsafe(no_mangle)]
    #[inline(never)]
    pub(crate) unsafe extern "C" fn __opensensor_init_power_limits(a0: usize) {
        unsafe {
            let value = super::dispatch::<Hardware>(13, &[a0]);
            let _ = value;
        }
    }
    #[cfg(esp32s3)]
    #[unsafe(no_mangle)]
    #[inline(never)]
    pub(crate) unsafe extern "C" fn __opensensor_init_package() -> u32 {
        unsafe {
            let value = super::dispatch::<Hardware>(14, &[]);
            value
        }
    }
    #[cfg(esp32s3)]
    #[unsafe(no_mangle)]
    #[inline(never)]
    pub(crate) unsafe extern "C" fn __opensensor_init_chip_version() {
        unsafe {
            let value = super::dispatch::<Hardware>(15, &[]);
            let _ = value;
        }
    }
    #[unsafe(no_mangle)]
    #[esp_hal::ram]
    pub(crate) unsafe extern "C" fn __opensensor_init_wakeup() {
        unsafe {
            let value = super::dispatch::<Hardware>(16, &[]);
            let _ = value;
        }
    }
    #[unsafe(no_mangle)]
    #[esp_hal::ram]
    pub(crate) unsafe extern "C" fn __opensensor_init_close() {
        unsafe {
            let value = super::dispatch::<Hardware>(17, &[]);
            let _ = value;
        }
    }
}
