# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SkyReels V3 is a multimodal video generation framework built on diffusion transformers. It supports four tasks:
- **reference_to_video** – generate video from 1–4 reference images + text prompt (14B model)
- **single_shot_extension** – extend an existing video 5–30 seconds (14B model)
- **shot_switching_extension** – extend video with cinematic shot transitions, max 5s (14B model)
- **talking_avatar** – generate talking avatar from a portrait image + audio up to 200s (19B model)

## Installation

```bash
pip install -r requirements.txt
# Requires Python 3.12+, CUDA 12.8+, flash_attn, xfuser, torchao
```

## Running Inference

All inference goes through `generate_video.py`. Models are downloaded automatically from HuggingFace on first run (unless `--model_id` points to a local path).

**Single-GPU:**
```bash
python3 generate_video.py --task_type <task> [options]
```

**Multi-GPU (xDiT USP):**
```bash
torchrun --nproc_per_node=4 generate_video.py --task_type <task> --use_usp --seed 42 [options]
```
`--seed` is required when using `--use_usp`.

**Low VRAM (<24GB):**
```bash
export PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True"
python3 generate_video.py --low_vram --resolution 540P --task_type <task> [options]
```
`--low_vram` enables FP8 weight-only quantization (torchao) and block offload. Cannot be combined with `--use_usp`.

**Key flags:** `--offload` (CPU offload), `--resolution` (480P/540P/720P, default 720P), `--duration` (seconds), `--seed`.

Output is saved to `result/<task_type>/<seed>_<timestamp>.mp4`.

## Architecture

### Entry Point
`generate_video.py` parses arguments, initializes distributed environment (NCCL) for multi-GPU, downloads models, pre-processes inputs, instantiates the appropriate pipeline, runs generation, and saves results via `imageio.mimwrite`.

### Package Structure (`skyreels_v3/`)

- **`config.py`** – `ASPECT_RATIO_CONFIG` dict (resolution → aspect ratio → (H, W) tuples), `SHOT_NUM_CONDITION_FRAMES_MAP`
- **`configs/`** – `WAN_CONFIGS` (EasyDict-based), only entry is `"talking-avatar-19B"` from `talking_avatar_19B.py`
- **`modules/`** – Model components:
  - `transformer.py` / `transformer_a2v.py` – `WanModel` (extension/avatar pipelines)
  - `vae.py` – `WanVAE` wrapper
  - `t5.py` – `T5EncoderModel` (UMT5-XXL)
  - `clip.py` / `xlm_roberta.py` / `wav2vec2.py` – encoders for avatar pipeline
  - `attention.py`, `tokenizers.py` – shared utilities
  - `reference_to_video/transformer.py` – `SkyReelsA2WanI2v3DModel` (custom diffusers-compatible model for reference-to-video)
  - `__init__.py` – `download_model()`, `get_vae()`, `get_transformer()`, `get_text_encoder()`, `get_image_encoder()` factory functions
- **`pipelines/`** – Four pipeline classes (one per task):
  - `ReferenceToVideoPipeline` – wraps `WanSkyReelsA2WanT2VPipeline` (a `diffusers.DiffusionPipeline` subclass). Uses `UniPCMultistepScheduler` with flow prediction. Supports dual classifier-free guidance (text + image).
  - `SingleShotExtensionPipeline` / `ShotSwitchingExtensionPipeline` – use custom `WanModel` + `FlowUniPCMultistepScheduler`. Load VAE from `Wan2.1_VAE.pth`, transformer from `transformer/` subfolder.
  - `TalkingAvatarPipeline` – uses `WanModel` from `transformer_a2v.py`, CLIP, T5, WAV2VEC2, `WanVAE`. Audio is preprocessed via `preprocess_audio()` before pipeline invocation.
- **`scheduler/`** – `FlowUniPCMultistepScheduler` used by extension pipelines
- **`distributed/`** – Context parallel (sequence parallelism) implementations:
  - `context_parallel_for_reference.py` – patches transformer for `ReferenceToVideoPipeline`
  - `context_parallel_for_extension.py` – patches attention/forward for extension pipelines
  - `context_parallel_for_avatar.py` – patches for avatar pipeline
- **`utils/`** – `util.py` (video loading/resizing, `get_height_width_from_image`), `avatar_preprocess.py`, `avatar_util.py`

### Key Design Patterns

**Two transformer architectures coexist:**
1. `SkyReelsA2WanI2v3DModel` (reference_to_video) – compatible with diffusers `WanTransformer3DModel`, loaded via `from_pretrained`
2. `WanModel` (extension/avatar) – custom implementation, loaded from `config.json` + `.safetensors` files

**Multi-GPU parallelism:** `--use_usp` uses xDiT's Unified Sequence Parallelism. The `distributed/` modules monkey-patch transformer attention/forward methods. Input preparation (downloads, audio preprocessing) happens on rank 0 only and results are broadcast to all ranks via `dist.broadcast_object_list`.

**Memory modes:**
- Default: full model on GPU
- `--offload`: text encoder and transformer stay on CPU, moved to GPU only during their forward pass; VAE stays on GPU
- `--low_vram`: same as offload + FP8 quantization (`torchao.float8_weight_only`) + VAE tiling + block-level offload during denoising

**Resolution handling:** `ASPECT_RATIO_CONFIG` maps resolution names to dicts of aspect ratio strings → (H, W). The closest aspect ratio to the input image/video is selected and dimensions are rounded to multiples of 16.

**Frame rates:** 24 fps for all tasks except talking_avatar (25 fps).

## Model IDs

| Task | HuggingFace Model |
|------|-------------------|
| `reference_to_video` | `Skywork/SkyReels-V3-Reference2Video` |
| `single_shot_extension` / `shot_switching_extension` | `Skywork/SkyReels-V3-Video-Extension` |
| `talking_avatar` | `Skywork/SkyReels-V3-TalkingAvatar` |
