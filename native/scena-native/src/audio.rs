use pyo3::exceptions::{PyIOError, PyInterruptedError, PyValueError};
use pyo3::prelude::*;
use std::fs::{self, File};
use std::io::{self, BufReader, BufWriter, Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};

const TRUE_PEAK_LIMIT: f32 = 0.891_250_9;
const PRE_ROLL_SECONDS: f32 = 0.05;
const EXIT_RAMP_SECONDS: f32 = 0.01;
const LIMITER_LOOKAHEAD_SECONDS: f32 = 0.005;
const LIMITER_RELEASE_SECONDS: f32 = 0.06;
const MINIMUM_PREVIOUS_GAIN: f32 = 0.707_945_76;

pub(crate) struct Audio {
    pub(crate) samples: Vec<f32>,
    pub(crate) rate: u32,
    pub(crate) channels: usize,
}

fn read_u16(bytes: &[u8]) -> u16 {
    u16::from_le_bytes([bytes[0], bytes[1]])
}

fn read_u32(bytes: &[u8]) -> u32 {
    u32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]])
}

fn invalid(message: &str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message)
}

pub(crate) fn decode_pcm(path: &Path) -> io::Result<Audio> {
    let mut reader = BufReader::new(File::open(path)?);
    let mut header = [0_u8; 12];
    reader.read_exact(&mut header)?;
    if &header[..4] != b"RIFF" || &header[8..] != b"WAVE" {
        return Err(invalid("Only RIFF PCM WAV files are supported."));
    }
    let mut format = None;
    loop {
        let mut chunk = [0_u8; 8];
        reader.read_exact(&mut chunk)?;
        let size = read_u32(&chunk[4..]) as u64;
        let start = reader.stream_position()?;
        if &chunk[..4] == b"fmt " {
            if size < 16 {
                return Err(invalid("Invalid WAV fmt chunk."));
            }
            let mut raw = [0_u8; 16];
            reader.read_exact(&mut raw)?;
            if read_u16(&raw[..]) != 1 {
                return Err(invalid("Compressed WAV is not supported."));
            }
            format = Some((
                read_u16(&raw[2..]) as usize,
                read_u32(&raw[4..]),
                read_u16(&raw[14..]),
            ));
        } else if &chunk[..4] == b"data" {
            let (channels, rate, bits) =
                format.ok_or_else(|| invalid("WAV fmt chunk is missing."))?;
            let mut raw = vec![0_u8; size as usize];
            reader.read_exact(&mut raw)?;
            let samples = decode_samples(&raw, bits)?;
            if channels == 0 || samples.len() % channels != 0 {
                return Err(invalid("WAV channel data is invalid."));
            }
            return Ok(Audio {
                samples,
                rate,
                channels,
            });
        }
        reader.seek(SeekFrom::Start(start + size + size % 2))?;
    }
}

pub(crate) fn decode_samples(raw: &[u8], bits: u16) -> io::Result<Vec<f32>> {
    match bits {
        8 => Ok(raw
            .iter()
            .map(|value| (*value as f32 - 128.0) / 128.0)
            .collect()),
        16 => Ok(raw
            .chunks_exact(2)
            .map(|value| i16::from_le_bytes([value[0], value[1]]) as f32 / 32768.0)
            .collect()),
        24 => Ok(raw
            .chunks_exact(3)
            .map(|value| {
                let packed = value[0] as i32 | (value[1] as i32) << 8 | (value[2] as i32) << 16;
                ((packed ^ 0x800000) - 0x800000) as f32 / 8_388_608.0
            })
            .collect()),
        32 => Ok(raw
            .chunks_exact(4)
            .map(|value| {
                i32::from_le_bytes([value[0], value[1], value[2], value[3]]) as f32
                    / 2_147_483_648.0
            })
            .collect()),
        _ => Err(invalid("Unsupported PCM sample width.")),
    }
}

pub(crate) fn true_peak(samples: &[f32], channels: usize) -> f32 {
    let frames = samples.len() / channels;
    if frames == 0 {
        return 0.0;
    }
    let mut peak = samples
        .iter()
        .fold(0.0_f32, |value, sample| value.max(sample.abs()));
    for frame in 0..frames.saturating_sub(1) {
        for channel in 0..channels {
            let first = samples[frame * channels + channel];
            let second = samples[(frame + 1) * channels + channel];
            for quarter in 1..4 {
                peak = peak.max((first + (second - first) * quarter as f32 / 4.0).abs());
            }
        }
    }
    peak
}

pub(crate) fn write_pcm16(
    path: &Path,
    samples: &[f32],
    rate: u32,
    channels: usize,
) -> io::Result<()> {
    let temporary = path.with_extension("tmp.wav");
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let result = (|| -> io::Result<()> {
        let data_size =
            u32::try_from(samples.len() * 2).map_err(|_| invalid("WAV data is too large."))?;
        let mut writer = BufWriter::new(File::create(&temporary)?);
        writer.write_all(b"RIFF")?;
        writer.write_all(&(36 + data_size).to_le_bytes())?;
        writer.write_all(b"WAVEfmt ")?;
        writer.write_all(&16_u32.to_le_bytes())?;
        writer.write_all(&1_u16.to_le_bytes())?;
        writer.write_all(&(channels as u16).to_le_bytes())?;
        writer.write_all(&rate.to_le_bytes())?;
        writer.write_all(&(rate * channels as u32 * 2).to_le_bytes())?;
        writer.write_all(&(channels as u16 * 2).to_le_bytes())?;
        writer.write_all(&16_u16.to_le_bytes())?;
        writer.write_all(b"data")?;
        writer.write_all(&data_size.to_le_bytes())?;
        for sample in samples {
            let pcm = (sample.clamp(-1.0, 32767.0 / 32768.0) * 32768.0).round() as i16;
            writer.write_all(&pcm.to_le_bytes())?;
        }
        writer.flush()?;
        fs::rename(&temporary, path)
    })();
    if result.is_err() {
        let _ = fs::remove_file(temporary);
    }
    result
}

#[pyfunction]
pub fn overlap_following_gain(path: PathBuf, seconds: f64) -> PyResult<f32> {
    let audio = decode_pcm(&path).map_err(|error| PyIOError::new_err(error.to_string()))?;
    let requested = (seconds.max(0.0) * audio.rate as f64).round() as usize;
    let frames = requested.min(audio.samples.len() / audio.channels);
    if frames == 0 {
        return Err(PyValueError::new_err(
            "Overlap duration must contain at least one sample.",
        ));
    }
    let samples = &audio.samples[..frames * audio.channels];
    Ok((TRUE_PEAK_LIMIT / true_peak(samples, audio.channels).max(1e-12)).min(1.0))
}

#[pyfunction]
#[pyo3(signature = (previous_path, following_path, seconds, output, should_cancel=None))]
pub fn render_overlap_wav(
    py: Python<'_>,
    previous_path: PathBuf,
    following_path: PathBuf,
    seconds: f64,
    output: PathBuf,
    should_cancel: Option<Py<PyAny>>,
) -> PyResult<(f64, f64, f64, f32, f32)> {
    py.allow_threads(move || {
        render_overlap_wav_without_gil(
            previous_path,
            following_path,
            seconds,
            output,
            should_cancel,
        )
    })
}

fn check_cancelled(should_cancel: &Option<Py<PyAny>>) -> PyResult<()> {
    let cancelled = match should_cancel {
        Some(callback) => Python::with_gil(|py| callback.call0(py)?.is_truthy(py)),
        None => Ok(false),
    }?;
    if cancelled {
        Err(PyInterruptedError::new_err(
            "Overlap preparation was interrupted.",
        ))
    } else {
        Ok(())
    }
}

fn render_overlap_wav_without_gil(
    previous_path: PathBuf,
    following_path: PathBuf,
    seconds: f64,
    output: PathBuf,
    should_cancel: Option<Py<PyAny>>,
) -> PyResult<(f64, f64, f64, f32, f32)> {
    check_cancelled(&should_cancel)?;
    let previous =
        decode_pcm(&previous_path).map_err(|error| PyIOError::new_err(error.to_string()))?;
    check_cancelled(&should_cancel)?;
    let following =
        decode_pcm(&following_path).map_err(|error| PyIOError::new_err(error.to_string()))?;
    check_cancelled(&should_cancel)?;
    if previous.rate != following.rate || previous.channels != following.channels {
        return Err(PyValueError::new_err(
            "Overlapping units must use the same sample rate and channel count.",
        ));
    }
    let requested = (seconds.max(0.0) * previous.rate as f64).round() as usize;
    let previous_frames = previous.samples.len() / previous.channels;
    let following_frames = following.samples.len() / following.channels;
    let frames = requested.min(previous_frames).min(following_frames);
    if frames == 0 {
        return Err(PyValueError::new_err(
            "Overlap duration must contain at least one sample.",
        ));
    }
    let pre_roll_frames = previous_frames
        .saturating_sub(frames)
        .min((previous.rate as f32 * PRE_ROLL_SECONDS).round() as usize);
    let post_roll_frames = following_frames
        .saturating_sub(frames)
        .min((previous.rate as f32 * LIMITER_RELEASE_SECONDS).round() as usize);
    let previous_gain = MINIMUM_PREVIOUS_GAIN;
    let mut mixed = Vec::with_capacity(frames * previous.channels);
    let exit_frames = ((previous.rate as f32 * EXIT_RAMP_SECONDS).round() as usize).min(frames);
    for frame in 0..frames {
        if frame % 4096 == 0 {
            check_cancelled(&should_cancel)?;
        }
        let exit = frames.saturating_sub(frame + 1);
        let ramp = if exit < exit_frames {
            exit as f32 / exit_frames.saturating_sub(1).max(1) as f32
        } else {
            1.0
        };
        for channel in 0..previous.channels {
            let before =
                previous.samples[(previous_frames - frames + frame) * previous.channels + channel];
            let after = following.samples[frame * following.channels + channel];
            mixed.push(after + before * previous_gain * ramp);
        }
    }
    let mut rendered =
        Vec::with_capacity((pre_roll_frames + frames + post_roll_frames) * previous.channels);
    for frame in 0..pre_roll_frames {
        if frame % 4096 == 0 {
            check_cancelled(&should_cancel)?;
        }
        let position = if pre_roll_frames <= 1 {
            1.0
        } else {
            frame as f32 / (pre_roll_frames - 1) as f32
        };
        let gain = 1.0 + (previous_gain - 1.0) * position;
        let source_frame = previous_frames - frames - pre_roll_frames + frame;
        for channel in 0..previous.channels {
            rendered.push(previous.samples[source_frame * previous.channels + channel] * gain);
        }
    }
    rendered.extend(mixed);
    rendered.extend_from_slice(
        &following.samples
            [frames * following.channels..(frames + post_roll_frames) * following.channels],
    );
    let following_gain = apply_lookahead_limiter(
        &mut rendered,
        previous.rate,
        previous.channels,
        &should_cancel,
    )?;
    check_cancelled(&should_cancel)?;
    write_pcm16(&output, &rendered, previous.rate, previous.channels)
        .map_err(|error| PyIOError::new_err(error.to_string()))?;
    Ok((
        frames as f64 / previous.rate as f64,
        pre_roll_frames as f64 / previous.rate as f64,
        post_roll_frames as f64 / previous.rate as f64,
        previous_gain,
        following_gain,
    ))
}

fn frame_true_peak(samples: &[f32], frame: usize, channels: usize) -> f32 {
    let frames = samples.len() / channels;
    let mut peak = 0.0_f32;
    for channel in 0..channels {
        let first = samples[frame * channels + channel];
        peak = peak.max(first.abs());
        if frame + 1 < frames {
            let second = samples[(frame + 1) * channels + channel];
            for quarter in 1..4 {
                peak = peak.max((first + (second - first) * quarter as f32 / 4.0).abs());
            }
        }
    }
    peak
}

fn apply_lookahead_limiter(
    samples: &mut [f32],
    rate: u32,
    channels: usize,
    should_cancel: &Option<Py<PyAny>>,
) -> PyResult<f32> {
    let frames = samples.len() / channels;
    let lookahead = ((rate as f32 * LIMITER_LOOKAHEAD_SECONDS).round() as usize).max(1);
    let release = (-4.605_170_2 / (rate as f32 * LIMITER_RELEASE_SECONDS)).exp();
    let peaks: Vec<f32> = (0..frames)
        .map(|frame| frame_true_peak(samples, frame, channels))
        .collect();
    let mut desired = vec![1.0_f32; frames];
    for (frame, peak) in peaks.iter().enumerate() {
        desired[frame] = (TRUE_PEAK_LIMIT / peak.max(1e-12)).min(1.0);
    }
    let attack_step = (1.0 - TRUE_PEAK_LIMIT / 2.0) / lookahead as f32;
    for frame in (0..frames.saturating_sub(1)).rev() {
        if frame % 4096 == 0 {
            check_cancelled(should_cancel)?;
        }
        desired[frame] = desired[frame].min(desired[frame + 1] + attack_step);
    }
    let mut gain = 1.0_f32;
    for frame in 0..frames {
        if frame % 4096 == 0 {
            check_cancelled(should_cancel)?;
        }
        gain = if desired[frame] < gain {
            desired[frame]
        } else {
            desired[frame] + (gain - desired[frame]) * release
        };
        for channel in 0..channels {
            samples[frame * channels + channel] *= gain;
        }
    }
    let peak = true_peak(samples, channels);
    let correction = if peak > TRUE_PEAK_LIMIT {
        let correction = TRUE_PEAK_LIMIT / peak;
        samples.iter_mut().for_each(|sample| *sample *= correction);
        correction
    } else {
        1.0
    };
    Ok(gain * correction)
}
