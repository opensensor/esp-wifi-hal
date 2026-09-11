fn main() {
    #[cfg(feature = "printf-smoke")]
    build_printf_test();
}

#[cfg(feature = "printf-smoke")]
fn build_printf_test() {
    let target = std::env::var("TARGET").unwrap();
    let (compiler, flags): (&str, &[&str]) = match target.as_str() {
        "riscv32imc-unknown-none-elf" => {
            ("riscv32-esp-elf-gcc", &["-march=rv32imc", "-mabi=ilp32"])
        }
        "xtensa-esp32s3-none-elf" => (
            "xtensa-esp32s3-elf-gcc",
            &["-mlongcalls", "-mtext-section-literals"],
        ),
        _ => panic!("printf-smoke supports C3 and S3 only"),
    };
    let mut build = cc::Build::new();
    for (kind, fallback) in [
        ("CC", compiler.to_owned()),
        ("AR", compiler.replace("gcc", "ar")),
    ] {
        let vars = [
            format!("{kind}_{target}"),
            format!("{kind}_{}", target.replace('-', "_")),
            format!("TARGET_{kind}"),
            kind.to_owned(),
        ];
        for var in &vars {
            println!("cargo:rerun-if-env-changed={var}");
        }
        if !vars.iter().any(|var| std::env::var_os(var).is_some()) {
            if kind == "CC" {
                build.compiler(fallback);
            } else {
                build.archiver(fallback);
            }
        }
    }
    build
        .no_default_flags(true)
        .file("tests/printf-abi.c")
        .flags([
            "-std=c99",
            "-Os",
            "-ffreestanding",
            "-fno-builtin",
            "-fno-stack-protector",
            "-ffunction-sections",
            "-fdata-sections",
        ])
        .flags(flags)
        .compile("printf-abi-test");
    println!("cargo:rerun-if-changed=tests/printf-abi.c");
}
