use crate::audio::{decode_samples, find_wav_data, Audio};
use std::fs::File;
use std::io::{self, BufReader, Read, Seek, SeekFrom};
use std::path::Path;

pub(crate) fn window(path: &Path, offset: usize, count: usize) -> io::Result<Audio> {
    let mut file = BufReader::new(File::open(path)?);
    let data = find_wav_data(&mut file)?;
    let stride = data.channels * (data.bits as usize / 8);
    let frames = data.size as usize / stride;
    let start = offset.min(frames);
    let length = count.min(frames - start);
    file.seek(SeekFrom::Start(data.start + (start * stride) as u64))?;
    let mut bytes = vec![0; length * stride];
    file.read_exact(&mut bytes)?;
    Ok(Audio {
        samples: decode_samples(&bytes, data.bits)?,
        channels: data.channels,
        rate: data.rate,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::audio::decode_pcm;
    use std::path::PathBuf;

    fn wav(data_size: u32, payload: &[u8], rate: u32, bits: u16) -> Vec<u8> {
        let mut bytes = b"RIFF".to_vec();
        bytes.extend((36 + payload.len() as u32).to_le_bytes());
        bytes.extend(b"WAVEfmt ");
        bytes.extend(16_u32.to_le_bytes());
        bytes.extend(1_u16.to_le_bytes());
        bytes.extend(1_u16.to_le_bytes());
        bytes.extend(rate.to_le_bytes());
        bytes.extend((rate * u32::from(bits) / 8).to_le_bytes());
        bytes.extend((bits / 8).to_le_bytes());
        bytes.extend(bits.to_le_bytes());
        bytes.extend(b"data");
        bytes.extend(data_size.to_le_bytes());
        bytes.extend(payload);
        bytes
    }

    fn temp(name: &str, bytes: &[u8]) -> PathBuf {
        let path =
            std::env::temp_dir().join(format!("scena-native-{}-{name}.wav", std::process::id()));
        std::fs::write(&path, bytes).unwrap();
        path
    }

    #[test]
    fn data_size_beyond_file_is_rejected_without_allocating() {
        let path = temp("oversized", &wav(u32::MAX, &[0, 0, 0, 0], 48_000, 16));
        let decoded = decode_pcm(&path).err().unwrap();
        let windowed = window(&path, 0, 1).err().unwrap();
        std::fs::remove_file(&path).unwrap();
        assert_eq!(decoded.kind(), io::ErrorKind::InvalidData);
        assert_eq!(decoded.to_string(), "WAV data chunk is truncated.");
        assert_eq!(windowed.to_string(), "WAV data chunk is truncated.");
    }

    #[test]
    fn invalid_format_is_rejected_up_front() {
        for (name, rate, bits) in [("zero-rate", 0, 16), ("bad-bits", 48_000, 12)] {
            let path = temp(name, &wav(2, &[0, 0], rate, bits));
            let error = decode_pcm(&path).err().unwrap();
            std::fs::remove_file(&path).unwrap();
            assert_eq!(error.to_string(), "Invalid PCM format.");
        }
    }

    #[test]
    fn valid_file_decodes_and_windows() {
        let payload = [0, 0, 0, 64, 0, 128];
        let path = temp("valid", &wav(6, &payload, 48_000, 16));
        let all = decode_pcm(&path).unwrap();
        let part = window(&path, 1, 5).unwrap();
        std::fs::remove_file(&path).unwrap();
        assert_eq!((all.samples.len(), all.rate, all.channels), (3, 48_000, 1));
        assert_eq!(part.samples, all.samples[1..].to_vec());
    }
}
