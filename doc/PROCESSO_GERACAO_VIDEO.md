# Processo de Geração de Vídeo — SkyReels V3

Documento baseado na execução real do teste `reference_to_video` (2026-02-22).
Explica cada etapa, cada componente e cada parâmetro do sistema.

---

## Visão Geral do Fluxo

```
Entrada (imagens + texto)
        │
        ▼
1. Parsing de argumentos (generate_video.py)
        │
        ▼
2. Download/resolução do modelo (HuggingFace Hub)
        │
        ▼
3. Preparação dos inputs (imagens → PIL, URLs → local)
        │
        ▼
4. Instanciação do Pipeline
        │
        ▼
5. Encoding do texto (T5 → embeddings)
        │
        ▼
6. Encoding das imagens de referência (VAE → latents)
        │
        ▼
7. Loop de denoising (8 steps × ~101s)
        │  └─ a cada step: Transformer forward pass (3x com CFG)
        │  └─ a cada step: Scheduler atualiza os latents
        ▼
8. VAE Decode (latents → frames RGB)
        │
        ▼
9. Salvar como MP4 (imageio)
```

---

## 1. Parsing de Argumentos (`generate_video.py`)

O ponto de entrada único do sistema. Aceita:

| Argumento | Tipo | Descrição |
|-----------|------|-----------|
| `--task_type` | string | Qual pipeline usar: `reference_to_video`, `single_shot_extension`, `shot_switching_extension`, `talking_avatar` |
| `--prompt` | string | Descrição textual do vídeo desejado. Vai para o encoder T5 |
| `--resolution` | string | `480P`, `540P` ou `720P`. Determina a tabela de dimensões usada |
| `--duration` | int | Duração em segundos. Convertida em `num_frames = duration × fps + 1` |
| `--seed` | int | Semente aleatória. Controla o ruído inicial — mesmo seed = mesmo vídeo |
| `--ref_imgs` | string | Caminhos das imagens de referência separados por vírgula (máx 4) |
| `--offload` | flag | Move modelos para CPU entre usos, libera VRAM. Mais lento, menos memória |
| `--low_vram` | flag | Offload + quantização FP8 (torchao). Para GPUs < 24 GB. Incompatível com `--use_usp` |
| `--use_usp` | flag | Paralelismo multi-GPU via xDiT USP. Usa `torchrun`. Incompatível com `--low_vram` |
| `--model_id` | string | Path local ou ID HuggingFace. Se omitido, selecionado automaticamente pelo `task_type` |

**O que acontece no nosso teste:**
```
task_type=reference_to_video, resolution=540P, duration=5, seed=42, offload=True
→ num_frames = 5 × 24 + 1 = 121
→ modelo: Skywork/SkyReels-V3-Reference2Video
```

---

## 2. Seleção de Modelo e Download

```python
MODEL_ID_CONFIG = {
    "reference_to_video":         "Skywork/SkyReels-V3-Reference2Video",   # 14B params, ~49 GB
    "single_shot_extension":      "Skywork/SkyReels-V3-Video-Extension",   # 14B params, ~28 GB
    "shot_switching_extension":   "Skywork/SkyReels-V3-Video-Extension",   # mesmo modelo
    "talking_avatar":             "Skywork/SkyReels-V3-TalkingAvatar",     # 19B params, ~38 GB
}
```

`download_model()` em `skyreels_v3/modules/__init__.py`:
- Se o path já existe localmente → usa direto
- Se não → chama `huggingface_hub.snapshot_download()` e baixa para `~/.cache/huggingface/hub/`
- Retorna o path local do snapshot

**No nosso teste:** modelo já estava em cache (`~/.cache/huggingface/hub/models--Skywork--SkyReels-V3-Reference2Video/snapshots/8df04fa.../`), carga em ~3s.

A linha de log `Fetching 21 files: 100%|█| 21/21` indica verificação dos 21 arquivos do repositório (não re-download, apenas checagem de integridade).

---

## 3. Preparação dos Inputs (`prepare_and_broadcast_inputs`)

Para `reference_to_video`:
1. String `"ref_imgs/0_1.png,ref_imgs/0_2.png"` é separada por vírgula em lista
2. Cada path é verificado: se for URL → baixa com `wget`; se local → usa direto
3. Cada path é carregado como `PIL.Image` via `diffusers.utils.load_image()`
4. Em modo multi-GPU: rank 0 faz o download e transmite os paths para os outros ranks via `dist.broadcast_object_list()`

**Resultado no nosso teste:**
```
ref_imgs = [PIL.Image 960x544, PIL.Image 960x544]
```
As imagens foram redimensionadas para 960x544 ao carregar (resolução 540P, aspect ratio 1.78).

---

## 4. Seleção de Resolução e Dimensões (`config.py`)

`ASPECT_RATIO_CONFIG` é um dicionário de três níveis:
```
resolução → aspect_ratio → (altura, largura)
```

**Como funciona a seleção:**
1. Calcula o aspect ratio da imagem de entrada (largura/altura)
2. Encontra o aspect ratio mais próximo na tabela para a resolução escolhida
3. Usa as dimensões correspondentes

**Para 540P, as dimensões base são:**

| Aspect Ratio | Dimensões (H × W) | Uso |
|---|---|---|
| 0.57 (9:16 vertical) | 544 × 960 | ← nosso teste |
| 0.75 (4:3 vertical) | 624 × 832 | |
| 1.00 (quadrado) | 720 × 720 | |
| 1.33 (4:3) | 832 × 624 | |
| 1.78 (16:9) | 960 × 544 | paisagem |

> Todas as dimensões são múltiplos de 16 (requisito do transformer).

---

## 5. Instanciação do Pipeline (`ReferenceToVideoPipeline`)

O pipeline `reference_to_video` usa `WanSkyReelsA2WanT2VPipeline`, uma subclasse de `diffusers.DiffusionPipeline`.

Contém 5 componentes carregados via `from_pretrained`:

| Componente | Classe | Função |
|-----------|--------|--------|
| `tokenizer` | `AutoTokenizer` (UMT5) | Converte texto em token IDs |
| `text_encoder` | `UMT5EncoderModel` | Converte tokens em embeddings semânticos |
| `transformer` | `SkyReelsA2WanI2v3DModel` | Modelo principal de denoising (14B) |
| `vae` | `AutoencoderKLWan` | Encoder/decoder entre pixels e espaço latente |
| `scheduler` | `UniPCMultistepScheduler` | Controla o processo de denoising |

**Log observado:**
```
Loading checkpoint shards: 100%|████| 5/5 [00:02]
Loading pipeline components...: 100%|████| 5/5 [00:02]
```
O transformer está dividido em 5 shards de safetensors (~10 GB cada).

**Warning inofensivo:**
```
Expected types for transformer: WanTransformer3DModel, got SkyReelsA2WanI2v3DModel
```
O diffusers espera o tipo base; o SkyReels usa uma subclasse customizada compatível.

---

## 6. Encoding do Texto (T5 UMT5-XXL)

**O que é o T5/UMT5:**
- UMT5 (Unified Multilingual T5) é um modelo encoder-decoder de linguagem da Google
- Versão XXL: ~11B parâmetros
- Transforma texto em vetores de alta dimensionalidade que capturam semântica

**Fluxo em `_get_t5_prompt_embeds()`:**
```
prompt (string)
    │
    ▼ ftfy.fix_text() + html.unescape()  ← limpeza de encoding
    │
    ▼ tokenizer(padding="max_length", max_length=512)
    │  → token IDs + attention_mask
    │
    ▼ text_encoder(input_ids, attention_mask)
    │  → last_hidden_state: tensor [1, 512, 4096]
    │
    ▼ truncar ao comprimento real do prompt
    │  → tensor [1, N_tokens, 4096]
    │
    ▼ repadd até max_length=512
    │
    ▼ prompt_embeds: tensor [1, 512, 4096]
```

**Com `--offload`:** o text_encoder vai para GPU → faz o forward → volta para CPU, memória liberada.

**Dual guidance:** o sistema gera dois embeddings:
- `prompt_embeds`: embedding do prompt real
- `negative_prompt_embeds`: embedding de prompt vazio `""` (para CFG)

---

## 7. Encoding das Imagens de Referência (VAE Encoder)

**O que é o VAE (Variational Autoencoder):**
- Comprime imagens/vídeos de espaço de pixels para espaço latente
- Fator de compressão espacial: 8× (960→120, 544→68)
- Fator temporal: 4× (para vídeos)
- Espaço latente: 16 canais (z_dim=16)

**Fluxo em `prepare_latents()`:**
```
PIL.Image (960×544, RGB)
    │
    ▼ F.to_tensor() → [0,1]
    ▼ .sub_(0.5).div_(0.5) → [-1,1]  ← normalização padrão
    │
    ▼ unsqueeze: [1, 3, 1, 544, 960]  ← batch=1, C=3, T=1, H, W
    │
    ▼ vae.encode() → distribuição latente
    │
    ▼ retrieve_latents() → sample da distribuição
    │  → tensor [1, 16, 1, 68, 120]
    │
    ▼ normalização: (latent - mean) × (1/std)
    │  → latent normalizado para média 0
```

**Para 2 imagens de referência + 2 zeros (padding até máx 4):**
```
ref_vae_latents = cat([img1_latent, img2_latent, zeros, zeros], dim=2)
→ tensor [1, 16, 4, 68, 120]
```

**O ruído inicial (latents):**
```python
latents = randn_tensor([1, 16, 31, 68, 120])
# num_latent_frames = (121-1)//4 + 1 = 31
```
Este tensor de ruído gaussiano é o que será progressivamente "limpado" pelo denoising.

---

## 8. Loop de Denoising (8 Steps)

Este é o coração do processo — ~13 minutos no nosso teste.

### O que é Denoising por Difusão

A ideia central: começar com ruído puro (Gaussiano) e remover o ruído gradualmente, guiado pelo texto e pelas imagens de referência.

### Scheduler: `UniPCMultistepScheduler`

O scheduler controla **quando** e **quanto** ruído é removido em cada step. Usa o algoritmo UniPC (Unified Predictor-Corrector), mais eficiente que DDPM puro.

Com `num_inference_steps=8`, os timesteps são distribuídos em [0, 1000]:
```
t=1000 → t=857 → t=714 → t=571 → t=428 → t=285 → t=142 → t=0
(muito ruído)                                              (sem ruído)
```

### O Transformer: `SkyReelsA2WanI2v3DModel` (14B parâmetros)

Modelo de atenção 3D (espacial + temporal) baseado na arquitetura Wan. A cada step, recebe:

```
hidden_states = cat([latents_ruidosos, condition_imagens], dim=2)
              = [1, 16, 31+4, 68, 120]  ← frames de vídeo + frames de referência

timestep = t  ← quanto ruído existe agora (embedding aprendido)

encoder_hidden_states = prompt_embeds  ← o que queremos gerar [1, 512, 4096]
```

E prevê: `noise_pred` — o ruído a ser removido.

### Dual Classifier-Free Guidance (CFG)

A técnica CFG permite controlar o "quanto o modelo segue o prompt". O sistema faz **3 forward passes por step**:

```
1. noise_pred          = Transformer(latents + condition_imgs, prompt_embed)
                         ↑ condicionado por texto E imagens

2. noise_uncond_txt    = Transformer(latents + condition_imgs, neg_prompt_embed)
                         ↑ condicionado APENAS por imagens (texto nulo)

3. noise_uncond_txt_img = Transformer(latents + zeros, neg_prompt_embed)
                          ↑ sem condicionamento nenhum

Final:
noise_final = noise_uncond_txt_img
            + guidance_scale_img × (noise_uncond_txt - noise_uncond_txt_img)
            + guidance_scale     × (noise_pred - noise_uncond_txt)
```

Com `guidance_scale=1.0` e `guidance_scale_img=1.0` (nosso teste), o CFG está desabilitado efetivamente — só usa o passo 1. Valores maiores (ex: 7.5) aumentariam a fidelidade ao prompt mas podem reduzir variedade.

### Scheduler Step

Após o forward pass:
```python
latents = scheduler.step(noise_pred, t, latents)[0]
```
O scheduler usa a previsão de ruído para calcular os latents "menos ruidosos" para o próximo step. É a "receita" matemática do UniPC.

**Com `--offload`:** o transformer vai para GPU antes do loop e volta para CPU depois.

---

## 9. VAE Decode

Após os 8 steps, os latents finais (quase sem ruído) são decodificados de volta para pixels:

```
latents [1, 16, 31, 68, 120]
    │
    ▼ desnormalização: latent × std + mean
    │
    ▼ vae.decode() ← processo inverso do encoder
    │  → video tensor [1, 3, 121, 544, 960]  ← C=RGB, T=frames, H, W
    │
    ▼ video_processor.postprocess_video()
    │  → normalização [-1,1] → [0,255]
    │  → tensor de uint8
```

O VAE é a parte mais custosa em memória pois processa todos os 121 frames de uma vez.

---

## 10. Salvamento (`imageio.mimwrite`)

```python
imageio.mimwrite(
    "result/reference_to_video/42_2026-02-22_06-22-44.mp4",
    video_out,       # array numpy [121, 544, 960, 3]
    fps=24,          # 24 fps para todos os tasks exceto talking_avatar (25 fps)
    quality=8,       # escala 0-10, 8 = alta qualidade
    output_params=["-loglevel", "error"],  # suprime logs do ffmpeg
)
```

**Nome do arquivo:** `{seed}_{timestamp}.mp4`
- `42` = seed usado
- `2026-02-22_06-22-44` = horário de conclusão

---

## Resumo: O Que Cada Arquivo Faz

| Arquivo | Responsabilidade |
|---------|-----------------|
| `generate_video.py` | Entry point: argumentos, download, orquestração, salvamento |
| `skyreels_v3/config.py` | Tabela de resoluções e aspect ratios |
| `skyreels_v3/modules/__init__.py` | Factory functions: download_model, get_vae, get_transformer |
| `skyreels_v3/modules/reference_to_video/transformer.py` | Arquitetura do transformer 14B (SkyReelsA2WanI2v3DModel) |
| `skyreels_v3/pipelines/reference_to_video_pipeline.py` | Pipeline completo: encode → denoise → decode |
| `skyreels_v3/scheduler/` | FlowUniPCMultistepScheduler (para pipelines de extensão) |
| `skyreels_v3/distributed/` | Patches de atenção para multi-GPU |

---

## Números do Nosso Teste

| Métrica | Valor |
|---------|-------|
| Resolução | 960 × 544 (540P, aspect 1.78) |
| Frames | 121 (5s × 24fps + 1) |
| Latent frames | 31 = (121-1)÷4 + 1 |
| Latent shape | [1, 16, 31, 68, 120] |
| Steps denoising | 8 × ~101s = ~13.5 min |
| RAM pico | ~66 GB / 119 GB disponíveis |
| Arquivo final | 3.7 MB |
| Tempo total | ~18 minutos |

---

## Warnings Explicados

| Warning | Causa | Problema? |
|---------|-------|-----------|
| `cuda capability 12.1 ... max is 12.0` | GB10 (Blackwell) é mais novo que o PyTorch instalado | Não — funciona por compatibilidade forward |
| `flash_attn not found` | flash-attention não instalada (ARM64) | Não — usa atenção padrão do PyTorch, ~20% mais lento |
| `Expected types for transformer: WanTransformer3DModel` | diffusers espera o tipo base, SkyReels usa subclasse | Não — subclasse é compatível por herança |
| `amp.autocast deprecated` | API antiga do PyTorch em transformer_a2v.py | Não — aviso cosmético, funciona |
