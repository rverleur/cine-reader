//! Streaming CINE encoding with bounded memory and atomic publication.
//!
//! Input is top-down, tightly packed RGB or monochrome data. Normal CINE frames
//! are stored bottom-up and BGR; Phantom P10 frames are stored top-down. P10
//! input is linear 12-bit data in little-endian `u16` samples, quantized to the
//! nearest entry of the Phantom transfer table (ties choose the smaller code).
//! Normal encoding is lossless. No implicit rescaling of samples is performed.
//!
//! A known frame count enables a single sequential write. A zero count streams
//! frames to a temporary file and copies them once at finalization, so arbitrary
//! iterators never require a frame stack in memory. The target is published only
//! after successful finalization and is never overwritten. Filesystems without
//! hard links (for example ExFAT) use an exclusive-create copy fallback: the
//! destination is visible during that last copy, and removed if copying fails.

use crate::{Error, Result};
use std::fs::{self, File, OpenOptions};
use std::io::{BufWriter, Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::OnceLock;
use std::time::{SystemTime, UNIX_EPOCH};

const SETUP_SIZE: usize = 10_684;
const SETUP_OFFSET: u64 = 84;
const IO_BUFFER_SIZE: usize = 1024 * 1024;
static TEMP_SERIAL: AtomicU64 = AtomicU64::new(0);
static INVERSE_LUT: OnceLock<[u16; 4096]> = OnceLock::new();

/// Parameters shared by the standalone Rust and foreign-language writers.
#[derive(Clone, Debug)]
pub struct WriterOptions {
    pub width: u32,
    pub height: u32,
    /// One monochrome/Bayer channel or three RGB channels.
    pub channels: u32,
    /// Normal: 8 to 16 bits; P10: 12-bit linear input in a u16 container.
    pub bit_depth: u32,
    pub packed10: bool,
    /// Zero means that the count is unknown until `finish`.
    pub frame_count: u32,
    pub first_frame: i32,
    pub frame_rate: f64,
    /// Phantom CFA code, 0 for monochrome/interpolated RGB, 1..=6 for raw CFA.
    pub cfa: u32,
}

impl Default for WriterOptions {
    fn default() -> Self {
        Self {
            width: 0,
            height: 0,
            channels: 1,
            bit_depth: 8,
            packed10: false,
            frame_count: 0,
            first_frame: 0,
            frame_rate: 30.0,
            cfa: 0,
        }
    }
}

impl WriterOptions {
    fn layout(&self) -> Result<Layout> {
        if self.width == 0
            || self.height == 0
            || self.width > i32::MAX as u32
            || self.height > i32::MAX as u32
        {
            return Err(Error::format(
                "width and height must be positive signed 32-bit dimensions",
            ));
        }
        if self.channels != 1 && self.channels != 3 {
            return Err(Error::format("CINE supports one or three channels"));
        }
        if !(8..=16).contains(&self.bit_depth) {
            return Err(Error::format("bit_depth must be between 8 and 16"));
        }
        if !self.frame_rate.is_finite() || self.frame_rate <= 0.0 {
            return Err(Error::format("frame_rate must be finite and positive"));
        }
        if self.cfa > 6 || (self.channels == 3 && self.cfa != 0) {
            return Err(Error::format(
                "CFA must be 0..6 and is only valid for single-channel frames",
            ));
        }
        let sample_bytes = if self.bit_depth == 8 { 1u64 } else { 2 };
        let row_bytes = u64::from(self.width) * u64::from(self.channels) * sample_bytes;
        let input_bytes = row_bytes
            .checked_mul(u64::from(self.height))
            .ok_or_else(|| Error::format("image dimensions overflow"))?;
        let samples = u64::from(self.width) * u64::from(self.height);
        // 8/24-bit Windows DIB rows are DWORD-aligned. Phantom's non-Windows
        // 16/48-bit extensions are arrays of u16 samples, without row padding.
        // Readers accept both conventions for historical third-party files.
        let row_stride = if sample_bytes == 1 {
            (row_bytes + 3) & !3
        } else {
            row_bytes
        };
        let payload_bytes = if self.packed10 {
            if self.channels != 1 || self.bit_depth != 12 {
                return Err(Error::format(
                    "packed10 requires one channel and linear 12-bit u16 input",
                ));
            }
            samples.div_ceil(4) * 5
        } else {
            row_stride
                .checked_mul(u64::from(self.height))
                .ok_or_else(|| Error::format("image dimensions overflow"))?
        };
        if payload_bytes > u64::from(u32::MAX) {
            return Err(Error::format("a CINE image payload cannot exceed 4 GiB"));
        }
        self.check_count(self.frame_count)?;
        Ok(Layout {
            input_bytes: usize::try_from(input_bytes)
                .map_err(|_| Error::format("image is too large for this processor"))?,
            row_bytes: usize::try_from(row_bytes)
                .map_err(|_| Error::format("row is too large for this processor"))?,
            row_stride: usize::try_from(row_stride)
                .map_err(|_| Error::format("row is too large for this processor"))?,
            payload_bytes: payload_bytes as u32,
            sample_bytes: sample_bytes as usize,
        })
    }

    fn check_count(&self, count: u32) -> Result<()> {
        if count > 0 && i64::from(self.first_frame) + i64::from(count) - 1 > i64::from(i32::MAX) {
            return Err(Error::format(
                "last frame number exceeds signed 32-bit range",
            ));
        }
        let offsets_start = SETUP_OFFSET + SETUP_SIZE as u64 + 8 + u64::from(count) * 8;
        if offsets_start > u64::from(u32::MAX) {
            return Err(Error::format(
                "image timestamp block exceeds CINE header addressing limits",
            ));
        }
        Ok(())
    }
}

struct Layout {
    input_bytes: usize,
    row_bytes: usize,
    row_stride: usize,
    payload_bytes: u32,
    sample_bytes: usize,
}

/// A frame-at-a-time writer. Dropping it without `finish` discards the output.
pub struct CineWriter {
    options: WriterOptions,
    layout: Layout,
    destination: PathBuf,
    temporary: PathBuf,
    output: Option<BufWriter<File>>,
    buffer: Vec<u8>,
    conversion: Vec<u8>,
    written: u32,
    trigger_time: u64,
    finished: bool,
    failed: bool,
}

impl CineWriter {
    pub fn create(path: impl AsRef<Path>, options: WriterOptions) -> Result<Self> {
        let layout = options.layout()?;
        let destination = path.as_ref().to_path_buf();
        if destination.try_exists()? {
            return Err(Error::format(
                "output already exists; choose a new filename",
            ));
        }
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| Error::format("system clock is earlier than the Unix epoch"))?;
        if now.as_secs() > u64::from(u32::MAX) {
            return Err(Error::format(
                "system clock exceeds the CINE timestamp range",
            ));
        }
        let trigger_time =
            (now.as_secs() << 32) | ((u64::from(now.subsec_nanos()) << 32) / 1_000_000_000);
        let (temporary, file) = temporary_file(&destination)?;
        let mut writer = Self {
            options,
            layout,
            destination,
            temporary,
            output: Some(BufWriter::with_capacity(IO_BUFFER_SIZE, file)),
            buffer: Vec::new(),
            conversion: Vec::new(),
            written: 0,
            trigger_time,
            finished: false,
            failed: false,
        };
        if writer.options.frame_count != 0 {
            let mut output = writer.output.take().unwrap();
            let result = writer.write_prefix(&mut output, writer.options.frame_count);
            writer.output = Some(output);
            result?;
        }
        Ok(writer)
    }

    pub fn options(&self) -> &WriterOptions {
        &self.options
    }
    pub fn frames_written(&self) -> u32 {
        self.written
    }

    /// Encode a generic image, including u8/RGB conversion for packed output.
    ///
    /// Normal files require matching channels and sample size. Packed output
    /// expands u8 samples to the full 12-bit range. Three-channel packed input
    /// is mosaiced using the configured CFA: only one source color survives at
    /// each pixel. Use normal RGB encoding when all three channels must survive.
    pub fn write_image(&mut self, data: &[u8], sample_bytes: u32, channels: u32) -> Result<()> {
        if !matches!(sample_bytes, 1 | 2) || !matches!(channels, 1 | 3) {
            return Err(Error::format(
                "images require one or three channels of u8 or little-endian u16 samples",
            ));
        }
        if !self.options.packed10 {
            if sample_bytes as usize != self.layout.sample_bytes
                || channels != self.options.channels
            {
                return Err(Error::format(
                    "image dtype and channels must match the normal CINE writer",
                ));
            }
            return self.write_frame(data);
        }
        if channels == 3 && self.options.cfa == 0 {
            return Err(Error::format(
                "packed RGB input requires a nonzero CFA pattern",
            ));
        }
        let pixels = self.options.width as usize * self.options.height as usize;
        let expected = pixels
            .checked_mul(sample_bytes as usize)
            .and_then(|n| n.checked_mul(channels as usize))
            .ok_or_else(|| Error::format("image dimensions overflow"))?;
        if data.len() != expected {
            return Err(Error::format(format!(
                "image has {} bytes; expected {expected}",
                data.len()
            )));
        }
        if sample_bytes == 2 && channels == 1 {
            return self.write_frame(data);
        }
        let mut conversion = std::mem::take(&mut self.conversion);
        let result = (|| {
            let required = self.layout.input_bytes;
            if conversion.len() < required {
                conversion
                    .try_reserve_exact(required - conversion.len())
                    .map_err(|_| Error::format("cannot allocate image conversion buffer"))?;
            }
            conversion.resize(required, 0);
            // Channel indices in top-down sensor order: R=0, G=1, B=2.
            let pattern = match self.options.cfa {
                1 | 3 => [1usize, 2, 0, 1],
                2 | 6 => [2, 1, 1, 0],
                5 => [1, 0, 2, 1],
                _ => [0, 1, 1, 2],
            };
            for (index, output) in conversion.chunks_exact_mut(2).enumerate() {
                let row = index / self.options.width as usize;
                let col = index % self.options.width as usize;
                let channel = if channels == 1 {
                    0
                } else {
                    pattern[(row & 1) * 2 + (col & 1)]
                };
                let at = (index * channels as usize + channel) * sample_bytes as usize;
                let value = if sample_bytes == 1 {
                    ((u32::from(data[at]) * 4095 + 127) / 255) as u16
                } else {
                    u16::from_le_bytes([data[at], data[at + 1]])
                };
                output.copy_from_slice(&value.to_le_bytes());
            }
            self.write_frame(&conversion)
        })();
        self.conversion = conversion;
        result
    }

    /// Validate and encode one tightly packed top-down RGB or monochrome frame.
    /// Invalid frames do not change the writer; an I/O failure aborts it.
    pub fn write_frame(&mut self, data: &[u8]) -> Result<()> {
        if self.finished || self.failed {
            return Err(Error::format("writer is already finished or aborted"));
        }
        if data.len() != self.layout.input_bytes {
            return Err(Error::format(format!(
                "frame has {} bytes; expected {}",
                data.len(),
                self.layout.input_bytes
            )));
        }
        let next_count = self
            .written
            .checked_add(1)
            .ok_or_else(|| Error::format("too many frames"))?;
        self.options.check_count(next_count)?;
        if self.options.frame_count != 0 && next_count > self.options.frame_count {
            return Err(Error::format("more frames supplied than frame_count"));
        }
        if self.layout.sample_bytes == 2 && self.options.bit_depth < 16 {
            let maximum = (1u32 << self.options.bit_depth) - 1;
            if data
                .chunks_exact(2)
                .any(|pair| u32::from(u16::from_le_bytes([pair[0], pair[1]])) > maximum)
            {
                return Err(Error::format(format!(
                    "a sample exceeds the {}-bit input range",
                    self.options.bit_depth
                )));
            }
        }
        let payload_length = self.layout.payload_bytes as usize;
        if self.buffer.len() < payload_length {
            self.buffer
                .try_reserve_exact(payload_length - self.buffer.len())
                .map_err(|_| Error::format("cannot allocate frame encoding buffer"))?;
        }
        self.buffer.resize(payload_length, 0);
        if self.options.packed10 {
            let table = inverse_lut();
            for (samples, packed) in data.chunks(8).zip(self.buffer.chunks_exact_mut(5)) {
                let code = |at: usize| {
                    if at + 1 < samples.len() {
                        table[u16::from_le_bytes([samples[at], samples[at + 1]]) as usize]
                    } else {
                        0
                    }
                };
                let a = code(0);
                let b = code(2);
                let c = code(4);
                let d = code(6);
                packed[0] = (a >> 2) as u8;
                packed[1] = ((a << 6) | (b >> 4)) as u8;
                packed[2] = ((b << 4) | (c >> 6)) as u8;
                packed[3] = ((c << 2) | (d >> 8)) as u8;
                packed[4] = d as u8;
            }
        } else {
            for (input, output) in data
                .chunks_exact(self.layout.row_bytes)
                .rev()
                .zip(self.buffer.chunks_exact_mut(self.layout.row_stride))
            {
                let output = &mut output[..self.layout.row_bytes];
                if self.options.channels == 1 {
                    output.copy_from_slice(input);
                } else if self.layout.sample_bytes == 1 {
                    for (rgb, bgr) in input.chunks_exact(3).zip(output.chunks_exact_mut(3)) {
                        bgr.copy_from_slice(&[rgb[2], rgb[1], rgb[0]]);
                    }
                } else {
                    for (rgb, bgr) in input.chunks_exact(6).zip(output.chunks_exact_mut(6)) {
                        bgr.copy_from_slice(&[rgb[4], rgb[5], rgb[2], rgb[3], rgb[0], rgb[1]]);
                    }
                }
            }
        }
        let output = self.output.as_mut().unwrap();
        let result = output
            .write_all(&8u32.to_le_bytes())
            .and_then(|_| output.write_all(&self.layout.payload_bytes.to_le_bytes()))
            .and_then(|_| output.write_all(&self.buffer));
        if let Err(error) = result {
            self.failed = true;
            return Err(error.into());
        }
        self.written = next_count;
        Ok(())
    }

    /// Finish and publish the file. The destination is never replaced.
    pub fn finish(&mut self) -> Result<()> {
        if self.finished {
            return Ok(());
        }
        if self.failed {
            return Err(Error::format("writer was aborted after an I/O failure"));
        }
        if self.written == 0 {
            return Err(Error::format("cannot write an empty CINE"));
        }
        if self.options.frame_count != 0 && self.written != self.options.frame_count {
            return Err(Error::format(format!(
                "wrote {} frames; expected {}",
                self.written, self.options.frame_count
            )));
        }
        let result = self.finish_inner();
        if result.is_err() {
            self.failed = true;
        }
        result
    }

    fn finish_inner(&mut self) -> Result<()> {
        let mut output = self.output.take().unwrap();
        output.flush()?;
        let mut file = output.into_inner().map_err(|error| error.into_error())?;
        if self.options.frame_count == 0 {
            let (complete_path, complete_file) = temporary_file(&self.destination)?;
            let result = (|| -> Result<()> {
                let mut complete = BufWriter::with_capacity(IO_BUFFER_SIZE, complete_file);
                self.write_prefix(&mut complete, self.written)?;
                file.seek(SeekFrom::Start(0))?;
                self.buffer.resize(IO_BUFFER_SIZE, 0);
                loop {
                    let count = file.read(&mut self.buffer)?;
                    if count == 0 {
                        break;
                    }
                    complete.write_all(&self.buffer[..count])?;
                }
                complete.flush()?;
                complete.get_ref().sync_all()?;
                Ok(())
            })();
            drop(file);
            if let Err(error) = result {
                let _ = fs::remove_file(&complete_path);
                return Err(error);
            }
            let old_temporary = std::mem::replace(&mut self.temporary, complete_path);
            let _ = fs::remove_file(old_temporary);
        } else {
            file.sync_all()?;
            drop(file);
        }
        // A hard link is an atomic, no-clobber publication on the same filesystem.
        // Unlike exists()+rename(), it cannot overwrite a concurrently created file.
        if let Err(error) = fs::hard_link(&self.temporary, &self.destination) {
            if error.kind() == std::io::ErrorKind::AlreadyExists {
                return Err(error.into());
            }
            // ExFAT/FAT and some network mounts have no hard-link support. The
            // fallback retains no-clobber behavior, but is not an atomic publish.
            publish_copy(&self.temporary, &self.destination)?;
        }
        self.finished = true;
        self.buffer = Vec::new();
        self.conversion = Vec::new();
        // Publication has succeeded even if antivirus/indexing delays temp cleanup.
        let _ = fs::remove_file(&self.temporary);
        Ok(())
    }

    fn write_prefix(&self, output: &mut impl Write, count: u32) -> Result<()> {
        self.options.check_count(count)?;
        let time_start = SETUP_OFFSET + SETUP_SIZE as u64;
        let time_size = 8 + u64::from(count) * 8;
        let offsets_start = time_start + time_size;
        let data_start = offsets_start + u64::from(count) * 8;
        let mut header = [0u8; 44];
        header[..2].copy_from_slice(b"CI");
        set_u16(&mut header, 2, 44);
        set_u16(&mut header, 4, if self.options.cfa != 0 { 2 } else { 0 });
        set_u16(&mut header, 6, 1);
        set_u32(&mut header, 8, self.options.first_frame as u32);
        set_u32(&mut header, 12, count);
        set_u32(&mut header, 16, self.options.first_frame as u32);
        set_u32(&mut header, 20, count);
        set_u32(&mut header, 24, 44);
        set_u32(&mut header, 28, SETUP_OFFSET as u32);
        set_u32(&mut header, 32, offsets_start as u32);
        header[36..44].copy_from_slice(&self.trigger_time.to_le_bytes());
        output.write_all(&header)?;

        let mut bitmap = [0u8; 40];
        set_u32(&mut bitmap, 0, 40);
        set_u32(&mut bitmap, 4, self.options.width);
        set_u32(&mut bitmap, 8, self.options.height);
        set_u16(&mut bitmap, 12, 1);
        set_u16(
            &mut bitmap,
            14,
            (self.layout.sample_bytes * 8 * self.options.channels as usize) as u16,
        );
        set_u32(&mut bitmap, 16, if self.options.packed10 { 256 } else { 0 });
        set_u32(&mut bitmap, 20, self.layout.payload_bytes);
        let stored_bits = if self.options.packed10 {
            10
        } else {
            self.options.bit_depth
        };
        if self.layout.sample_bytes == 2 {
            set_u32(&mut bitmap, 36, 1u32 << stored_bits);
        }
        output.write_all(&bitmap)?;

        let mut setup = [0u8; SETUP_SIZE];
        set_u16(
            &mut setup,
            0,
            self.options.frame_rate.round().min(u16::MAX as f64) as u16,
        );
        setup[140..142].copy_from_slice(b"ST");
        set_u16(&mut setup, 142, SETUP_SIZE as u16);
        setup[150] = 1; // SamplesPerImage, even with no acquisition channels.
        set_u16(
            &mut setup,
            737,
            self.options.width.min(u16::MAX as u32) as u16,
        );
        set_u16(
            &mut setup,
            739,
            self.options.height.min(u16::MAX as u32) as u16,
        );
        set_u32(
            &mut setup,
            768,
            self.options.frame_rate.round().min(u32::MAX as f64) as u32,
        );
        let exposure_ns = (1_000_000_000.0 / self.options.frame_rate).min(u32::MAX as f64) as u32;
        set_u16(
            &mut setup,
            2,
            (exposure_ns / 1000).min(u16::MAX as u32) as u16,
        );
        set_u32(&mut setup, 772, exposure_ns / 1000);
        let last_exclusive = i64::from(self.options.first_frame) + i64::from(count);
        set_u32(
            &mut setup,
            780,
            last_exclusive.max(0).min(i64::from(count)) as u32,
        );
        set_u32(
            &mut setup,
            788,
            u32::from(self.options.cfa != 0 || self.options.channels == 3),
        );
        set_u32(&mut setup, 800, 804); // File-structure revision supported by this writer.
        set_u32(&mut setup, 808, self.options.cfa);
        for offset in (852..884).step_by(4) {
            set_f32(&mut setup, offset, 1.0);
        }
        for offset in [888, 892] {
            set_f32(&mut setup, offset, 1.0);
        }
        set_u32(&mut setup, 896, stored_bits);
        set_u32(&mut setup, 904, (1u32 << stored_bits) - 1);
        set_u32(&mut setup, 1556, 1);
        set_u32(&mut setup, 1568, exposure_ns);
        set_u32(&mut setup, 1588, self.options.width);
        set_u32(&mut setup, 1592, self.options.height);
        set_text(&mut setup, 1596, "Encoded by cine-handler Rust backend");
        set_u32(&mut setup, 5724, u32::from(self.options.cfa != 0));
        set_u32(&mut setup, 5736, (1u32 << stored_bits) - 1);
        for offset in [6012, 6016, 6024, 6052, 6900, 7240, 7244, 7248, 10388] {
            set_f32(&mut setup, offset, 1.0);
        }
        for offset in [6832, 6848, 6864, 7252, 7268, 7284] {
            set_f32(&mut setup, offset, 1.0);
        }
        set_f32(
            &mut setup,
            6976,
            self.options.frame_rate.min(f32::MAX as f64) as f32,
        );
        set_text(&mut setup, 9856, "cine-handler Rust backend");
        set_u32(&mut setup, 10112, self.options.bit_depth);
        setup[10400..10408].copy_from_slice(&self.options.frame_rate.to_le_bytes());
        output.write_all(&setup)?;

        output.write_all(&(time_size as u32).to_le_bytes())?;
        output.write_all(&1002u16.to_le_bytes())?;
        output.write_all(&0u16.to_le_bytes())?;
        for index in 0..count {
            let frame_number = i64::from(self.options.first_frame) + i64::from(index);
            let offset = frame_number as f64 / self.options.frame_rate * 4_294_967_296.0;
            if !offset.is_finite() || offset.abs() > u64::MAX as f64 {
                return Err(Error::format(
                    "image timestamp is outside the CINE TIME64 range",
                ));
            }
            let absolute = i128::from(self.trigger_time) + offset.round() as i128;
            let time = u64::try_from(absolute)
                .map_err(|_| Error::format("image timestamp is outside the CINE TIME64 range"))?;
            output.write_all(&time.to_le_bytes())?;
        }
        let frame_bytes = 8 + u64::from(self.layout.payload_bytes);
        for index in 0..count {
            output.write_all(&(data_start + u64::from(index) * frame_bytes).to_le_bytes())?;
        }
        Ok(())
    }
}

impl Drop for CineWriter {
    fn drop(&mut self) {
        // Close before unlinking, which is required on Windows.
        self.output.take();
        let _ = fs::remove_file(&self.temporary);
    }
}

fn temporary_file(destination: &Path) -> Result<(PathBuf, File)> {
    let parent = destination
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    let name = destination
        .file_name()
        .ok_or_else(|| Error::format("output must be a filename"))?;
    for _ in 0..100 {
        let mut temporary_name = name.to_os_string();
        temporary_name.push(format!(
            ".cine-tmp-{}-{}",
            std::process::id(),
            TEMP_SERIAL.fetch_add(1, Ordering::Relaxed)
        ));
        let temporary = parent.join(temporary_name);
        match OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .open(&temporary)
        {
            Ok(file) => return Ok((temporary, file)),
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(error.into()),
        }
    }
    Err(Error::format("could not create a unique temporary output"))
}

fn publish_copy(source: &Path, destination: &Path) -> Result<()> {
    let mut input = File::open(source)?;
    let mut output = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(destination)?;
    let result = (|| -> Result<()> {
        let expected = input.metadata()?.len();
        if std::io::copy(&mut input, &mut output)? != expected {
            return Err(Error::format("temporary output changed while publishing"));
        }
        output.sync_all()?;
        Ok(())
    })();
    drop(output);
    if result.is_err() {
        let _ = fs::remove_file(destination);
    }
    result
}

/// Maps linear 12-bit samples to the closest Phantom P10 code.
pub fn inverse_lut() -> &'static [u16; 4096] {
    INVERSE_LUT.get_or_init(|| {
        let mut inverse = [0u16; 4096];
        let lut = &crate::lookup::LOOKUP;
        // Built only once: first minimum also gives deterministic duplicate/tie handling.
        for (value, code) in inverse.iter_mut().enumerate() {
            *code = lut
                .iter()
                .enumerate()
                .min_by_key(|(_, sample)| (i32::from(**sample) - value as i32).abs())
                .unwrap()
                .0 as u16;
        }
        inverse
    })
}

fn set_u16(buffer: &mut [u8], offset: usize, value: u16) {
    buffer[offset..offset + 2].copy_from_slice(&value.to_le_bytes());
}
fn set_u32(buffer: &mut [u8], offset: usize, value: u32) {
    buffer[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
}
fn set_f32(buffer: &mut [u8], offset: usize, value: f32) {
    buffer[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
}
fn set_text(buffer: &mut [u8], offset: usize, value: &str) {
    buffer[offset..offset + value.len()].copy_from_slice(value.as_bytes());
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn copy_publication_fallback_preserves_content_and_never_overwrites() {
        let destination = std::env::temp_dir().join(format!(
            "cine-publish-{}-{}",
            std::process::id(),
            TEMP_SERIAL.fetch_add(1, Ordering::Relaxed)
        ));
        let (source, mut file) = temporary_file(&destination).unwrap();
        file.write_all(b"complete CINE bytes").unwrap();
        drop(file);
        publish_copy(&source, &destination).unwrap();
        assert_eq!(fs::read(&destination).unwrap(), b"complete CINE bytes");
        fs::write(&source, b"must not replace").unwrap();
        assert!(publish_copy(&source, &destination).is_err());
        assert_eq!(fs::read(&destination).unwrap(), b"complete CINE bytes");
        fs::remove_file(source).unwrap();
        fs::remove_file(destination).unwrap();
    }
}
