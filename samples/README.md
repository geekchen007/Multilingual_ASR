# Bundled public speech samples

These six recordings let signed-in users try ASR without downloading or uploading
files. They are real corpus recordings, not synthesized speech or canned model
outputs. Selecting a sample creates an ordinary, user-owned evaluation job.

| Dataset | Languages | Recordings | Upstream license |
| --- | --- | --- | --- |
| [AISHELL-1](https://www.openslr.org/33/) | Mandarin Chinese | 2 | Apache-2.0 |
| [LibriSpeech](https://www.openslr.org/12/) | English | 2 | CC-BY-4.0 |
| [Google FLEURS](https://huggingface.co/datasets/google/fleurs) | Japanese, Malay | 2 | CC-BY-4.0 |

## Attribution and provenance

- **AISHELL-1:** Beijing Shell Shell Technology Co., Ltd.; Hui Bu, Jiayu Du,
  Xingyu Na, Bengu Wu and Hao Zheng (2017). Test recordings `BAC009S0764W0121`
  and `BAC009S0764W0122`, obtained from the k2-fsa/icefall model examples hosted
  by csukuangfj on Hugging Face. The original resource page also describes the
  corpus as free for academic use; preserve that upstream notice.
- **LibriSpeech:** Vassil Panayotov, Guoguo Chen, Daniel Povey and Sanjeev
  Khudanpur (2015), and the LibriVox readers. Recordings `1272-128104-0000` and
  `1272-128104-0001`, obtained through Hugging Face's
  `hf-internal-testing/librispeech_asr_dummy` subset of test-clean.
- **FLEURS:** Google; Alexis Conneau et al. (2022), and FLEURS contributors.
  One development-set recording each from `ja_jp` and `ms_my`.

`manifest.json` records each original sample ID, source split, pinned download
location, reference text, attribution, license link, duration, and bundled SHA-256.
Retain the manifest, this notice and the license files when redistributing audio.

## Audio and usage

All recordings were converted to mono, 16 kHz, 16-bit PCM WAV without trimming.
No dataset transcript was changed except removing AISHELL's word-separator spaces.
The original references are available in the interface and are never submitted
to ASR providers as prompts or substituted for recognition results.

The application serves these files locally after login. Selecting a cloud model
sends the selected audio to that provider. Each evaluation stores a separate
normalized clip in the user's test history; bundled originals remain unchanged.

This is a small experience set, not a representative benchmark. Dataset references
are provided for comparison and are not automatically marked as reviewed regression
references. For cropped audio, the displayed dataset reference remains the full
original utterance.
