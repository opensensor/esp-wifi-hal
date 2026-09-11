/* SPDX-FileCopyrightText: 2015-2024 Espressif Systems (Shanghai) CO LTD
 * SPDX-License-Identifier: Apache-2.0
 *
 * Original esp_coex_common_clk_slowclk_cal_get_wrapper body from ESP-IDF
 * 67c1de1eebe095d554d281952fde63c16ee2dca0, components/esp_coex/esp32s3/
 * esp_coex_adapter.c. Only its name and peripheral reads are adapted for host
 * tests; constants come from that revision's S3 headers. The getter below
 * models esp_hw_support/esp_clk.c -> clk_ll_rtc_slow_load_cal(), whose body
 * in hal/esp32s3/include/hal/clk_tree_ll.h reads RTC_SLOW_CLK_CAL_REG.
 * Source and original compiled instruction evidence: ../SLOW-CLOCK.md.
 */
#include <stdint.h>

extern uint32_t s3_idf_test_read(uintptr_t address);
#define SYSTEM_BT_LPCK_DIV_FRAC_REG 0x600c002cu
#define SYSTEM_LPCLK_SEL_XTAL (1u << 26)
#define RTC_CLK_CAL_FRACT 19
#define SOC_WIFI_LIGHT_SLEEP_CLK_WIDTH 12
#define MHZ 1000000
#define GET_PERI_REG_MASK(reg, mask) (s3_idf_test_read(reg) & (mask))

static uint32_t esp_clk_slowclk_cal_get(void)
{
    return s3_idf_test_read(0x60008054u);
}

uint32_t s3_idf_slowclk_cal_get_reference(void)
{
    /* The bit width of WiFi light sleep clock calibration is 12 while the one of
     * system is 19. It should shift 19 - 12 = 7.
    */
    if (GET_PERI_REG_MASK(SYSTEM_BT_LPCK_DIV_FRAC_REG, SYSTEM_LPCLK_SEL_XTAL)) {
        uint64_t time_per_us = 1000000ULL;
        return (((time_per_us << RTC_CLK_CAL_FRACT) / (MHZ)) >> (RTC_CLK_CAL_FRACT - SOC_WIFI_LIGHT_SLEEP_CLK_WIDTH));
    } else {
        return (esp_clk_slowclk_cal_get() >> (RTC_CLK_CAL_FRACT - SOC_WIFI_LIGHT_SLEEP_CLK_WIDTH));
    }
}
