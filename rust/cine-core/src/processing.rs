//! CPU-only image processing and Rust-owned streaming accumulators.
use crate::{Error, Result};

pub trait Sample: Copy {
    const INTEGER: bool;
    fn to_f64(self) -> f64;
    fn from_f64(value: f64) -> Self;
}

macro_rules! sample {
    ($($t:ty),+) => {$ (
        impl Sample for $t {
            const INTEGER: bool = <$t>::MIN >= 0 as $t;
            fn to_f64(self) -> f64 { self as f64 }
            fn from_f64(value: f64) -> Self { value as Self }
        }
    )+};
}
sample!(u8, u16, f32, f64);

/// Repair (1), same-phase Bayer repair (2), or bilinear demosaic (3).
/// Demosaic patterns are RGGB/BGGR/GRBG/GBRG at param 0/1/2/3.
/// Param bit 256 selects MATLAB's ties-away rounding instead of ties-even.
pub fn process<T: Sample>(
    source: &[T],
    output: &mut [T],
    width: usize,
    height: usize,
    channels: usize,
    op: u32,
    param: u32,
    value: f64,
) -> Result<()> {
    let pixels = width
        .checked_mul(height)
        .ok_or_else(|| Error::format("image dimensions overflow"))?;
    let samples = pixels
        .checked_mul(channels)
        .ok_or_else(|| Error::format("image dimensions overflow"))?;
    if width == 0 || height == 0 || channels == 0 || source.len() != samples {
        return Err(Error::format(
            "invalid image dimensions or input buffer size",
        ));
    }
    if op == 3 {
        let required = pixels
            .checked_mul(3)
            .ok_or_else(|| Error::format("image dimensions overflow"))?;
        if channels != 1 || output.len() != required || param & !0x103 != 0 {
            return Err(Error::format(
                "demosaic requires one channel, a valid pattern, and three-channel output",
            ));
        }
        // R, G with red horizontal, G with blue horizontal, B.
        let patterns = [[0u8, 1, 2, 3], [3, 2, 1, 0], [1, 0, 3, 2], [2, 3, 0, 1]];
        let pattern = patterns[(param & 3) as usize];
        for y in 0..height {
            let up = y.saturating_sub(1);
            let down = (y + 1).min(height - 1);
            for x in 0..width {
                let left = x.saturating_sub(1);
                let right = (x + 1).min(width - 1);
                let get = |row: usize, col: usize| source[row * width + col].to_f64() as f32;
                let center = get(y, x);
                let cross = (get(up, x) + get(down, x) + get(y, left) + get(y, right)) * 0.25;
                let diagonal =
                    (get(up, left) + get(up, right) + get(down, left) + get(down, right)) * 0.25;
                let horizontal = (get(y, left) + get(y, right)) * 0.5;
                let vertical = (get(up, x) + get(down, x)) * 0.5;
                let rgb = match pattern[(y & 1) * 2 + (x & 1)] {
                    0 => [center, cross, diagonal],
                    1 => [horizontal, center, vertical],
                    2 => [vertical, center, horizontal],
                    _ => [diagonal, cross, center],
                };
                for (channel, sample) in rgb.into_iter().enumerate() {
                    let rounded = if param & 256 != 0 {
                        sample.round()
                    } else {
                        sample.round_ties_even()
                    };
                    output[(y * width + x) * 3 + channel] = T::from_f64(f64::from(rounded));
                }
            }
        }
        return Ok(());
    }
    if (op != 1 && op != 2)
        || output.len() != samples
        || param & !257 != 0
        || (op == 2 && channels != 1)
    {
        return Err(Error::format(
            "invalid repair operation, parameters, or output size",
        ));
    }
    output.copy_from_slice(source);
    let bad = |sample: T| {
        if param & 1 == 0 {
            sample.to_f64() == value
        } else {
            sample.to_f64() >= value
        }
    };
    let step = if op == 2 { 2isize } else { 1 };
    for y in 0..height {
        for x in 0..width {
            for channel in 0..channels {
                let index = (y * width + x) * channels + channel;
                if !bad(source[index]) {
                    continue;
                }
                let mut sum = 0f32;
                let mut count = 0u32;
                for dy in [-step, 0, step] {
                    for dx in [-step, 0, step] {
                        if dy == 0 && dx == 0 {
                            continue;
                        }
                        let row = y as isize + dy;
                        let col = x as isize + dx;
                        if row < 0 || row >= height as isize || col < 0 || col >= width as isize {
                            continue;
                        }
                        let neighbor =
                            source[(row as usize * width + col as usize) * channels + channel];
                        if !bad(neighbor) {
                            sum += neighbor.to_f64() as f32;
                            count += 1;
                        }
                    }
                }
                if count != 0 {
                    let mean = sum / count as f32;
                    output[index] = T::from_f64(f64::from(if param & 256 != 0 && T::INTEGER {
                        mean.round()
                    } else {
                        mean
                    }));
                }
            }
        }
    }
    Ok(())
}

enum Storage {
    Mean(Vec<f64>),
    // A contiguous minimum heap per pixel, bounded by k frames regardless of count.
    TopK { heap: Vec<f32>, k: usize },
    Mad(Vec<Vec<f32>>),
}

/// Rust-owned frame statistics. Modes: 0 mean, 1 top-k, 2 quantile/MAD.
pub struct Stats {
    samples: usize,
    count: u64,
    q: f64,
    sigma: f64,
    min_keep: u32,
    storage: Storage,
    matlab: bool,
}

impl Stats {
    pub fn new(
        samples: usize,
        mode: u32,
        k: u32,
        q: f64,
        sigma: f64,
        min_keep: u32,
    ) -> Result<Self> {
        let matlab = mode & 256 != 0;
        let mode = mode & !256;
        if samples == 0 {
            return Err(Error::format(
                "statistics require at least one sample per frame",
            ));
        }
        if mode != 0
            && (!q.is_finite()
                || if matlab {
                    !(0.0..=1.0).contains(&q)
                } else {
                    q <= 0.0 || q >= 1.0
                })
        {
            return Err(Error::format("q_bg must be between zero and one"));
        }
        if mode == 2 && (!sigma.is_finite() || sigma < 0.0 || min_keep == 0) {
            return Err(Error::format(
                "k_sigma must be finite and nonnegative and min_keep must be positive",
            ));
        }
        let storage = match mode {
            0 => Storage::Mean(zeros(samples)?),
            1 if k != 0 => {
                let length = samples
                    .checked_mul(k as usize)
                    .ok_or_else(|| Error::format("top-k buffer size overflow"))?;
                Storage::TopK {
                    heap: zeros(length)?,
                    k: k as usize,
                }
            }
            2 => Storage::Mad(Vec::new()),
            _ => return Err(Error::format("invalid statistics mode or top-k count")),
        };
        Ok(Self {
            samples,
            count: 0,
            q,
            sigma,
            min_keep,
            storage,
            matlab,
        })
    }

    /// Copy one frame into the accumulator. The input may be reused immediately.
    pub fn push(&mut self, values: &[f64]) -> Result<()> {
        if values.len() != self.samples {
            return Err(Error::format("all frames must have the same sample count"));
        }
        let next_count = self
            .count
            .checked_add(1)
            .ok_or_else(|| Error::format("frame count overflow"))?;
        match &mut self.storage {
            Storage::Mean(sum) => {
                for (accumulator, &value) in sum.iter_mut().zip(values) {
                    *accumulator += value;
                }
            }
            Storage::TopK { heap, k } => {
                for (pixel, &value) in values.iter().enumerate() {
                    let value = value as f32;
                    let h = &mut heap[pixel * *k..(pixel + 1) * *k];
                    if self.count < *k as u64 {
                        let mut child = self.count as usize;
                        h[child] = value;
                        while child > 0 {
                            let parent = (child - 1) / 2;
                            if h[parent] <= h[child] {
                                break;
                            }
                            h.swap(child, parent);
                            child = parent;
                        }
                    } else if value > h[0] {
                        h[0] = value;
                        let mut parent = 0;
                        while parent * 2 + 1 < *k {
                            let mut child = parent * 2 + 1;
                            if child + 1 < *k && h[child + 1] < h[child] {
                                child += 1;
                            }
                            if h[parent] <= h[child] {
                                break;
                            }
                            h.swap(parent, child);
                            parent = child;
                        }
                    }
                }
            }
            Storage::Mad(frames) => {
                let mut frame = Vec::new();
                frame
                    .try_reserve_exact(values.len())
                    .map_err(|_| Error::format("cannot allocate MAD frame"))?;
                frame.extend(values.iter().map(|&value| value as f32));
                frames
                    .try_reserve(1)
                    .map_err(|_| Error::format("cannot extend MAD stack"))?;
                frames.push(frame);
            }
        }
        self.count = next_count;
        Ok(())
    }

    pub fn finish(&self, output: &mut [f64]) -> Result<u64> {
        if output.len() != self.samples {
            return Err(Error::format(
                "statistics output has the wrong sample count",
            ));
        }
        if self.count == 0 {
            return Err(Error::format("no frames were provided"));
        }
        match &self.storage {
            Storage::Mean(sum) => {
                for (out, &total) in output.iter_mut().zip(sum) {
                    *out = round(total / self.count as f64, self.matlab);
                }
            }
            Storage::TopK { heap, k } => {
                let used = self.count.min(*k as u64) as usize;
                for (pixel, out) in output.iter_mut().enumerate() {
                    let total: f32 = heap[pixel * *k..pixel * *k + used].iter().sum();
                    *out = round(f64::from(total / used as f32), self.matlab).clamp(0.0, 65535.0);
                }
            }
            Storage::Mad(frames) => {
                let mut values: Vec<f32> = zeros(frames.len())?;
                let mut deviations: Vec<f32> = zeros(frames.len())?;
                for (pixel, out) in output.iter_mut().enumerate() {
                    for (value, frame) in values.iter_mut().zip(frames) {
                        *value = frame[pixel];
                    }
                    if values.iter().any(|value| value.is_nan()) {
                        *out = f64::NAN;
                        continue;
                    }
                    values.sort_unstable_by(f32::total_cmp);
                    let position = if self.matlab {
                        (values.len() as f64 * self.q - 0.5).clamp(0.0, (values.len() - 1) as f64)
                    } else {
                        (values.len() - 1) as f64 * self.q
                    };
                    let lower = position.floor() as usize;
                    let upper = position.ceil() as usize;
                    let background = f64::from(values[lower])
                        + f64::from(values[upper] - values[lower]) * (position - lower as f64);
                    let midpoint = median(&values);
                    for (deviation, value) in deviations.iter_mut().zip(&values) {
                        *deviation = (*value - midpoint).abs();
                    }
                    deviations.sort_unstable_by(f32::total_cmp);
                    let sigma = (1.4826f32 * median(&deviations)).max(1e-6f32);
                    let threshold = background - self.sigma * f64::from(sigma);
                    let mut total = 0f32;
                    let mut count = 0u64;
                    for frame in frames {
                        let sample = frame[pixel];
                        if f64::from(sample) >= threshold {
                            total += sample;
                            count += 1;
                        }
                    }
                    let value = if count >= u64::from(self.min_keep) {
                        f64::from(total) / count as f64
                    } else {
                        background
                    };
                    *out = round(value, self.matlab).clamp(0.0, 65535.0);
                }
            }
        }
        Ok(self.count)
    }
}

fn round(value: f64, matlab: bool) -> f64 {
    if matlab {
        value.round()
    } else {
        value.round_ties_even()
    }
}

fn median(values: &[f32]) -> f32 {
    let middle = values.len() / 2;
    if values.len() % 2 == 0 {
        (values[middle - 1] + values[middle]) * 0.5
    } else {
        values[middle]
    }
}

fn zeros<T: Copy + Default>(length: usize) -> Result<Vec<T>> {
    let mut values = Vec::new();
    values
        .try_reserve_exact(length)
        .map_err(|_| Error::format("cannot allocate statistics buffer"))?;
    values.resize(length, T::default());
    Ok(values)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn repairs_do_not_propagate_into_neighboring_dead_pixels() {
        let input = [2u16, 4095, 4095, 8];
        let mut output = [0; 4];
        process(&input, &mut output, 4, 1, 1, 1, 0, 4095.0).unwrap();
        assert_eq!(output, [2, 2, 8, 8]);
    }

    #[test]
    fn bayer_repair_only_uses_same_phase() {
        let mut input = [100u16; 25];
        for y in (0..5).step_by(2) {
            for x in (0..5).step_by(2) {
                input[y * 5 + x] = 12;
            }
        }
        input[12] = 4095;
        let mut output = [0; 25];
        process(&input, &mut output, 5, 5, 1, 2, 0, 4095.0).unwrap();
        assert_eq!(output[12], 12);
    }

    #[test]
    fn demosaic_handles_single_pixel_and_rounding_modes() {
        let mut output = [0u16; 3];
        process(&[7], &mut output, 1, 1, 1, 3, 0, 0.0).unwrap();
        assert_eq!(output, [7, 7, 7]);
        let input = [0u16, 1];
        let mut even = [0u16; 6];
        let mut away = [0u16; 6];
        process(&input, &mut even, 2, 1, 1, 3, 0, 0.0).unwrap();
        process(&input, &mut away, 2, 1, 1, 3, 256, 0.0).unwrap();
        assert_eq!(even[2], 0);
        assert_eq!(away[2], 1);
    }

    #[test]
    fn mean_owns_inputs_and_rounds_ties_even() {
        let mut stats = Stats::new(2, 0, 0, 0.8, 2.5, 3).unwrap();
        let mut values = [2.0, 3.0];
        stats.push(&values).unwrap();
        values = [3.0, 4.0];
        stats.push(&values).unwrap();
        let mut output = [0.0; 2];
        assert_eq!(stats.finish(&mut output).unwrap(), 2);
        assert_eq!(output, [2.0, 4.0]);
    }

    #[test]
    fn top_k_replaces_minima_per_pixel() {
        let mut stats = Stats::new(2, 1, 2, 0.8, 2.5, 3).unwrap();
        for values in [[1.0, 9.0], [8.0, 2.0], [3.0, 7.0], [6.0, 4.0]] {
            stats.push(&values).unwrap();
        }
        let mut output = [0.0; 2];
        stats.finish(&mut output).unwrap();
        assert_eq!(output, [7.0, 8.0]);
    }

    #[test]
    fn mad_rejects_dark_outlier() {
        let mut stats = Stats::new(1, 2, 0, 0.8, 2.5, 3).unwrap();
        for value in [1.0, 100.0, 100.0, 100.0] {
            stats.push(&[value]).unwrap();
        }
        let mut output = [0.0];
        stats.finish(&mut output).unwrap();
        assert_eq!(output, [100.0]);
    }

    #[test]
    fn matlab_uses_its_historical_quantile_and_rounding_conventions() {
        let mut python = Stats::new(1, 2, 0, 0.8, 0.0, 3).unwrap();
        let mut matlab = Stats::new(1, 258, 0, 0.8, 0.0, 3).unwrap();
        for value in [0.0, 10.0] {
            python.push(&[value]).unwrap();
            matlab.push(&[value]).unwrap();
        }
        let mut output = [0.0];
        python.finish(&mut output).unwrap();
        assert_eq!(output, [8.0]);
        matlab.finish(&mut output).unwrap();
        assert_eq!(output, [10.0]);
        let mut mean = Stats::new(1, 256, 0, 0.8, 0.0, 3).unwrap();
        mean.push(&[2.0]).unwrap();
        mean.push(&[3.0]).unwrap();
        mean.finish(&mut output).unwrap();
        assert_eq!(output, [3.0]);
        assert!(Stats::new(1, 258, 0, 1.0, 0.0, 3).is_ok());
    }

    #[test]
    fn matlab_repair_rounds_integers_but_preserves_fractional_float_samples() {
        let mut integers = [0u16; 3];
        process(&[2, 99, 3], &mut integers, 3, 1, 1, 1, 256, 99.0).unwrap();
        assert_eq!(integers, [2, 3, 3]);
        let mut floats = [0.0f32; 3];
        process(&[2.0, 99.0, 3.0], &mut floats, 3, 1, 1, 1, 256, 99.0).unwrap();
        assert_eq!(floats, [2.0, 2.5, 3.0]);
    }
}
