//! Product business-code helper. This is separate from the trusted Agent CLI.
use std::io::{self, BufRead, Read};
use std::time::Duration;
use serde::Deserialize;
use serde_json::json;
use wasmtime::*;
use base64::Engine as _;
use wasmtime_wasi::{WasiCtxBuilder, p1::{self, WasiP1Ctx}, p2::pipe::MemoryOutputPipe};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request { abi: String, id: String, module: String }
struct Context { limits: StoreLimits, wasi: WasiP1Ctx }

fn evaluate(request: &Request) -> wasmtime::Result<()> {
    let bytes = base64::engine::general_purpose::STANDARD.decode(&request.module)?;
    if bytes.len() > 2 * 1024 * 1024 || !bytes.starts_with(b"\0asm") { bail!("invalid_module"); }
    let mut config = Config::new();
    config.consume_fuel(true).epoch_interruption(true);
    let engine = Engine::new(&config)?;
    let module = Module::new(&engine, bytes)?;
    let mut linker = Linker::new(&engine);
    p1::add_to_linker_sync(&mut linker, |context: &mut Context| &mut context.wasi)?;
    let mut builder = WasiCtxBuilder::new();
    builder.inherit_stdin().inherit_stdout().stderr(MemoryOutputPipe::new(16384))
        .allow_tcp(false).allow_udp(false).allow_ip_name_lookup(false);
    // No inherited environment, preopened directories, sockets or fixture imports.
    let context = Context {
        limits: StoreLimitsBuilder::new().memory_size(64 * 1024 * 1024)
            .instances(1).memories(1).tables(1).build(),
        wasi: builder.build_p1(),
    };
    let mut store = Store::new(&engine, context);
    store.limiter(|context| &mut context.limits);
    store.set_fuel(100_000_000)?;
    store.set_epoch_deadline(1);
    let clock = engine.clone();
    std::thread::spawn(move || { std::thread::sleep(Duration::from_secs(20)); clock.increment_epoch(); });
    let instance = linker.instantiate(&mut store, &module)?;
    instance.get_typed_func::<(), ()>(&mut store, "_start")?.call(&mut store, ())?;
    Ok(())
}

fn main() {
    let mut line = String::new();
    let read = io::stdin().lock().take(3 * 1024 * 1024 + 1).read_line(&mut line);
    let request = match read.and_then(|_| Ok(serde_json::from_str::<Request>(&line))) {
        Ok(Ok(value)) if line.ends_with('\n') && line.len() <= 3 * 1024 * 1024
            && value.abi == "runteams.wasi-jsonl/1" && !value.id.is_empty() && value.id.len() <= 128 => value,
        _ => { eprintln!("{}", json!({"outcome":"rejected","code":"invalid_request"})); return; }
    };
    let state = match evaluate(&request) { Ok(()) => "completed", Err(_) => "failed" };
    // Only this private stderr control frame can report the helper outcome.
    eprintln!("{}", json!({"abi":"runteams.wasi-jsonl/1","id":request.id,"outcome":state}));
}
