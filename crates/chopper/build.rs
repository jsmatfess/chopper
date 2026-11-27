fn main() {
    println!("cargo::rerun-if-changed=build.rs");
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("windows")
        && std::env::var("CARGO_CFG_TARGET_ENV").as_deref() == Ok("msvc")
    {
        // Allow the CLI's nested parser and publication frames to fit on Windows.
        // Reserve address space and let Windows commit pages as needed.
        println!("cargo::rustc-link-arg-bin=chopper=/STACK:4194304");
    }
}
