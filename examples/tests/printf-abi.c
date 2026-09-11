/* MIT. Target-callable formatter tests. No allocator, I/O or test-only library
 * symbols are needed: compile this file in a consumer's test image only. */
#include <limits.h>
#include <stdint.h>
/* Same cases as opensensor/esp-wifi-sys ffcc1a2 tests/printf-abi.c.
 * Declare the real C ABI directly; no libc inline/builtin substitution. */
#include <stdarg.h>
#include <stddef.h>
extern int snprintf(char *, size_t, const char *, ...);
extern int vsnprintf(char *, size_t, const char *, va_list);

static int equal(const char *a, const char *b) {
  while (*a && *a == *b) { ++a; ++b; }
  return *a == *b;
}

static int format_va(char *buffer, size_t count, const char *format, ...) {
  va_list args;
  va_start(args, format);
  int result = vsnprintf(buffer, count, format, args);
  va_end(args);
  return result;
}

/* Returns zero on success; otherwise the failing case number. */
unsigned opensensor_printf_abi_selftest(void) {
  char buffer[160];
#define CHECK(id, test) do { if (!(test)) return (id); } while (0)
  CHECK(1, snprintf(buffer, sizeof(buffer), "%d %u %08x %04X", -123, 4294967295U, 0x1234abcdU, 0xbeefU) == 29);
  CHECK(2, equal(buffer, "-123 4294967295 1234abcd BEEF"));
  snprintf(buffer, sizeof(buffer), "%lld %llu", -123456789012345LL, 18446744073709551615ULL);
  CHECK(3, equal(buffer, "-123456789012345 18446744073709551615"));
  format_va(buffer, sizeof(buffer), "%*.*f %e %g %zu %td", 7, 2, 12.5, 1000.0, 1.25, (size_t)17, (ptrdiff_t)-9);
  CHECK(4, equal(buffer, "  12.50 10.000000e+02 1.25000 17 -9"));
  snprintf(buffer, sizeof(buffer), "%+06d|%-5.3s|%#x|%b|%%", 42, "abcdef", 42U, 5U);
  CHECK(5, equal(buffer, "+00042|abc  |0x2a|101|%"));
  char guard[9] = "ABCDEFGH";
  CHECK(6, snprintf(guard + 2, 4, "%s", "123456") == 6);
  CHECK(7, guard[0] == 'A' && guard[1] == 'B' && guard[2] == '1' && guard[3] == '2' && guard[4] == '3' && guard[5] == 0 && guard[6] == 'G' && guard[7] == 'H');
  CHECK(8, snprintf(guard + 2, 0, "%d", 123) == 3 && guard[2] == '1');
  CHECK(9, snprintf(guard + 2, 1, "abc") == 3 && guard[2] == 0 && guard[3] == '2');
  CHECK(10, snprintf(0, 0, "%llu", 18446744073709551615ULL) == 20);
  snprintf(buffer, sizeof(buffer), "%lld", LLONG_MIN);
  CHECK(11, equal(buffer, "-9223372036854775808"));
  snprintf(buffer, sizeof(buffer), "%d", INT_MIN);
  CHECK(12, equal(buffer, "-2147483648"));
  snprintf(buffer, sizeof(buffer), "%p", (void *)(uintptr_t)0x1234);
  CHECK(13, equal(buffer, sizeof(void *) == 4 ? "00001234" : "0000000000001234"));
  snprintf(buffer, sizeof(buffer), "%ld", LONG_MIN);
  CHECK(14, equal(buffer, sizeof(long) == 4 ? "-2147483648" : "-9223372036854775808"));
  return 0;
#undef CHECK
}
