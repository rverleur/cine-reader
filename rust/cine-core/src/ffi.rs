//! Stable C ABI. All unsafe code is confined to this module: valid caller-owned
//! buffers and live handles are a requirement of the C contract. Rust errors and
//! panics become a thread-local diagnostic and never unwind across the ABI.
use crate::{
    processing::{self, Stats},
    reader::{decode, FrameInfo, Info, Reader},
    writer::{CineWriter, WriterOptions},
    Error, Result,
};
use std::cell::RefCell;
use std::ffi::{c_char, c_void, CStr, CString};
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::ptr;
use std::slice;

thread_local! {static LAST_ERROR: RefCell<CString> = RefCell::new(CString::new("").unwrap());}
fn error(e: impl std::fmt::Display) {
    LAST_ERROR.with(|v| *v.borrow_mut() = CString::new(e.to_string().replace('\0', " ")).unwrap());
}
fn run<T>(f: impl FnOnce() -> Result<T>) -> Option<T> {
    match catch_unwind(AssertUnwindSafe(f)) {
        Ok(Ok(v)) => Some(v),
        Ok(Err(e)) => {
            error(e);
            None
        }
        Err(_) => {
            error("Rust backend panic contained at ABI boundary");
            None
        }
    }
}
fn status(f: impl FnOnce() -> Result<()>) -> i32 {
    if run(f).is_some() {
        0
    } else {
        -1
    }
}
fn disjoint(
    src: *const c_void,
    source_bytes: usize,
    dst: *mut c_void,
    output_bytes: usize,
) -> Result<()> {
    if source_bytes == 0 || output_bytes == 0 {
        return Ok(());
    }
    let a = src as usize;
    let b = dst as usize;
    let ae = a
        .checked_add(source_bytes)
        .ok_or_else(|| Error::format("input address range overflow"))?;
    let be = b
        .checked_add(output_bytes)
        .ok_or_else(|| Error::format("output address range overflow"))?;
    if a < be && b < ae {
        return Err(Error::format("input and output buffers must not overlap"));
    }
    Ok(())
}
unsafe fn handle<'a, T>(p: *mut c_void) -> Result<&'a mut T> {
    p.cast::<T>()
        .as_mut()
        .ok_or_else(|| Error::format("null or closed handle"))
}
unsafe fn path<'a>(p: *const c_char) -> Result<&'a str> {
    if p.is_null() {
        return Err(Error::format("null path"));
    }
    CStr::from_ptr(p)
        .to_str()
        .map_err(|_| Error::format("path must be UTF-8"))
}
unsafe fn input<'a, T>(p: *const T, n: usize) -> Result<&'a [T]> {
    if n == 0 {
        return Ok(&[]);
    }
    if p.is_null()
        || n > isize::MAX as usize / std::mem::size_of::<T>()
        || (p as usize) % std::mem::align_of::<T>() != 0
    {
        return Err(Error::format("invalid input buffer"));
    }
    Ok(slice::from_raw_parts(p, n))
}
unsafe fn output<'a, T>(p: *mut T, n: usize) -> Result<&'a mut [T]> {
    if n == 0 {
        return Ok(&mut []);
    }
    if p.is_null()
        || n > isize::MAX as usize / std::mem::size_of::<T>()
        || (p as usize) % std::mem::align_of::<T>() != 0
    {
        return Err(Error::format("invalid output buffer"));
    }
    Ok(slice::from_raw_parts_mut(p, n))
}
#[no_mangle]
pub extern "C" fn cine_abi_version() -> u32 {
    1
}
#[no_mangle]
pub extern "C" fn cine_last_error() -> *const c_char {
    LAST_ERROR.with(|v| v.borrow().as_ptr())
}
#[no_mangle]
pub unsafe extern "C" fn cine_reader_open(p: *const c_char) -> *mut c_void {
    run(|| Ok(Box::into_raw(Box::new(Reader::open(path(p)?)?)).cast())).unwrap_or(ptr::null_mut())
}
#[no_mangle]
pub unsafe extern "C" fn cine_reader_close(p: *mut c_void) {
    if !p.is_null() {
        let _ = run(|| {
            drop(Box::from_raw(p.cast::<Reader>()));
            Ok(())
        });
    }
}
#[no_mangle]
pub unsafe extern "C" fn cine_reader_info(p: *mut c_void, out: *mut Info) -> i32 {
    status(|| {
        *out.as_mut()
            .ok_or_else(|| Error::format("null info output"))? = handle::<Reader>(p)?.info;
        Ok(())
    })
}
#[no_mangle]
pub unsafe extern "C" fn cine_reader_offset(p: *mut c_void, index: u32, out: *mut u64) -> i32 {
    status(|| {
        *out.as_mut()
            .ok_or_else(|| Error::format("null offset output"))? =
            handle::<Reader>(p)?.offset(index)?;
        Ok(())
    })
}
#[no_mangle]
pub unsafe extern "C" fn cine_reader_block(
    p: *mut c_void,
    kind: u32,
    out: *mut u8,
    capacity: usize,
    written: *mut usize,
) -> i32 {
    status(|| {
        let r = handle::<Reader>(p)?;
        let n = r.block_len(kind)?;
        *written
            .as_mut()
            .ok_or_else(|| Error::format("null block size output"))? = n;
        if out.is_null() && capacity == 0 {
            return Ok(());
        }
        r.block_into(kind, output(out, capacity)?)
    })
}
#[no_mangle]
pub unsafe extern "C" fn cine_reader_read_at(
    p: *mut c_void,
    offset: u64,
    out: *mut u8,
    len: usize,
) -> i32 {
    status(|| handle::<Reader>(p)?.read_at(offset, output(out, len)?))
}
#[no_mangle]
pub unsafe extern "C" fn cine_reader_read_frame(
    p: *mut c_void,
    index: u32,
    flags: u32,
    out: *mut u8,
    capacity: usize,
    info: *mut FrameInfo,
) -> i32 {
    status(|| {
        let fi = handle::<Reader>(p)?.read_frame_into(index, flags, output(out, capacity)?)?;
        if !info.is_null() {
            *info = fi;
        }
        Ok(())
    })
}
#[no_mangle]
pub unsafe extern "C" fn cine_reader_trim(
    p: *mut c_void,
    name: *const c_char,
    start: u32,
    count: u32,
) -> i32 {
    status(|| handle::<Reader>(p)?.trim(path(name)?, start, count))
}
#[no_mangle]
pub unsafe extern "C" fn cine_decode(
    data: *const u8,
    len: usize,
    width: u32,
    height: i32,
    bit_count: u32,
    compression: u32,
    flags: u32,
    out: *mut u8,
    capacity: usize,
) -> i32 {
    status(|| {
        disjoint(data.cast(), len, out.cast(), capacity)?;
        decode(
            input(data, len)?,
            width,
            height,
            bit_count,
            compression,
            flags,
            output(out, capacity)?,
        )
    })
}
#[no_mangle]
pub unsafe extern "C" fn cine_unpack10(
    data: *const u8,
    len: usize,
    out: *mut u16,
    samples: usize,
) -> i32 {
    status(|| {
        let n = len / 5 * 4;
        if samples < n {
            return Err(Error::format("output buffer too small"));
        }
        disjoint(
            data.cast(),
            len,
            out.cast(),
            n.checked_mul(2)
                .ok_or_else(|| Error::format("output length overflow"))?,
        )?;
        let data = input(data, len / 5 * 5)?;
        let out = output(out, n)?;
        for (g, d) in data.chunks_exact(5).zip(out.chunks_exact_mut(4)) {
            d[0] = crate::lookup::LOOKUP[((g[0] as usize) << 2) | (g[1] as usize >> 6)];
            d[1] = crate::lookup::LOOKUP[((g[1] as usize & 63) << 4) | (g[2] as usize >> 4)];
            d[2] = crate::lookup::LOOKUP[((g[2] as usize & 15) << 6) | (g[3] as usize >> 2)];
            d[3] = crate::lookup::LOOKUP[((g[3] as usize & 3) << 8) | g[4] as usize];
        }
        Ok(())
    })
}
#[repr(C)]
pub struct CWriterOptions {
    width: u32,
    height: u32,
    channels: u32,
    bit_depth: u32,
    packed10: u32,
    frame_count: u32,
    first_frame: i32,
    cfa: u32,
    frame_rate: f64,
}
#[no_mangle]
pub unsafe extern "C" fn cine_writer_create(
    name: *const c_char,
    opts: *const CWriterOptions,
) -> *mut c_void {
    run(|| {
        let o = opts
            .as_ref()
            .ok_or_else(|| Error::format("null writer options"))?;
        let options = WriterOptions {
            width: o.width,
            height: o.height,
            channels: o.channels,
            bit_depth: o.bit_depth,
            packed10: o.packed10 != 0,
            frame_count: o.frame_count,
            first_frame: o.first_frame,
            cfa: o.cfa,
            frame_rate: o.frame_rate,
        };
        Ok(Box::into_raw(Box::new(CineWriter::create(path(name)?, options)?)).cast())
    })
    .unwrap_or(ptr::null_mut())
}
#[no_mangle]
pub unsafe extern "C" fn cine_writer_write(p: *mut c_void, data: *const u8, len: usize) -> i32 {
    status(|| handle::<CineWriter>(p)?.write_frame(input(data, len)?))
}
#[no_mangle]
pub unsafe extern "C" fn cine_writer_finish(p: *mut c_void) -> i32 {
    status(|| handle::<CineWriter>(p)?.finish())
}
#[no_mangle]
pub unsafe extern "C" fn cine_writer_write_image(
    p: *mut c_void,
    data: *const u8,
    len: usize,
    sample_bytes: u32,
    channels: u32,
) -> i32 {
    status(|| handle::<CineWriter>(p)?.write_image(input(data, len)?, sample_bytes, channels))
}
#[no_mangle]
pub unsafe extern "C" fn cine_writer_close(p: *mut c_void) {
    if !p.is_null() {
        let _ = run(|| {
            drop(Box::from_raw(p.cast::<CineWriter>()));
            Ok(())
        });
    }
}

#[no_mangle]
pub unsafe extern "C" fn cine_process(
    src: *const c_void,
    dst: *mut c_void,
    width: u32,
    height: u32,
    channels: u32,
    sample_type: u32,
    op: u32,
    param: u32,
    value: f64,
) -> i32 {
    status(|| {
        if op == 3 && channels != 1 {
            return Err(Error::format("demosaic requires one channel"));
        }
        let n = (width as usize)
            .checked_mul(height as usize)
            .and_then(|v| v.checked_mul(channels as usize))
            .ok_or_else(|| Error::format("image size overflow"))?;
        let m = if op == 3 {
            n.checked_mul(3)
                .ok_or_else(|| Error::format("image size overflow"))?
        } else {
            n
        };
        let bytes = sample_type as usize;
        if !matches!(bytes, 1 | 2 | 4 | 8) {
            return Err(Error::format("unsupported sample type"));
        }
        disjoint(
            src,
            n.checked_mul(bytes)
                .ok_or_else(|| Error::format("input length overflow"))?,
            dst,
            m.checked_mul(bytes)
                .ok_or_else(|| Error::format("output length overflow"))?,
        )?;
        macro_rules! go {
            ($t:ty) => {
                processing::process(
                    input(src.cast::<$t>(), n)?,
                    output(dst.cast::<$t>(), m)?,
                    width as usize,
                    height as usize,
                    channels as usize,
                    op,
                    param,
                    value,
                )
            };
        }
        match sample_type {
            1 => go!(u8),
            2 => go!(u16),
            4 => go!(f32),
            8 => go!(f64),
            _ => Err(Error::format("unsupported sample type")),
        }
    })
}
#[no_mangle]
pub extern "C" fn cine_stats_create(
    samples: usize,
    mode: u32,
    k: u32,
    q: f64,
    sigma: f64,
    min_keep: u32,
) -> *mut c_void {
    run(|| Ok(Box::into_raw(Box::new(Stats::new(samples, mode, k, q, sigma, min_keep)?)).cast()))
        .unwrap_or(ptr::null_mut())
}
#[no_mangle]
pub unsafe extern "C" fn cine_stats_push(
    p: *mut c_void,
    values: *const f64,
    samples: usize,
) -> i32 {
    status(|| handle::<Stats>(p)?.push(input(values, samples)?))
}
#[no_mangle]
pub unsafe extern "C" fn cine_stats_finish(
    p: *mut c_void,
    out: *mut f64,
    samples: usize,
    count: *mut u64,
) -> i32 {
    status(|| {
        let n = handle::<Stats>(p)?.finish(output(out, samples)?)?;
        if !count.is_null() {
            *count = n;
        }
        Ok(())
    })
}
#[no_mangle]
pub unsafe extern "C" fn cine_stats_close(p: *mut c_void) {
    if !p.is_null() {
        let _ = run(|| {
            drop(Box::from_raw(p.cast::<Stats>()));
            Ok(())
        });
    }
}
