//! Independently renderable intervals: all DSP state has finite support.
use crate::audio::write_pcm16;
use crate::timeline_pcm::window;
use pyo3::exceptions::{PyIOError, PyInterruptedError, PyValueError};
use pyo3::prelude::*;
use std::collections::VecDeque;
use std::path::PathBuf;

// Reserve PCM16 reconstruction/rounding headroom below -1 dBTP.
const LIMIT: f32 = 29202.0 / 32768.0;
const DUCK: f32 = 0.707_945_76;

fn cancelled(callback: &Option<Py<PyAny>>) -> PyResult<()> {
    if callback.is_none() {
        return Ok(());
    }
    Python::with_gil(|py| {
        if let Some(callback) = callback {
            if callback.call0(py)?.extract::<bool>(py)? {
                return Err(PyInterruptedError::new_err("Timeline rendering cancelled"));
            }
        }
        Ok(())
    })
}

fn finite_limiter(samples: &mut [f32], channels: usize, rate: u32) {
    let frames = samples.len() / channels;
    let radius = ((rate as f64 * 0.06).ceil() as usize).max(16);
    let smooth = (rate as f64 * 0.025).ceil() as usize;
    let peaks = crate::timeline_peak::bounds(samples, channels);
    let mut maxima = vec![0.0_f64; frames];
    let mut queue: VecDeque<usize> = VecDeque::new();
    let mut right = 0;
    for (index, maximum) in maxima.iter_mut().enumerate() {
        while right < frames.min(index + radius + 1) {
            while queue
                .back()
                .is_some_and(|&previous| peaks[previous] <= peaks[right])
            {
                queue.pop_back();
            }
            queue.push_back(right);
            right += 1;
        }
        while queue
            .front()
            .is_some_and(|&left| left < index.saturating_sub(radius))
        {
            queue.pop_front();
        }
        *maximum = peaks[*queue.front().unwrap()] as f64;
    }
    let mut prefix = vec![0.0; frames + 1];
    for index in 0..frames {
        prefix[index + 1] = prefix[index] + maxima[index];
    }
    for index in 0..frames {
        let left = index.saturating_sub(smooth);
        let right = frames.min(index + smooth + 1);
        // Every window contributing to this average includes the current sample.
        let peak = ((prefix[right] - prefix[left]) / (right - left) as f64) as f32;
        let gain = (LIMIT / peak.max(LIMIT)).min(1.0);
        for sample in &mut samples[index * channels..(index + 1) * channels] {
            *sample *= gain;
        }
    }
}

#[pyfunction]
#[pyo3(signature = (members, start, end, rate, channels, output, should_cancel=None))]
pub fn render_timeline_wav(
    py: Python<'_>,
    members: Vec<(PathBuf, usize, usize)>,
    start: usize,
    end: usize,
    rate: u32,
    channels: usize,
    output: PathBuf,
    should_cancel: Option<Py<PyAny>>,
) -> PyResult<()> {
    py.allow_threads(move || render(members, start, end, rate, channels, output, &should_cancel))
}

fn render(
    mut members: Vec<(PathBuf, usize, usize)>,
    start: usize,
    end: usize,
    rate: u32,
    channels: usize,
    output: PathBuf,
    callback: &Option<Py<PyAny>>,
) -> PyResult<()> {
    if end <= start || rate == 0 || channels == 0 || end - start > rate as usize * 60 {
        return Err(PyValueError::new_err("Invalid timeline interval"));
    }
    let halo = ((rate as f64 * 0.15).ceil() as usize).max(26);
    let left = start.saturating_sub(halo);
    let right = end
        .checked_add(halo)
        .ok_or_else(|| PyValueError::new_err("Frame overflow"))?;
    let frames = right - left;
    let mut mix = vec![0.0; frames * channels];
    let mut later = vec![0.0_f32; frames];
    let mut upcoming = vec![usize::MAX; frames];
    members.sort_by_key(|member| std::cmp::Reverse(member.1));
    let ramp = (rate as f64 * 0.05).max(1.0) as f32;
    let mut index = 0;
    while index < members.len() {
        cancelled(callback)?;
        let onset = members[index].1;
        let mut group_end = index + 1;
        while group_end < members.len() && members[group_end].1 == onset {
            group_end += 1;
        }
        let mut latest_end = onset;
        for (path, onset, duration) in &members[index..group_end] {
            cancelled(callback)?;
            let stop = onset
                .checked_add(*duration)
                .ok_or_else(|| PyValueError::new_err("Frame overflow"))?;
            latest_end = latest_end.max(stop);
            let from = left.max(*onset);
            let to = right.min(stop);
            if to <= from {
                continue;
            }
            let audio = window(path, from - onset, to - from)
                .map_err(|e| PyIOError::new_err(e.to_string()))?;
            if audio.rate != rate
                || audio.channels != channels
                || audio.samples.len() != (to - from) * channels
            {
                return Err(PyValueError::new_err(
                    "Timeline input changed or has incompatible format",
                ));
            }
            for (frame, values) in audio.samples.chunks(channels).enumerate() {
                let target = from - left + frame;
                let next = upcoming[target];
                let attack = if next < stop {
                    ((from + frame) as f64 - next as f64 + ramp as f64) / ramp as f64
                } else {
                    0.0
                };
                let attenuation = later[target].max(attack.clamp(0.0, 1.0) as f32);
                let gain = 1.0 - (1.0 - DUCK) * attenuation;
                for channel in 0..channels {
                    mix[target * channels + channel] += values[channel] * gain;
                }
            }
        }
        for (frame, attenuation) in later.iter_mut().enumerate() {
            let at = (left + frame) as f64;
            if at < onset as f64 {
                upcoming[frame] = upcoming[frame].min(onset);
            } else {
                let release =
                    ((latest_end as f64 + ramp as f64 - at) / ramp as f64).clamp(0.0, 1.0) as f32;
                *attenuation = attenuation.max(release);
            }
        }
        index = group_end;
    }
    cancelled(callback)?;
    finite_limiter(&mut mix, channels, rate);
    cancelled(callback)?;
    write_pcm16(
        &output,
        &mix[(start - left) * channels..(end - left) * channels],
        rate,
        channels,
    )
    .map_err(|e| PyIOError::new_err(e.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::audio::decode_pcm;
    use crate::timeline_peak::measured_peak;

    #[test]
    fn intervals_match_continuous_for_dense_and_reversed_onsets() {
        let root = std::env::temp_dir().join(format!("scena-timeline-{}", std::process::id()));
        std::fs::create_dir_all(&root).unwrap();
        let rate = 1000;
        let source = root.join("source.wav");
        let pcm: Vec<f32> = (0..3000)
            .map(|frame| ((frame as f32 * 0.137).sin()) * 0.6)
            .collect();
        write_pcm16(&source, &pcm, rate, 1).unwrap();
        for count in [2, 3, 10, 243] {
            let members: Vec<_> = (0..count)
                .map(|index| (source.clone(), (index * 73) % 500, 3000))
                .collect();
            let full = root.join("full.wav");
            render(members.clone(), 0, 3500, rate, 1, full.clone(), &None).unwrap();
            let reference = decode_pcm(&full).unwrap();
            let mut joined = Vec::new();
            for (start, end) in [(0, 1000), (1000, 2000), (2000, 3000), (3000, 3500)] {
                let part = root.join("part.wav");
                render(members.clone(), start, end, rate, 1, part.clone(), &None).unwrap();
                joined.extend(decode_pcm(&part).unwrap().samples);
            }
            assert_eq!(joined, reference.samples, "{count} voices");
            assert!(measured_peak(&joined, 1) <= 0.891_250_9);
        }
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn only_actually_overlapping_earlier_voices_are_ducked() {
        let root = std::env::temp_dir().join(format!("scena-timeline-gain-{}", std::process::id()));
        std::fs::create_dir_all(&root).unwrap();
        let source = root.join("source.wav");
        write_pcm16(&source, &vec![0.1; 1000], 1000, 1).unwrap();
        let amplitude = decode_pcm(&source).unwrap().samples[0];
        let output = root.join("mix.wav");
        render(
            vec![(source.clone(), 0, 1000), (source.clone(), 1000, 1000)],
            0,
            2000,
            1000,
            1,
            output.clone(),
            &None,
        )
        .unwrap();
        assert!(decode_pcm(&output)
            .unwrap()
            .samples
            .iter()
            .all(|&sample| sample == amplitude));
        render(
            vec![
                (source.clone(), 0, 1000),
                (source.clone(), 200, 1000),
                (source.clone(), 200, 1000),
            ],
            0,
            1200,
            1000,
            1,
            output.clone(),
            &None,
        )
        .unwrap();
        let rendered = decode_pcm(&output).unwrap();
        assert!((rendered.samples[400] - amplitude * (DUCK + 2.0)).abs() <= 1.0 / 32768.0);
        std::fs::remove_dir_all(root).unwrap();
    }
}
