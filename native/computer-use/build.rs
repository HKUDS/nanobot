fn main() {
    // Swift runtime is supplied by macOS. Dependency build scripts' rpaths do
    // not propagate to the final host executable or its test harness.
    println!("cargo:rustc-link-arg=-Wl,-rpath,/usr/lib/swift");
}
