# Japanese lip-sync model attribution

The Japanese model and processor are licensed under Apache License 2.0.
See Apache-2.0.txt in this directory.

- Quantized ONNX distributor: mnaoizyyy/charsiu-js-models,
  revision d22b7e9b99d5fb2bed3e10fa8014917c2a4403dd.
  https://huggingface.co/mnaoizyyy/charsiu-js-models
- Original phoneme model and processor: prj-beatrice/japanese-hubert-base-phoneme-ctc,
  processor revision 1ec4eb3c45b2a1cafb7c477d447df34ca03070f2.
  https://huggingface.co/prj-beatrice/japanese-hubert-base-phoneme-ctc
- Base model: rinna/japanese-hubert-base (Apache-2.0).
  https://huggingface.co/rinna/japanese-hubert-base

The distributor describes the ONNX file as a torch.onnx conversion with ONNX Runtime
dynamic INT8 quantization. The distributor does not identify the original checkpoint
revision. SCENA distributes those exact quantized bytes without modifying them and
does not claim independently verified equivalence to a particular original checkpoint.
The distributor explicitly licenses the Japanese file as Apache-2.0; the repository-wide
MIT label is not used for this file.

The original model card describes fine-tuning on ReazonSpeech v2 with phoneme labels
produced by pyopenjtalk-plus. No training corpus, dictionary, tokenizer executable,
OpenJTalk implementation or charsiu-js application code is bundled here.

Flatbuffers 25.12.19 license source:
https://github.com/google/flatbuffers/blob/v25.12.19/LICENSE
The original Apache-2.0 license is included as flatbuffers-25.12.19.txt.

SCENA Japanese LAB refinement code: Copyright (c) 2026 NJ, MIT License.
See SCENA-MIT.txt. Python and dependency copyright notices are included separately.
