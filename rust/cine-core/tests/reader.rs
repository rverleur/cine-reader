use cine_core::{decode, Reader};
use std::{
    fs,
    path::PathBuf,
    sync::atomic::{AtomicU64, Ordering},
};

static SERIAL: AtomicU64 = AtomicU64::new(0);
struct Fixture(PathBuf);
impl Fixture {
    fn new(bytes: &[u8]) -> Self {
        let p = std::env::temp_dir().join(format!(
            "cine-reader-test-{}-{}.cine",
            std::process::id(),
            SERIAL.fetch_add(1, Ordering::Relaxed)
        ));
        fs::write(&p, bytes).unwrap();
        Self(p)
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}
fn put16(b: &mut [u8], p: usize, v: u16) {
    b[p..p + 2].copy_from_slice(&v.to_le_bytes());
}
fn put32(b: &mut [u8], p: usize, v: u32) {
    b[p..p + 4].copy_from_slice(&v.to_le_bytes());
}
fn fixture(version: u16) -> Vec<u8> {
    let step = if version == 0 { 4 } else { 8 };
    let table = 228;
    let first = table + step * 2;
    let mut b = vec![0; first];
    b[..2].copy_from_slice(b"CI");
    put16(&mut b, 2, 44);
    put16(&mut b, 6, version);
    put32(&mut b, 8, (-5i32) as u32);
    put32(&mut b, 12, 2);
    put32(&mut b, 16, (-5i32) as u32);
    put32(&mut b, 20, 2);
    put32(&mut b, 24, 44);
    put32(&mut b, 28, 84);
    put32(&mut b, 32, table as u32);
    put32(&mut b, 44, 40);
    put32(&mut b, 48, 3);
    put32(&mut b, 52, 2);
    put16(&mut b, 56, 1);
    put16(&mut b, 58, 8);
    put32(&mut b, 64, 8);
    b[224..226].copy_from_slice(b"ST");
    put16(&mut b, 226, 144);
    for i in 0..2 {
        let offset = b.len() as u64;
        b[table + i * step..table + (i + 1) * step].copy_from_slice(&offset.to_le_bytes()[..step]);
        b.extend_from_slice(&8u32.to_le_bytes());
        b.extend_from_slice(&8u32.to_le_bytes());
        b.extend_from_slice(&[1 + i as u8, 2, 3, 0, 4, 5, 6, 0]);
    }
    b
}
#[test]
fn versions_padding_and_orientation() {
    for v in [0, 1] {
        let f = Fixture::new(&fixture(v));
        let mut r = Reader::open(&f.0).unwrap();
        assert_eq!(r.info.first_frame, -5);
        assert_eq!(r.read_frame(0).unwrap(), [4, 5, 6, 1, 2, 3]);
        let mut out = [0; 6];
        r.read_frame_into(1, 0, &mut out).unwrap();
        assert_eq!(out, [2, 2, 3, 4, 5, 6]);
        assert_eq!(r.offset(2).unwrap(), r.info.file_size);
        assert!(r.read_frame(2).is_err());
    }
}
#[test]
fn packed12_and_plain_10_bit_container() {
    let mut out = [0; 4];
    decode(&[0xab, 0xc1, 0x23], 2, 1, 16, 1024, 3, &mut out).unwrap();
    assert_eq!(out, [0xbc, 0x0a, 0x23, 0x01]);
    decode(&[0xff, 3, 0, 2], 2, 1, 16, 0, 0, &mut out).unwrap();
    assert_eq!(out, [0xff, 3, 0, 2]);
}
#[test]
fn rgb_and_signed_height() {
    let raw = [1, 2, 3, 4, 5, 6];
    let mut out = [0; 6];
    decode(&raw, 1, -2, 24, 0, 3, &mut out).unwrap();
    assert_eq!(out, [3, 2, 1, 6, 5, 4]);
}
#[test]
fn rejects_truncated_and_corrupt_files() {
    for len in [0, 2, 43, 83, 143, 227, 243] {
        let f = Fixture::new(&fixture(1)[..len]);
        assert!(Reader::open(&f.0).is_err());
    }
    let mut b = fixture(1);
    put32(&mut b, 20, u32::MAX);
    let f = Fixture::new(&b);
    assert!(Reader::open(&f.0).is_err());
    let mut b = fixture(1);
    put32(&mut b, 244, u32::MAX);
    let f = Fixture::new(&b);
    let mut r = Reader::open(&f.0).unwrap();
    assert!(r.read_frame(0).is_err());
    let mut b = fixture(1);
    b[228..236].copy_from_slice(&44u64.to_le_bytes());
    let f = Fixture::new(&b);
    let mut r = Reader::open(&f.0).unwrap();
    assert!(r.read_frame(0).is_err());
}
#[test]
fn invalid_payloads_and_small_buffers_are_errors() {
    assert!(decode(&[0; 3], 2, 1, 16, 0, 0, &mut [0; 4]).is_err());
    assert!(decode(&[0; 5], 4, 1, 16, 256, 0, &mut [0; 2]).is_err());
    assert!(decode(&[0; 5], 0, 1, 16, 256, 0, &mut [0; 8]).is_err());
    assert!(decode(&[0; 5], 4, 1, 16, 999, 0, &mut [0; 8]).is_err());
    assert!(decode(&[], u32::MAX, i32::MAX, 48, 0, 0, &mut []).is_err());
}
#[test]
fn trimming_preserves_original_acquisition_numbers_and_slices_time_tags() {
    let mut b = fixture(1);
    let mut tag = Vec::new();
    tag.extend_from_slice(&24u32.to_le_bytes());
    tag.extend_from_slice(&1002u16.to_le_bytes());
    tag.extend_from_slice(&0u16.to_le_bytes());
    tag.extend_from_slice(&11u64.to_le_bytes());
    tag.extend_from_slice(&22u64.to_le_bytes());
    b.splice(228..228, tag);
    put32(&mut b, 32, 252);
    b[252..260].copy_from_slice(&268u64.to_le_bytes());
    b[260..268].copy_from_slice(&284u64.to_le_bytes());
    let f = Fixture::new(&b);
    let dest = Fixture::new(&[]);
    fs::remove_file(&dest.0).unwrap();
    let mut r = Reader::open(&f.0).unwrap();
    r.trim(&dest.0, 1, 1).unwrap();
    let mut t = Reader::open(&dest.0).unwrap();
    assert_eq!(t.info.first_frame, -4);
    assert_eq!(t.info.frame_count, 1);
    assert_eq!(t.read_frame(0).unwrap(), [4, 5, 6, 2, 2, 3]);
    let data = fs::read(&dest.0).unwrap();
    assert_eq!(u32::from_le_bytes(data[12..16].try_into().unwrap()), 2);
    assert_eq!(u32::from_le_bytes(data[228..232].try_into().unwrap()), 16);
    assert_eq!(u64::from_le_bytes(data[236..244].try_into().unwrap()), 22);
    assert!(r.trim(&f.0, 0, 1).is_err());
    assert_eq!(fs::read(&f.0).unwrap(), b);
}
#[test]
fn corpus_first_middle_last_when_configured() {
    let Some(dir) = std::env::var_os("CINE_TEST_CORPUS") else {
        return;
    };
    let mut tested = 0;
    for item in fs::read_dir(dir).unwrap() {
        let p = item.unwrap().path();
        if p.extension().and_then(|s| s.to_str()) != Some("cine") {
            continue;
        }
        let mut r = Reader::open(&p).unwrap();
        let mut out = vec![0; r.info.decoded_bytes as usize];
        for i in [0, r.info.frame_count / 2, r.info.frame_count - 1] {
            r.read_frame_into(i, 3, &mut out).unwrap();
        }
        tested += 1;
    }
    assert!(tested > 0, "CINE_TEST_CORPUS contains no CINE files");
}
