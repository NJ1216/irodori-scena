export function testToneWav(durationSeconds = 0.4) {
  const sampleRate = 8_000;
  const frames = sampleRate * durationSeconds;
  const bytes = Buffer.alloc(44 + frames * 2);
  bytes.write("RIFF", 0);
  bytes.writeUInt32LE(bytes.length - 8, 4);
  bytes.write("WAVEfmt ", 8);
  bytes.writeUInt32LE(16, 16);
  bytes.writeUInt16LE(1, 20);
  bytes.writeUInt16LE(1, 22);
  bytes.writeUInt32LE(sampleRate, 24);
  bytes.writeUInt32LE(sampleRate * 2, 28);
  bytes.writeUInt16LE(2, 32);
  bytes.writeUInt16LE(16, 34);
  bytes.write("data", 36);
  bytes.writeUInt32LE(frames * 2, 40);
  for (let frame = 0; frame < frames; frame += 1) {
    const wave = Math.sin((frame * Math.PI * 2 * 440) / sampleRate);
    bytes.writeInt16LE(Math.round(wave * 8_000), 44 + frame * 2);
  }
  return bytes;
}
