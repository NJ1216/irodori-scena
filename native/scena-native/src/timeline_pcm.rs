use crate::audio::{decode_samples, Audio};
use std::fs::File;
use std::io::{self, Read, Seek, SeekFrom};
use std::path::Path;

pub(crate) fn window(path: &Path, offset: usize, count: usize) -> io::Result<Audio> {
    let mut file = File::open(path)?;
    let mut header = [0; 12];
    file.read_exact(&mut header)?;
    if &header[..4] != b"RIFF" || &header[8..] != b"WAVE" {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "Expected PCM WAV",
        ));
    }
    let mut format = None;
    loop {
        let mut chunk = [0; 8];
        file.read_exact(&mut chunk)?;
        let size = u32::from_le_bytes(chunk[4..].try_into().unwrap()) as u64;
        let position = file.stream_position()?;
        if &chunk[..4] == b"fmt " && size >= 16 {
            let mut fmt = [0; 16];
            file.read_exact(&mut fmt)?;
            let code = u16::from_le_bytes(fmt[..2].try_into().unwrap());
            let channels = u16::from_le_bytes(fmt[2..4].try_into().unwrap()) as usize;
            let rate = u32::from_le_bytes(fmt[4..8].try_into().unwrap());
            let bits = u16::from_le_bytes(fmt[14..16].try_into().unwrap());
            if code != 1 || channels == 0 || rate == 0 || ![8, 16, 24, 32].contains(&bits) {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidData,
                    "Invalid PCM format",
                ));
            }
            format = Some((channels, rate, bits));
        } else if &chunk[..4] == b"data" {
            let (channels, rate, bits) = format
                .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidData, "Missing WAV format"))?;
            let stride = channels * (bits as usize / 8);
            let frames = size as usize / stride;
            let start = offset.min(frames);
            let length = count.min(frames - start);
            file.seek(SeekFrom::Start(position + (start * stride) as u64))?;
            let mut bytes = vec![0; length * stride];
            file.read_exact(&mut bytes)?;
            return Ok(Audio {
                samples: decode_samples(&bytes, bits)?,
                channels,
                rate,
            });
        }
        file.seek(SeekFrom::Start(position + size + size % 2))?;
    }
}
