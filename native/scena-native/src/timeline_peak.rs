//! Four-phase, finite windowed-sinc reconstruction bounds.
//! Bounding absolute contributions also covers changing nonnegative limiter gains.
const RADIUS: isize = 8;

pub(crate) fn kernels() -> Vec<Vec<(isize, f32)>> {
    (1..4)
        .map(|phase| {
            let fraction = phase as f64 / 4.0;
            let mut weights: Vec<_> = (-RADIUS + 1..=RADIUS)
                .map(|offset| {
                    let distance = fraction - offset as f64;
                    let angle = std::f64::consts::PI * distance;
                    let sinc = angle.sin() / angle;
                    let window = 0.5 * (1.0 + (angle / RADIUS as f64).cos());
                    (offset, (sinc * window) as f32)
                })
                .collect();
            let sum: f32 = weights.iter().map(|(_, weight)| *weight).sum();
            for (_, weight) in &mut weights {
                *weight /= sum;
            }
            weights
        })
        .collect()
}

pub(crate) fn bounds(samples: &[f32], channels: usize) -> Vec<f32> {
    let frames = samples.len() / channels;
    let phases = kernels();
    (0..frames)
        .map(|frame| {
            let mut bound = 0.0_f32;
            for channel in 0..channels {
                bound = bound.max(samples[frame * channels + channel].abs());
                for phase in &phases {
                    let mut sum = 0.0;
                    for &(offset, weight) in phase {
                        let index = frame as isize + offset;
                        if index >= 0 && index < frames as isize {
                            sum += (samples[index as usize * channels + channel] * weight).abs();
                        }
                    }
                    bound = bound.max(sum);
                }
            }
            bound
        })
        .collect()
}

#[cfg(test)]
pub(crate) fn measured_peak(samples: &[f32], channels: usize) -> f32 {
    let mut peak = 0.0_f32;
    let frames = samples.len() / channels;
    let phases = kernels();
    for frame in 0..frames {
        for channel in 0..channels {
            peak = peak.max(samples[frame * channels + channel].abs());
            for phase in &phases {
                let sum: f32 = phase
                    .iter()
                    .map(|&(offset, weight)| {
                        let index = frame as isize + offset;
                        if index >= 0 && index < frames as isize {
                            samples[index as usize * channels + channel] * weight
                        } else {
                            0.0
                        }
                    })
                    .sum();
                peak = peak.max(sum.abs());
            }
        }
    }
    peak
}
