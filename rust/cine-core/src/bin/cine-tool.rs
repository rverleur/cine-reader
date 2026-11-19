//! Minimal standalone executable; no Python, MATLAB, codec library or GPU needed.
use cine_core::{
    writer::{CineWriter, WriterOptions},
    Reader,
};
use std::{env, fs, time::Instant};
fn main() {
    if let Err(e) = run() {
        eprintln!("{e}");
        std::process::exit(1);
    }
}
fn run() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = env::args().collect();
    if args.len() < 3 {
        return Err("usage: cine-tool info FILE | extract FILE INDEX OUTPUT.raw | verify FILE | transcode INPUT OUTPUT normal|packed10".into());
    }
    let mut r = Reader::open(&args[2])?;
    match args[1].as_str() {
        "info" => println!("{:#?}\n{:#?}", r.info, r.metadata()),
        "extract" if args.len() == 5 => {
            let index = args[3].parse()?;
            let bytes = r.read_frame(index)?;
            fs::write(&args[4], bytes)?;
        }
        "verify" => {
            let now = Instant::now();
            let mut frame = vec![0; r.info.decoded_bytes as usize];
            for i in 0..r.info.frame_count {
                r.read_frame_into(i, 0, &mut frame)?;
            }
            println!(
                "Verified {} frames in {:.3}s",
                r.info.frame_count,
                now.elapsed().as_secs_f64()
            );
        }
        "transcode" if args.len() == 5 => {
            let packed10 = match args[4].as_str() {
                "normal" => false,
                "packed10" => true,
                _ => return Err("encoding must be normal or packed10".into()),
            };
            let info = r.info;
            if packed10 && info.sample_bytes != 2 {
                return Err("packed10 requires 12-bit linear u16 input; use the image/video frontend to rescale 8-bit media".into());
            }
            let rate = r.metadata().frame_rate;
            let bit_depth = if packed10 || info.compression == 256 || info.compression == 1024 {
                12
            } else if info.sample_bytes == 1 {
                8
            } else {
                info.real_bpp.clamp(9, 16)
            };
            let options = WriterOptions {
                width: info.width,
                height: info.height.unsigned_abs(),
                channels: info.channels,
                bit_depth,
                packed10,
                frame_count: info.frame_count,
                first_frame: info.first_frame,
                frame_rate: if rate > 0.0 { rate } else { 30.0 },
                cfa: if info.channels == 1 { info.cfa } else { 0 },
            };
            let mut writer = CineWriter::create(&args[3], options)?;
            let mut frame = vec![0; info.decoded_bytes as usize];
            for i in 0..info.frame_count {
                r.read_frame_into(i, 3, &mut frame)?;
                writer.write_frame(&frame)?;
            }
            writer.finish()?;
        }
        _ => return Err("unknown command or wrong argument count".into()),
    }
    Ok(())
}
