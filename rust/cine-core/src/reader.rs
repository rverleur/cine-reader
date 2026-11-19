use crate::{lookup::LOOKUP, Error, Result};
use std::fs::{File, OpenOptions};
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::Path;

pub(crate) fn u16_at(b: &[u8], p: usize) -> u16 {
    u16::from_le_bytes(b[p..p + 2].try_into().unwrap())
}
pub(crate) fn u32_at(b: &[u8], p: usize) -> u32 {
    u32::from_le_bytes(b[p..p + 4].try_into().unwrap())
}
fn i32_at(b: &[u8], p: usize) -> i32 {
    u32_at(b, p) as i32
}
fn get32(b: &[u8], p: usize) -> u32 {
    if b.len() >= p + 4 {
        u32_at(b, p)
    } else {
        0
    }
}
fn read(file: &mut File, offset: u64, out: &mut [u8]) -> Result<()> {
    file.seek(SeekFrom::Start(offset))?;
    file.read_exact(out)?;
    Ok(())
}
fn checked_size(n: u64) -> Result<usize> {
    let n = usize::try_from(n).map_err(|_| Error::format("buffer exceeds address space"))?;
    if n > isize::MAX as usize {
        return Err(Error::format("buffer exceeds address space"));
    }
    Ok(n)
}

#[derive(Debug, Clone, Copy, Default)]
#[repr(C)]
pub struct Info {
    pub width: u32,
    pub height: i32,
    pub bit_count: u32,
    pub compression: u32,
    pub real_bpp: u32,
    pub cfa: u32,
    pub frame_count: u32,
    pub first_frame: i32,
    pub channels: u32,
    pub sample_bytes: u32,
    pub decoded_bytes: u64,
    pub file_size: u64,
}
#[derive(Debug, Clone, Copy, Default)]
#[repr(C)]
pub struct FrameInfo {
    pub annotation_size: u32,
    pub image_size: u32,
}

/// Common capture metadata, parsed without requiring a language binding.
#[derive(Debug, Clone)]
pub struct Metadata {
    pub version: u16,
    pub first_movie_image: i32,
    pub total_image_count: u32,
    /// TIME64: seconds since Unix epoch in the high word, fraction in the low.
    pub trigger_time: u64,
    pub frame_rate: f64,
    pub exposure_ns: u64,
    pub recording_timezone_minutes: i32,
    pub color_enabled: bool,
    pub black_level: i32,
    pub white_level: i32,
    pub setup_length: usize,
}

/// An open file with bounded metadata and one reusable packed-frame scratch buffer.
/// Opening does not read image data or scan the offset table. One reader may be
/// moved between threads, but accesses to the same reader must be serialized.
pub struct Reader {
    file: File,
    pub info: Info,
    header: Vec<u8>,
    bitmap: Vec<u8>,
    setup: Vec<u8>,
    table: u64,
    table_end: u64,
    offset_bytes: usize,
    last: Option<(u64, FrameInfo)>,
    scratch: Vec<u8>,
}
impl Reader {
    pub fn metadata(&self) -> Metadata {
        let floating_rate = if self.setup.len() >= 10408 {
            f64::from_le_bytes(self.setup[10400..10408].try_into().unwrap())
        } else {
            0.0
        };
        let rate = if floating_rate.is_finite() && floating_rate > 0.0 {
            floating_rate
        } else {
            let rate = get32(&self.setup, 768);
            if rate > 0 {
                rate as f64
            } else {
                u16_at(&self.setup, 0) as f64
            }
        };
        let exposure = get32(&self.setup, 1568) as u64;
        let exposure_ns = if exposure > 0 {
            exposure
        } else {
            let us = get32(&self.setup, 772);
            if us > 0 {
                us as u64 * 1000
            } else {
                u16_at(&self.setup, 2) as u64 * 1000
            }
        };
        Metadata {
            version: u16_at(&self.header, 6),
            first_movie_image: i32_at(&self.header, 8),
            total_image_count: u32_at(&self.header, 12),
            trigger_time: u64::from_le_bytes(self.header[36..44].try_into().unwrap()),
            frame_rate: rate,
            exposure_ns,
            recording_timezone_minutes: get32(&self.setup, 804) as i32,
            color_enabled: get32(&self.setup, 788) != 0,
            black_level: get32(&self.setup, 5732) as i32,
            white_level: get32(&self.setup, 5736) as i32,
            setup_length: self.setup.len(),
        }
    }
    pub fn open(path: impl AsRef<Path>) -> Result<Self> {
        let mut file = File::open(path)?;
        let file_size = file.metadata()?.len();
        let mut header = vec![0; 44];
        read(&mut file, 0, &mut header)?;
        if &header[..2] != b"CI" || u16_at(&header, 2) < 44 {
            return Err(Error::format("invalid CINE signature/header"));
        }
        if !matches!(u16_at(&header, 4), 0 | 2) {
            return Err(Error::format("compressed CCI requires the Phantom SDK"));
        }
        let offset_bytes = match u16_at(&header, 6) {
            0 => 4,
            1 => 8,
            _ => return Err(Error::format("unsupported CINE version")),
        };
        let bpos = u32_at(&header, 24) as u64;
        let spos = u32_at(&header, 28) as u64;
        let table = u32_at(&header, 32) as u64;
        let frame_count = u32_at(&header, 20);
        let table_end = table + u64::from(frame_count) * offset_bytes as u64;
        if bpos < u16_at(&header, 2) as u64
            || spos < bpos + 40
            || table < spos + 144
            || table_end > file_size
            || frame_count == 0
        {
            return Err(Error::format("invalid CINE metadata/offset bounds"));
        }
        let mut bitmap = vec![0; 40];
        read(&mut file, bpos, &mut bitmap)?;
        if u32_at(&bitmap, 0) < 40
            || bpos + u32_at(&bitmap, 0) as u64 > spos
            || u16_at(&bitmap, 12) != 1
        {
            return Err(Error::format("invalid bitmap header"));
        }
        let width = i32_at(&bitmap, 4);
        let height = i32_at(&bitmap, 8);
        if width <= 0 || height == 0 || height == i32::MIN {
            return Err(Error::format("invalid image dimensions"));
        }
        let bit_count = u16_at(&bitmap, 14) as u32;
        let (channels, sample_bytes) = match bit_count {
            8 => (1, 1),
            16 => (1, 2),
            24 => (3, 1),
            48 => (3, 2),
            _ => return Err(Error::format("unsupported image bit depth")),
        };
        let compression = u32_at(&bitmap, 16);
        if !matches!(compression, 0 | 256 | 1024)
            || (compression != 0 && (channels != 1 || sample_bytes != 2))
        {
            return Err(Error::format("unsupported bitmap compression"));
        }
        let mut setup = vec![0; 144];
        read(&mut file, spos, &mut setup)?;
        let declared = u16_at(&setup, 142) as u64;
        let setup_len = if declared == 0 {
            (table - spos).min(10684)
        } else {
            declared
        };
        if setup_len < 144 || spos + setup_len > table {
            return Err(Error::format("invalid SETUP length"));
        }
        setup.resize(setup_len as usize, 0);
        read(&mut file, spos, &mut setup)?;
        let pixels = (width as u64)
            .checked_mul(height.unsigned_abs() as u64)
            .and_then(|v| v.checked_mul(channels as u64))
            .ok_or_else(|| Error::format("image dimensions overflow"))?;
        let decoded_bytes = pixels
            .checked_mul(sample_bytes as u64)
            .ok_or_else(|| Error::format("image dimensions overflow"))?;
        checked_size(decoded_bytes)?;
        // ImageSize is a u32 in the file; larger decoded frames cannot be represented.
        if decoded_bytes > u32::MAX as u64 * 2 {
            return Err(Error::format("frame size exceeds CINE limits"));
        }
        let minimum_payload = match compression {
            256 => pixels.div_ceil(4) * 5,
            1024 => pixels.div_ceil(2) * 3,
            _ => decoded_bytes,
        };
        if minimum_payload > file_size.saturating_sub(table_end + 8) {
            return Err(Error::format(
                "file cannot contain a frame of the declared dimensions",
            ));
        }
        let info = Info {
            width: width as u32,
            height,
            bit_count,
            compression,
            real_bpp: get32(&setup, 896),
            cfa: get32(&setup, 808),
            frame_count,
            first_frame: i32_at(&header, 16),
            channels,
            sample_bytes,
            decoded_bytes,
            file_size,
        };
        Ok(Self {
            file,
            info,
            header,
            bitmap,
            setup,
            table,
            table_end,
            offset_bytes,
            last: None,
            scratch: Vec::new(),
        })
    }
    pub fn offset(&mut self, index: u32) -> Result<u64> {
        if index == self.info.frame_count {
            return Ok(self.info.file_size);
        }
        if index > self.info.frame_count {
            return Err(Error::format("frame index out of bounds"));
        }
        let mut b = [0; 8];
        read(
            &mut self.file,
            self.table + u64::from(index) * self.offset_bytes as u64,
            &mut b[..self.offset_bytes],
        )?;
        let off = u64::from_le_bytes(b);
        if off < self.table_end || off > self.info.file_size.saturating_sub(8) {
            return Err(Error::format("invalid image offset"));
        }
        Ok(off)
    }
    fn location(&mut self, index: u32) -> Result<(u64, FrameInfo)> {
        if index >= self.info.frame_count {
            return Err(Error::format("frame index out of bounds"));
        }
        let off = self.offset(index)?;
        let next = self.offset(index + 1)?;
        let mut b = [0; 4];
        read(&mut self.file, off, &mut b)?;
        let annotation_size = u32::from_le_bytes(b);
        if annotation_size < 8 || off + annotation_size as u64 > next {
            return Err(Error::format("invalid annotation size"));
        }
        read(&mut self.file, off + annotation_size as u64 - 4, &mut b)?;
        let image_size = u32::from_le_bytes(b);
        if image_size == 0 || off + annotation_size as u64 + image_size as u64 > next {
            return Err(Error::format("invalid image payload size"));
        }
        Ok((
            off,
            FrameInfo {
                annotation_size,
                image_size,
            },
        ))
    }
    /// Read into an existing allocation. flags=0 is storage order; bit 0 gives
    /// top-down rows, bit 1 gives RGB channels. Native Rust callers usually use 3.
    pub fn read_frame_into(&mut self, index: u32, flags: u32, out: &mut [u8]) -> Result<FrameInfo> {
        if out.len() < self.info.decoded_bytes as usize {
            return Err(Error::format("output buffer too small"));
        }
        let (off, frame) = self.location(index)?;
        let pos = off + frame.annotation_size as u64;
        if self.info.compression == 0
            && flags == 0
            && u64::from(frame.image_size) == self.info.decoded_bytes
        {
            read(&mut self.file, pos, &mut out[..frame.image_size as usize])?;
        } else {
            // Check payload length before allocating, so corrupt annotation sizes cannot
            // force an arbitrary large allocation.
            validate_payload(
                frame.image_size as usize,
                self.info.width,
                self.info.height,
                self.info.bit_count,
                self.info.compression,
            )?;
            self.scratch.resize(frame.image_size as usize, 0);
            read(&mut self.file, pos, &mut self.scratch)?;
            decode(
                &self.scratch,
                self.info.width,
                self.info.height,
                self.info.bit_count,
                self.info.compression,
                flags,
                out,
            )?;
        }
        self.last = Some((off, frame));
        Ok(frame)
    }
    /// Return a canonical top-down RGB frame; u16 samples are little endian.
    pub fn read_frame(&mut self, index: u32) -> Result<Vec<u8>> {
        let mut out = vec![0; self.info.decoded_bytes as usize];
        self.read_frame_into(index, 3, &mut out)?;
        Ok(out)
    }
    pub fn read_at(&mut self, offset: u64, out: &mut [u8]) -> Result<()> {
        if offset
            .checked_add(out.len() as u64)
            .map_or(true, |v| v > self.info.file_size)
        {
            return Err(Error::format("read exceeds file bounds"));
        }
        read(&mut self.file, offset, out)
    }
    pub fn block_len(&self, kind: u32) -> Result<usize> {
        Ok(match kind {
            0 => self.header.len(),
            1 => self.bitmap.len(),
            2 => self.setup.len(),
            3 => {
                self.last
                    .ok_or_else(|| Error::format("no frame loaded"))?
                    .1
                    .annotation_size as usize
            }
            4 => {
                self.last
                    .ok_or_else(|| Error::format("no frame loaded"))?
                    .1
                    .image_size as usize
            }
            5 => (self.table - u32_at(&self.header, 28) as u64) as usize,
            6 => checked_size(u64::from(self.info.frame_count) * self.offset_bytes as u64)?,
            _ => return Err(Error::format("invalid metadata block kind")),
        })
    }
    pub fn block_into(&mut self, kind: u32, out: &mut [u8]) -> Result<()> {
        let n = self.block_len(kind)?;
        if out.len() < n {
            return Err(Error::format("output buffer too small"));
        }
        let out = &mut out[..n];
        match kind {
            0 => out.copy_from_slice(&self.header),
            1 => out.copy_from_slice(&self.bitmap),
            2 => out.copy_from_slice(&self.setup),
            3 => read(&mut self.file, self.last.unwrap().0, out)?,
            4 => {
                let (off, f) = self.last.unwrap();
                read(&mut self.file, off + f.annotation_size as u64, out)?;
            }
            5 => read(&mut self.file, u32_at(&self.header, 28) as u64, out)?,
            6 => read(&mut self.file, self.table, out)?,
            _ => unreachable!(),
        }
        Ok(())
    }
    /// Copy a frame range without decoding. Preserves metadata and unknown tags;
    /// known per-saved-frame tags are sliced along with their images.
    pub fn trim(&mut self, path: impl AsRef<Path>, start: u32, count: u32) -> Result<()> {
        if count == 0
            || start
                .checked_add(count)
                .map_or(true, |n| n > self.info.frame_count)
        {
            return Err(Error::format("invalid trim range"));
        }
        let path = path.as_ref();
        // create_new protects the input, hard links to it, and existing output files.
        let mut output = OpenOptions::new().write(true).create_new(true).open(path)?;
        let result = self.trim_into(&mut output, start, count);
        if result.is_err() {
            drop(output);
            let _ = std::fs::remove_file(path);
        }
        result
    }
    fn trim_into(&mut self, out: &mut File, start: u32, count: u32) -> Result<()> {
        let first = (self.info.first_frame as i64 + start as i64) as i32;
        let mut header = self.header.clone();
        header[16..20].copy_from_slice(&first.to_le_bytes());
        header[20..24].copy_from_slice(&count.to_le_bytes());
        // Keep FirstMovieImage/TotalImageCount: original recording metadata and old
        // type1001 tags are indexed by the original acquisition, not saved range.
        out.write_all(&header)?;
        let setup_end = u32_at(&self.header, 28) as u64 + self.setup.len() as u64;
        copy_range(&mut self.file, out, 44, setup_end - 44)?;
        let mut pos = setup_end;
        while pos < self.table {
            if self.table - pos < 8 {
                copy_range(&mut self.file, out, pos, self.table - pos)?;
                break;
            }
            let mut tag = [0; 8];
            read(&mut self.file, pos, &mut tag)?;
            let size = u32_at(&tag, 0) as u64;
            let kind = u16_at(&tag, 4);
            if size < 8 || size > self.table - pos {
                return Err(Error::format("invalid tagged metadata block"));
            }
            let item = match kind {
                1002 => Some(8u64),
                1003 => Some(4),
                1004 => Some(get32(&self.setup, 1552) as u64),
                1007 => Some(8),
                1005 | 1006 => {
                    if (size - 8) % self.info.frame_count as u64 == 0 {
                        Some((size - 8) / self.info.frame_count as u64)
                    } else {
                        None
                    }
                }
                _ => None,
            };
            if let Some(item) =
                item.filter(|v| *v > 0 && *v * self.info.frame_count as u64 == size - 8)
            {
                let len = 8 + item * count as u64;
                tag[..4].copy_from_slice(&(len as u32).to_le_bytes());
                out.write_all(&tag)?;
                copy_range(
                    &mut self.file,
                    out,
                    pos + 8 + start as u64 * item,
                    count as u64 * item,
                )?;
            } else {
                copy_range(&mut self.file, out, pos, size)?;
            }
            pos += size;
        }
        let table = out.stream_position()?;
        if table > u32::MAX as u64 {
            return Err(Error::format("metadata exceeds CINE header offset range"));
        }
        header[32..36].copy_from_slice(&(table as u32).to_le_bytes());
        let mut dest = table + count as u64 * self.offset_bytes as u64;
        for i in start..start + count {
            if self.offset_bytes == 4 && dest > u32::MAX as u64 {
                return Err(Error::format("version 0 file exceeds 4 GiB"));
            }
            out.write_all(&dest.to_le_bytes()[..self.offset_bytes])?;
            let (off, fi) = self.location(i)?;
            let _ = off;
            dest += fi.annotation_size as u64 + fi.image_size as u64;
        }
        for i in start..start + count {
            let (off, fi) = self.location(i)?;
            copy_range(
                &mut self.file,
                out,
                off,
                fi.annotation_size as u64 + fi.image_size as u64,
            )?;
        }
        out.seek(SeekFrom::Start(0))?;
        out.write_all(&header)?;
        out.sync_all()?;
        Ok(())
    }
}
fn copy_range(src: &mut File, dst: &mut File, start: u64, len: u64) -> Result<()> {
    src.seek(SeekFrom::Start(start))?;
    if std::io::copy(&mut src.take(len), dst)? != len {
        return Err(Error::format("truncated file while copying"));
    }
    Ok(())
}

fn validate_payload(
    len: usize,
    width: u32,
    height: i32,
    bit_count: u32,
    compression: u32,
) -> Result<(usize, usize, usize)> {
    if width == 0 || height == 0 || height == i32::MIN {
        return Err(Error::format("invalid dimensions"));
    }
    let (channels, bytes) = match bit_count {
        8 => (1, 1),
        16 => (1, 2),
        24 => (3, 1),
        48 => (3, 2),
        _ => return Err(Error::format("unsupported bit depth")),
    };
    let samples = checked_size(
        (width as u64)
            .checked_mul(height.unsigned_abs() as u64)
            .and_then(|n| n.checked_mul(channels))
            .ok_or_else(|| Error::format("image dimensions overflow"))?,
    )?;
    let row = checked_size(width as u64 * channels * bytes)?;
    let h = height.unsigned_abs() as usize;
    match compression {
        0 => {
            let stride = (row + 3) & !3;
            if len != row * h && len != stride * h {
                return Err(Error::format("normal frame payload size mismatch"));
            }
        }
        256 => {
            if bit_count != 16 || len != samples.div_ceil(4) * 5 {
                return Err(Error::format("packed10 frame payload size mismatch"));
            }
        }
        1024 => {
            if bit_count != 16 || len != samples.div_ceil(2) * 3 {
                return Err(Error::format("packed12 frame payload size mismatch"));
            }
        }
        _ => return Err(Error::format("unsupported compression")),
    }
    Ok((samples, row, bytes as usize))
}

/// Decode a payload without any container or language binding dependency.
pub fn decode(
    raw: &[u8],
    width: u32,
    height: i32,
    bit_count: u32,
    compression: u32,
    flags: u32,
    out: &mut [u8],
) -> Result<()> {
    let (samples, row, bytes) = validate_payload(raw.len(), width, height, bit_count, compression)?;
    let len = samples * bytes;
    if out.len() < len {
        return Err(Error::format("output buffer too small"));
    }
    let out = &mut out[..len];
    if compression == 256 {
        for (g, dst) in raw.chunks_exact(5).zip(out.chunks_mut(8)) {
            let codes = [
                ((g[0] as usize) << 2) | (g[1] as usize >> 6),
                ((g[1] as usize & 63) << 4) | (g[2] as usize >> 4),
                ((g[2] as usize & 15) << 6) | (g[3] as usize >> 2),
                ((g[3] as usize & 3) << 8) | g[4] as usize,
            ];
            for (d, code) in dst.chunks_exact_mut(2).zip(codes) {
                d.copy_from_slice(&LOOKUP[code].to_le_bytes());
            }
        }
    } else if compression == 1024 {
        for (g, dst) in raw.chunks_exact(3).zip(out.chunks_mut(4)) {
            let codes = [
                ((g[0] as u16) << 4) | (g[1] as u16 >> 4),
                ((g[1] as u16 & 15) << 8) | g[2] as u16,
            ];
            for (d, v) in dst.chunks_exact_mut(2).zip(codes) {
                d.copy_from_slice(&v.to_le_bytes());
            }
        }
    } else {
        let h = height.unsigned_abs() as usize;
        let stride = raw.len() / h;
        for y in 0..h {
            let source = if flags & 1 != 0 && height > 0 {
                h - 1 - y
            } else {
                y
            };
            out[y * row..(y + 1) * row]
                .copy_from_slice(&raw[source * stride..source * stride + row]);
        }
        if flags & 2 != 0 && matches!(bit_count, 24 | 48) {
            for p in out.chunks_exact_mut(3 * bytes) {
                for b in 0..bytes {
                    p.swap(b, 2 * bytes + b);
                }
            }
        }
    }
    Ok(())
}
