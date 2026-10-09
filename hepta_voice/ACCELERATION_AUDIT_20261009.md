# Pocket4 voice acceleration: tested candidate, NOT deployed

This commit is a narrow source candidate based on 1de8fa6351b2594b5af488cda6e11de53afe67c8. It fixes input sample-rate conversion and adds an unused, bounded static prompt-cache component with tests. It does not change live VAD thresholds, TTS thread count, eager-turn strategy, llama.cpp flags, phone permissions or service definitions. Resident source hashes, PIDs and start times were unchanged at the end of this audit.

## Input correctness defect

The custom transport forwarded raw 8kHz mono PCM into a PipelineWorker, Silero VAD, Smart Turn and SegmentedSTT all configured for 16kHz. Native BaseInputTransport did not resample the bytes. Existing success on one synthetic clip did not certify correct audio timing or pitch. The candidate uses SOXRStreamAudioResampler HQ with persistent filter history and rejects mixed sample rates/non-mono/odd byte counts. A 1kHz tone remains 1kHz; a flushed 1-second stream yields exactly 16000 output samples. 16kHz frames remain unchanged. Stream filter delay is real and included in replay measurements.

## Actual Pocket4 tests (fixed real Vulkan GPU model)

All audio inputs were synthetic; no phone calls or microphone capture occurred. An isolated native Pipecat pipeline used the existing authenticated GPU endpoint while the resident voice service was idle. No second GPU model or cloud fallback was used.

After correct resampling, 16 cases completed at VAD stop=0.5s and the same 16 at 0.2s. Median first PCM was 2205.34ms and 1870.17ms respectively; neither group had premature playback in this corpus. Nevertheless 0.2s split and damaged number/negative-word examples: the reference number 零七零四 was lost in the 0.3-second pause case. Therefore 0.2s is NOT promoted. A diagnostic 0.4s comparison also split a name case differently and is not promoted. A short-question case at 0.5s was judged incomplete by Smart Turn and used a longer fallback; finite vs continuous silence changes that observation. These are not P95/P99 estimates or matched comparisons with the old broken-rate path.

Melo 1/2/4 CPU threads, 8 phrases x 3 generations per setting: median synthesis 827.01/457.17/285.41ms; synthetic TTS-to-ASR character edits 14/10/13 over 216 reference characters each. Four threads is faster but has no established quality non-inferiority; stochastic generation and ASR confound attribution. No thread change was deployed. Some outputs lost the 不 in 不是真人; text-policy safety does not alone certify synthesized speech.

Three exact static prompts passed text-to-ASR checks in one cache trial. Cache lookup including PCM SHA verification was about 0.007-0.051ms versus 248-931ms synthesis. This is a component measurement, not full-call latency. No human review is claimed. Dynamic numbers, reservations, payment/phone status and arbitrary replies are not cacheable. Cache identity can bind weights, lexicon, tokens, FSTs, engine version and synthesis settings. The cache component is not connected to the live TTS path.

Prefix-cache A/B on identical fixed inputs: 24 requests, 3 runs per mode over 4 turns. Later-turn median TTFT 771.63ms without reuse vs 101.25ms with reuse; full text reply 924.76ms vs 207.59ms. Input hashes and output texts matched. A separate 12-request actual LLM + whole-reply guard + Melo comparison measured text-to-first-PCM medians 2413.20ms vs 1409.12ms, with identical replies. This excludes ASR and speech endpoint detection. Prefix caching already exists in the current engine; this validates its benefit, not a newly installed engine. Raw model semantics remain imperfect: one unguarded prompt about unavailable tools still returned 已经完成.

Five native Pipecat EagerUserTurnStrategies ExactMatch tests used actual GPU inference with controlled transcript events: exact confirmation, digit change, cancellation, unresolved timeout and deferred read-only tool. Before confirmation: zero audio frames, zero tool calls, empty committed context and zero pending ledger rows in all cases. Exact confirmation to first PCM was 359.78ms; the corrected digit case was 673.95ms. The read-only tool executed once only after confirmation. This does NOT integrate an early ASR endpointer and is not user-speech-to-audio latency. An initial mutable-context evidence snapshot was fixed by copying at measurement time; the suite was rerun and old records retained.

The independent lab and the clean publication candidate each passed 135 tests (two deprecation warnings). A first resampler test incorrectly assumed less than 1000 samples of buffered tail; the corrected test explicitly flushes and checks exact sample count and tone frequency instead of weakening the duration requirement.

## Not completed / not promoted

One controlled resident-service stop/test/restore request was denied by platform safety checks. It was not retried or bypassed. The live rate fix, full restart/cancel regression and production rollout remain unperformed. Token-level n-gram speculation requires a different startup configuration and was not enabled; live speculative type is none. No GPU speculative-decoding speedup is claimed.

Hipfire v0.4.1.1 (2026-10-08), source 0f999cb4dc3a271d9f7c1c473d4c4703111a2bc1, was inspected in an isolated directory. Release kernel assets have gfx1100/gfx1151/gfx1201/gfx906/gfx942, not gfx1150. The pinned model documentation deprecates GGUF input and warns about lossy double quantization. This is an unresolved direct-deployment prerequisite, not proof that gfx1150 can never work. No Hipfire weights were downloaded/requantized and no alternative engine was run. HRX PR27218 remained open/draft/unmerged, observed head 46eee5c5a891feb68c76c522d5410eec2d9afaa4. Weekly change tracking is scoped to actual gfx1150/Qwen3-4B-Instruct-2507 compatibility evidence, never automatic installation.

## Evidence location

Pocket4: /home/alex/.local/state/hepta-voice-opt-20261009/evidence/ holds acceleration-summary.json, audio-manifest.json, tts-thread-results.json, pipeline-eval.json, pipeline-mid.json, prefix-cache.json, cache-full-voice.json, eager-trial.json and fixed-cache-trial.json. Source experiments and the baseline snapshot are under /home/alex/hepta-voice-opt-20261009 and the evidence root. qian-qi voice/model installations were not recreated. Model weights, secrets, audio files and production ledger contents are not committed here.
