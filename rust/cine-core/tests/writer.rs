use cine_core::writer::{inverse_lut, CineWriter, WriterOptions};
use cine_core::{lookup::LOOKUP, Reader};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};

static SERIAL: AtomicU64 = AtomicU64::new(0);
struct Directory(PathBuf);
impl Directory {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "cine-writer-test-{}-{}",
            std::process::id(),
            SERIAL.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
    fn path(&self) -> PathBuf {
        self.0.join("test.cine")
    }
}
impl Drop for Directory {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}
fn u16_at(bytes: &[u8], at: usize) -> u16 {
    u16::from_le_bytes(bytes[at..at + 2].try_into().unwrap())
}
fn u32_at(bytes: &[u8], at: usize) -> u32 {
    u32::from_le_bytes(bytes[at..at + 4].try_into().unwrap())
}
fn u64_at(bytes: &[u8], at: usize) -> u64 {
    u64::from_le_bytes(bytes[at..at + 8].try_into().unwrap())
}
fn frame_offset(bytes: &[u8], index: usize) -> usize {
    u64_at(bytes, u32_at(bytes, 32) as usize + index * 8) as usize
}
fn encode(path: &Path, options: WriterOptions, frames: &[Vec<u8>]) {
    let mut writer = CineWriter::create(path, options).unwrap();
    for frame in frames {
        writer.write_frame(frame).unwrap();
    }
    assert!(!path.exists());
    writer.finish().unwrap();
}

#[test]
fn normal_mono_has_bottom_up_rows_and_dword_padding() {
    let dir = Directory::new();
    let path = dir.path();
    let frame = vec![1, 2, 3, 4, 5, 6];
    encode(
        &path,
        WriterOptions {
            width: 3,
            height: 2,
            frame_count: 1,
            ..WriterOptions::default()
        },
        &[frame.clone()],
    );
    let bytes = fs::read(&path).unwrap();
    assert_eq!(&bytes[..2], b"CI");
    assert_eq!(u16_at(&bytes, 6), 1);
    assert_eq!(u32_at(&bytes, 52), 2);
    assert_eq!(u32_at(&bytes, 60), 0);
    let offset = frame_offset(&bytes, 0);
    assert_eq!(u32_at(&bytes, offset), 8);
    assert_eq!(u32_at(&bytes, offset + 4), 8);
    assert_eq!(&bytes[offset + 8..], &[4, 5, 6, 0, 1, 2, 3, 0]);
    let mut reader = Reader::open(&path).unwrap();
    assert_eq!(reader.read_frame(0).unwrap(), frame);
}

#[test]
fn normal_rgb_stores_bgr_and_roundtrips_both_container_sizes() {
    for bits in [8, 16] {
        let dir = Directory::new();
        let path = dir.path();
        let values = [1u16, 2, 3, 4, 5, 6];
        let frame: Vec<u8> = if bits == 8 {
            values.iter().map(|&x| x as u8).collect()
        } else {
            values.iter().flat_map(|x| x.to_le_bytes()).collect()
        };
        encode(
            &path,
            WriterOptions {
                width: 1,
                height: 2,
                channels: 3,
                bit_depth: bits,
                frame_count: 1,
                ..WriterOptions::default()
            },
            &[frame.clone()],
        );
        let bytes = fs::read(&path).unwrap();
        let offset = frame_offset(&bytes, 0) + 8;
        if bits == 8 {
            assert_eq!(&bytes[offset..], &[6, 5, 4, 0, 3, 2, 1, 0]);
        } else {
            assert_eq!(
                &bytes[offset..],
                &[6, 0, 5, 0, 4, 0, 0, 0, 3, 0, 2, 0, 1, 0, 0, 0]
            );
        }
        assert_eq!(Reader::open(&path).unwrap().read_frame(0).unwrap(), frame);
    }
}

#[test]
fn packed10_quantizes_every_linear_value_to_the_nearest_lut_value() {
    let dir = Directory::new();
    let path = dir.path();
    let frame: Vec<u8> = (0u16..4096).flat_map(u16::to_le_bytes).collect();
    encode(
        &path,
        WriterOptions {
            width: 64,
            height: 64,
            bit_depth: 12,
            packed10: true,
            frame_count: 1,
            cfa: 3,
            ..WriterOptions::default()
        },
        &[frame],
    );
    let bytes = fs::read(&path).unwrap();
    assert_eq!(u16_at(&bytes, 4), 2);
    assert_eq!(u32_at(&bytes, 60), 256);
    assert_eq!(u32_at(&bytes, 80), 1024);
    assert_eq!(u32_at(&bytes, 84 + 896), 10);
    let data = &bytes[frame_offset(&bytes, 0) + 8..];
    let mut index = 0u16;
    for group in data.chunks_exact(5) {
        let bits = group.iter().fold(0u64, |acc, &x| (acc << 8) | u64::from(x));
        for shift in [30, 20, 10, 0] {
            let code = ((bits >> shift) & 1023) as usize;
            let actual = LOOKUP[code];
            let error = actual.abs_diff(index);
            assert!(LOOKUP.iter().all(|&sample| sample.abs_diff(index) >= error));
            assert!(error <= 15);
            index += 1;
        }
    }
    assert_eq!(index, 4096);
    assert_eq!(inverse_lut()[17], 13);
    let decoded = Reader::open(&path).unwrap().read_frame(0).unwrap();
    for (index, pair) in decoded.chunks_exact(2).enumerate() {
        assert_eq!(
            u16::from_le_bytes([pair[0], pair[1]]),
            LOOKUP[inverse_lut()[index] as usize]
        );
    }
}

#[test]
fn unknown_length_stream_has_correct_offsets_count_and_timing() {
    let dir = Directory::new();
    let path = dir.path();
    let frames = vec![vec![1, 2], vec![3, 4], vec![5, 6]];
    encode(
        &path,
        WriterOptions {
            width: 2,
            height: 1,
            first_frame: -1,
            frame_rate: 29.97,
            ..WriterOptions::default()
        },
        &frames,
    );
    let bytes = fs::read(&path).unwrap();
    assert_eq!(u32_at(&bytes, 12), 3);
    assert_eq!(u32_at(&bytes, 20), 3);
    assert_eq!(u32_at(&bytes, 16) as i32, -1);
    let time_start = 84 + 10_684;
    assert_eq!(u32_at(&bytes, time_start), 32);
    assert_eq!(u16_at(&bytes, time_start + 4), 1002);
    let step = u64_at(&bytes, time_start + 16) - u64_at(&bytes, time_start + 8);
    assert!((step as f64 - 4_294_967_296.0 / 29.97).abs() <= 1.0);
    assert_eq!(u64_at(&bytes, time_start + 16), u64_at(&bytes, 36));
    let mut reader = Reader::open(&path).unwrap();
    for (index, expected) in frames.iter().enumerate() {
        assert_eq!(&reader.read_frame(index as u32).unwrap(), expected);
    }
    assert_eq!(fs::read_dir(&dir.0).unwrap().count(), 1);
}

#[test]
fn invalid_frame_can_be_corrected_without_corrupting_output() {
    let dir = Directory::new();
    let path = dir.path();
    let options = WriterOptions {
        width: 2,
        height: 1,
        bit_depth: 12,
        frame_count: 1,
        ..WriterOptions::default()
    };
    let mut writer = CineWriter::create(&path, options).unwrap();
    assert!(writer.write_frame(&[1]).is_err());
    assert!(writer.write_frame(&[0, 16, 0, 0]).is_err());
    assert_eq!(writer.frames_written(), 0);
    writer.write_frame(&[0, 0, 1, 0]).unwrap();
    assert!(writer.write_frame(&[0, 0, 1, 0]).is_err());
    writer.finish().unwrap();
    assert_eq!(
        Reader::open(&path).unwrap().read_frame(0).unwrap(),
        [0, 0, 1, 0]
    );
}

#[test]
fn incomplete_files_are_not_published_and_drop_cleans_temporary_files() {
    let dir = Directory::new();
    let path = dir.path();
    {
        let mut writer = CineWriter::create(
            &path,
            WriterOptions {
                width: 1,
                height: 1,
                frame_count: 2,
                ..WriterOptions::default()
            },
        )
        .unwrap();
        writer.write_frame(&[1]).unwrap();
        assert!(writer.finish().is_err());
        assert!(!path.exists());
    }
    assert_eq!(fs::read_dir(&dir.0).unwrap().count(), 0);
}

#[test]
fn existing_destination_is_never_replaced_even_after_create() {
    let dir = Directory::new();
    let path = dir.path();
    let options = WriterOptions {
        width: 1,
        height: 1,
        frame_count: 1,
        ..WriterOptions::default()
    };
    let mut writer = CineWriter::create(&path, options.clone()).unwrap();
    writer.write_frame(&[1]).unwrap();
    fs::write(&path, b"keep me").unwrap();
    assert!(writer.finish().is_err());
    assert_eq!(fs::read(&path).unwrap(), b"keep me");
    assert!(CineWriter::create(&path, options).is_err());
    drop(writer);
    assert_eq!(fs::read_dir(&dir.0).unwrap().count(), 1);
}

#[test]
fn dimensions_counts_and_ranges_are_validated_before_output_creation() {
    let dir = Directory::new();
    let base = WriterOptions {
        width: 4,
        height: 1,
        bit_depth: 12,
        packed10: true,
        frame_count: 1,
        ..WriterOptions::default()
    };
    let mut invalid = vec![];
    let mut option = base.clone();
    option.width = 0;
    invalid.push(option);
    let mut option = base.clone();
    option.channels = 3;
    invalid.push(option);
    let mut option = base.clone();
    option.bit_depth = 16;
    invalid.push(option);
    let mut option = base.clone();
    option.frame_rate = f64::NAN;
    invalid.push(option);
    let mut option = base.clone();
    option.height = 0;
    invalid.push(option);
    let mut option = base.clone();
    option.first_frame = i32::MAX;
    option.frame_count = 2;
    invalid.push(option);
    let mut option = base;
    option.width = i32::MAX as u32;
    option.height = i32::MAX as u32;
    invalid.push(option);
    for options in invalid {
        assert!(CineWriter::create(dir.path(), options).is_err());
    }
    assert_eq!(fs::read_dir(&dir.0).unwrap().count(), 0);
}

#[test]
fn generic_rgb8_packed_conversion_and_partial_group() {
    let dir = Directory::new();
    let path = dir.path();
    let mut writer = CineWriter::create(
        &path,
        WriterOptions {
            width: 3,
            height: 1,
            channels: 1,
            bit_depth: 12,
            packed10: true,
            frame_count: 1,
            cfa: 4,
            ..WriterOptions::default()
        },
    )
    .unwrap();
    writer
        .write_image(&[255, 9, 7, 8, 128, 6, 64, 5, 4], 1, 3)
        .unwrap();
    writer.finish().unwrap();
    let bytes = fs::read(&path).unwrap();
    let start = frame_offset(&bytes, 0);
    assert_eq!(u32_at(&bytes, start + 4), 5);
    let decoded = Reader::open(&path).unwrap().read_frame(0).unwrap();
    let expected = [4095usize, (128 * 4095 + 127) / 255, (64 * 4095 + 127) / 255];
    for (pair, linear) in decoded.chunks_exact(2).zip(expected) {
        assert_eq!(
            u16::from_le_bytes([pair[0], pair[1]]),
            LOOKUP[inverse_lut()[linear] as usize]
        );
    }
}
