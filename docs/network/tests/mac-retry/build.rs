use std::{env, fs, path::Path};

use quote::{ToTokens, quote};
use syn::{Item, TraitItem};

// Compile the production retry method without pulling in a chip-specific PAC.
// This is AST extraction, not a second implementation of the retry loop.
fn collect<'a>(items: &'a [Item], all: &mut Vec<&'a Item>) {
    for item in items {
        all.push(item);
        if let Item::Mod(module) = item {
            if let Some((_, nested)) = &module.content {
                collect(nested, all);
            }
        }
    }
}

fn main() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../..");
    let driver_path = root.join("esp-wifi-hal/src/async_driver.rs");
    let ll_path = root.join("esp-wifi-hal/src/ll.rs");
    for path in [&driver_path, &ll_path] {
        println!("cargo:rerun-if-changed={}", path.display());
    }
    let driver = syn::parse_file(&fs::read_to_string(driver_path).unwrap()).unwrap();
    let ll = syn::parse_file(&fs::read_to_string(ll_path).unwrap()).unwrap();
    let mut all = Vec::new();
    collect(&driver.items, &mut all);
    collect(&ll.items, &mut all);
    let mut output = quote! {};
    for name in [
        "TxError",
        "TxErrorBehaviour",
        "TxMacParameters",
        "TxPlcpParameters",
        "RtsStrategy",
        "EdcaParameters",
        "EdcaTxParameters",
        "ExtractedParameters",
        "NonExhaustive",
        "ChannelAccessError",
        "MacProtocolError",
        "HardwareTxQueue",
        "EdcaAccessCategory",
    ] {
        let matches: Vec<_> = all
            .iter()
            .filter(|item| match item {
                Item::Enum(item) => item.ident == name,
                Item::Struct(item) => item.ident == name,
                _ => false,
            })
            .collect();
        assert_eq!(
            matches.len(),
            1,
            "expected one production definition of {name}"
        );
        matches[0].to_tokens(&mut output);
    }
    for name in ["TxErrorBehaviour", "HardwareTxQueue", "EdcaAccessCategory"] {
        let matches: Vec<_> = all
            .iter()
            .filter(|item| {
                let Item::Impl(item) = item else {
                    return false;
                };
                item.trait_.is_none()
                    && matches!(&*item.self_ty, syn::Type::Path(path)
                if path.qself.is_none() && path.path.segments.len() == 1
                    && path.path.segments[0].ident == name)
            })
            .collect();
        assert_eq!(
            matches.len(),
            1,
            "expected one production implementation of {name}"
        );
        matches[0].to_tokens(&mut output);
    }
    let methods: Vec<_> = all
        .iter()
        .filter_map(|item| {
            let Item::Trait(item) = item else {
                return None;
            };
            (item.ident == "AsyncTransmitExt").then_some(item)
        })
        .flat_map(|item| &item.items)
        .filter_map(|item| {
            let TraitItem::Fn(method) = item else {
                return None;
            };
            (method.sig.ident == "transmit_with_retry").then_some(method)
        })
        .collect();
    assert_eq!(
        methods.len(),
        1,
        "production retry method missing or ambiguous"
    );
    let method = methods[0];
    assert!(
        method.default.is_some(),
        "retry method must have its production body"
    );
    output.extend(quote! { impl TestDriver { #method } });
    fs::write(
        Path::new(&env::var("OUT_DIR").unwrap()).join("production.rs"),
        output.to_string(),
    )
    .unwrap();
}
