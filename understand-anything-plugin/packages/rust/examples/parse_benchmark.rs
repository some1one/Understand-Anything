//! Low-level parse timing probe; no extraction or import-resolution claims.
use std::{env, fs, path::Path, time::Instant};
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = env::args().skip(1).collect();
    if args.len() != 4 {
        return Err("usage: parse_benchmark CACHE LANGUAGE SOURCE ITERATIONS".into());
    }
    let count = args[3].parse::<usize>()?;
    understand_anything::parsers::configure(Some(Path::new(&args[0])))?;
    let source = fs::read_to_string(&args[2])?;
    let start = Instant::now();
    let first = understand_anything::parsers::parse(&args[1], &source)?;
    std::hint::black_box(first.root_node().kind());
    let first_seconds = start.elapsed().as_secs_f64();
    let start = Instant::now();
    for _ in 0..count {
        let tree = understand_anything::parsers::parse(&args[1], &source)?;
        std::hint::black_box(tree.root_node().kind());
    }
    println!(
        "{}",
        serde_json::json!({"firstParseSeconds":first_seconds,"warmParseSeconds":start.elapsed().as_secs_f64(),"iterations":count})
    );
    Ok(())
}
