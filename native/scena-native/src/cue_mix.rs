use crate::audio::{decode_pcm, true_peak, write_pcm16};
use pyo3::exceptions::{PyIOError, PyValueError};
use pyo3::prelude::*;
use std::path::PathBuf;

const TRUE_PEAK_LIMIT: f32 = 0.891_250_9;
const LEVEL_RATE: usize = 48_000;

fn integrated_level(samples: &[f32], channels: usize) -> Option<f32> {
    let frames = samples.len() / channels;
    if frames == 0 {
        return None;
    }
    let block = (0.4 * LEVEL_RATE as f32).round() as usize;
    let mut audible = Vec::new();
    for start in (0..frames).step_by(block.max(1)) {
        let end = (start + block).min(frames);
        let mut power = 0.0_f32;
        for frame in start..end {
            let mut mono = 0.0_f32;
            for channel in 0..channels {
                mono += samples[frame * channels + channel];
            }
            mono /= channels as f32;
            power += mono * mono;
        }
        power /= (end - start) as f32;
        if power > 10_f32.powf(-7.0) {
            audible.push(power);
        }
    }
    if audible.is_empty() {
        return None;
    }
    let ungated = audible.iter().sum::<f32>() / audible.len() as f32;
    let gated: Vec<f32> = audible
        .iter()
        .copied()
        .filter(|power| *power >= ungated / 10.0)
        .collect();
    let selected = if gated.is_empty() { &audible } else { &gated };
    Some((selected.iter().sum::<f32>() / selected.len() as f32).sqrt())
}

#[pyfunction]
pub fn mix_pcm_members_wav(
    py: Python<'_>,
    members: Vec<(PathBuf, f64)>,
    output: PathBuf,
) -> PyResult<f64> {
    py.allow_threads(move || mix_pcm_members_wav_without_gil(members, output))
}

fn mix_pcm_members_wav_without_gil(members: Vec<(PathBuf, f64)>, output: PathBuf) -> PyResult<f64> {
    if members.is_empty() {
        return Err(PyValueError::new_err(
            "Cue must contain at least one member.",
        ));
    }
    let decoded = members
        .into_iter()
        .map(|(path, offset)| {
            decode_pcm(&path)
                .map(|audio| (audio, offset.max(0.0)))
                .map_err(|error| PyIOError::new_err(error.to_string()))
        })
        .collect::<PyResult<Vec<_>>>()?;
    let rate = decoded[0].0.rate;
    let channels = decoded[0].0.channels;
    if decoded
        .iter()
        .any(|(audio, _)| audio.rate != rate || audio.channels != channels)
    {
        return Err(PyValueError::new_err(
            "Cue members must use the same sample rate and channel count.",
        ));
    }
    let total_frames = decoded
        .iter()
        .map(|(audio, offset)| {
            (offset * rate as f64).round() as usize + audio.samples.len() / channels
        })
        .max()
        .unwrap_or(0);
    let mut mixed = vec![0.0_f32; total_frames * channels];
    let mut reference = 0.0_f32;
    for (audio, offset) in &decoded {
        let start = (offset * rate as f64).round() as usize * channels;
        for (target, sample) in mixed[start..start + audio.samples.len()]
            .iter_mut()
            .zip(&audio.samples)
        {
            *target += *sample;
        }
        reference = reference.max(integrated_level(&audio.samples, channels).unwrap_or(0.0));
    }
    if let Some(level) = integrated_level(&mixed, channels) {
        if reference > 0.0 && level > 0.0 {
            let gain = reference / level;
            mixed.iter_mut().for_each(|sample| *sample *= gain);
        }
    }
    let peak = true_peak(&mixed, channels);
    if peak > TRUE_PEAK_LIMIT {
        let gain = TRUE_PEAK_LIMIT / peak;
        mixed.iter_mut().for_each(|sample| *sample *= gain);
    }
    write_pcm16(&output, &mixed, rate, channels)
        .map_err(|error| PyIOError::new_err(error.to_string()))?;
    Ok(total_frames as f64 / rate as f64)
}
