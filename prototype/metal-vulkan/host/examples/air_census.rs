//! air_census <file.bc>...: decodes each AIR bitcode module as metal2vulkan's translator does and
//! prints one line per distinct failure with its count.
use std::collections::BTreeMap;

fn main() {
    let budget = metal2vulkan_air::budget::Budget::standard();
    let mut failures: BTreeMap<String, Vec<String>> = BTreeMap::new();
    let mut good = 0;
    for path in std::env::args().skip(1) {
        let bytes = std::fs::read(&path).expect("read");
        let mut meter = metal2vulkan_air::budget::Meter::new(&budget);
        match metal2vulkan_air::decode(&bytes, &mut meter) {
            Ok(_) => good += 1,
            Err(error) => failures.entry(format!("{error:?}").chars().take(300).collect()).or_default().push(path),
        }
    }
    for (failure, paths) in &failures {
        println!("{:5} x {failure}  e.g. {}", paths.len(), paths[0]);
    }
    println!("decoded {good}, failed {}", failures.values().map(Vec::len).sum::<usize>());
}
