# Análise e Plano: SkyReels V3 no DGX Spark
**Data:** 2026-02-22
**Autor:** Claude Code (Sonnet 4.6)
**Status:** Em execução — ambiente isolado sendo criado

---

## 1. Comparativo: Hardware vs. Requisitos

| Critério | DGX Spark (produção) | SkyReels V3 precisa | Status |
|----------|----------------------|----------------------|--------|
| CUDA | 13.0 | 12.8+ | ✅ OK (retrocompat.) |
| Python | 3.12.3 | 3.12+ | ✅ OK |
| VRAM | **122 GB (unificada)** | ~28–38 GB por modelo | ✅ FOLGA ENORME |
| Disco livre | 1.7 TB | ~94 GB todos modelos | ✅ OK (5.5% do livre) |
| CPU | **ARM64 (aarch64)** | x86_64 assumido | ⚠️ Risco em flash_attn |
| PyTorch prod. | 2.10.0+cu130 | `==2.8.0` no req.txt | ⚠️ Resolvido: venv separado com 2.10.0 |

---

## 2. Capacidades Novas vs. Stack Atual (VideosDGX)

| Capacidade | Wan 2.2 | LTX-2 | **SkyReels V3** |
|---|---|---|---|
| Text-to-Video | ✅ | ✅ | ❌ (não é o foco) |
| Image-to-Video | ✅ 5B | ✅ | ✅ (R2V com até 4 imagens ref.) |
| **Multi-referência (1–4 imagens)** | ❌ | ❌ | ✅ **NOVO** |
| **Extensão de vídeo (5–30s)** | ❌ | ❌ | ✅ **NOVO** |
| **Troca de planos cinematográficos** | ❌ | ❌ | ✅ **NOVO** |
| Talking Avatar (lip sync, 200s) | ❌ | ⚠️ parcial | ✅ **NOVO** (19B dedicado) |

SkyReels V3 é **complementar**, não concorrente ao stack atual.

---

## 3. Riscos Técnicos

### 3.1 flash_attn no ARM64 — Risco Médio
- Não há wheels pré-compilados para ARM64+CUDA13 no PyPI
- Fallbacks: compilar na máquina ou `FLASH_ATTENTION_SKIP_CUDA_BUILD=TRUE`
- SkyReels usa flash_attn via diffusers/transformers, que têm fallback para atenção padrão

### 3.2 PyTorch 2.8.0 → 2.10.0 — Risco Baixo
- requirements.txt pede 2.8.0, mas código usa APIs estáveis
- Estratégia: instalar 2.10.0+cu130 (já testado e funcional nesta máquina)

### 3.3 xfuser / yunchang — Irrelevante
- Necessários apenas para `--use_usp` (multi-GPU)
- DGX Spark tem 1 GPU — nunca será usado
- Pular instalação completamente

### 3.4 VRAM — Sem Risco
| Modelo SkyReels | VRAM BF16 | Com `--low_vram` FP8 |
|---|---|---|
| R2V 14B | ~28 GB | ~14 GB |
| V2V 14B | ~28 GB | ~14 GB |
| Talking 19B | ~38 GB | ~19 GB |

Com fila sequencial já existente na interface VideosDGX: zero risco de OOM.

---

## 4. Modelos SkyReels V3

| Task Type | HuggingFace ID | Tamanho estimado |
|---|---|---|
| `reference_to_video` | `Skywork/SkyReels-V3-Reference2Video` | ~28 GB |
| `single_shot_extension` + `shot_switching_extension` | `Skywork/SkyReels-V3-Video-Extension` | ~28 GB |
| `talking_avatar` | `Skywork/SkyReels-V3-TalkingAvatar` | ~38 GB |

Download automático para `~/.cache/huggingface/hub/`.

---

## 5. Ambiente Criado (isolado)

```
/home/nmaldaner/projetos/SkyReels-V3/
├── .venv/                  # venv isolado (Python 3.12 + PyTorch 2.10.0+cu130)
├── doc/
│   └── ANALISE_E_PLANO.md  # este arquivo
├── generate_video.py       # entry point
├── requirements.txt        # original (referência)
├── skyreels_v3/            # pacote principal
└── result/                 # outputs gerados (criado no primeiro run)
```

### Ativar ambiente
```bash
source /home/nmaldaner/projetos/SkyReels-V3/.venv/bin/activate
cd /home/nmaldaner/projetos/SkyReels-V3
```

### Dependências instaladas
- PyTorch: `2.10.0+cu130` (em vez de 2.8.0 — compatível e testado na máquina)
- flash_attn: instalado se possível, caso contrário skip (fallback automático)
- xfuser / yunchang: **não instalados** (single GPU, desnecessário)

---

## 6. Comandos de Teste

### Reference to Video (primeiro teste recomendado)
```bash
source /home/nmaldaner/projetos/SkyReels-V3/.venv/bin/activate
cd /home/nmaldaner/projetos/SkyReels-V3

python3 generate_video.py \
  --task_type reference_to_video \
  --ref_imgs "https://skyreels-api.oss-accelerate.aliyuncs.com/examples/subject_reference/0_1.png,https://skyreels-api.oss-accelerate.aliyuncs.com/examples/subject_reference/0_2.png" \
  --prompt "Two people talking in a park, cinematic shot" \
  --duration 5 \
  --offload \
  --seed 42
```

### Video Extension (Single Shot)
```bash
python3 generate_video.py \
  --task_type single_shot_extension \
  --input_video https://skyreels-api.oss-accelerate.aliyuncs.com/examples/video_extension/test.mp4 \
  --prompt "A man walking forward slowly" \
  --duration 5 \
  --offload \
  --seed 42
```

### Talking Avatar
```bash
python3 generate_video.py \
  --task_type talking_avatar \
  --input_image "https://skyreels-api.oss-accelerate.aliyuncs.com/examples/talking_avatar_video/single1.png" \
  --input_audio "https://skyreels-api.oss-accelerate.aliyuncs.com/examples/talking_avatar_video/single_actor/huahai_5s.mp3" \
  --prompt "A woman giving a confident speech" \
  --offload \
  --seed 42
```

---

## 7. Monitoramento Durante Testes

```bash
# Terminal 2 — monitorar VRAM em tempo real
watch -n 1 nvidia-smi

# Terminal 3 — verificar disco
watch -n 30 df -h /home/nmaldaner

# Ver outputs gerados
ls -lth /home/nmaldaner/projetos/SkyReels-V3/result/
```

---

## 8. Rollback (se necessário)

```bash
# Remove tudo sem tocar na produção
rm -rf /home/nmaldaner/projetos/SkyReels-V3/.venv
rm -rf ~/.cache/huggingface/hub/models--Skywork*

# VideosDGX continua funcionando normalmente
```

---

## 9. Plano de Integração (Fase Futura — após validação)

Após validar os 3 task types com sucesso:

1. **Wrapper scripts** — `gerar_video_skyreels_r2v.py`, `gerar_video_skyreels_v2v.py`, `gerar_video_skyreels_avatar.py`
2. **Interface web** — adicionar 3 novos modelos no seletor da v4.2 (ou nova versão)
3. **Job queue** — subprocess com `.venv` python, mesmo padrão do ComfyUI na interface atual

### Arquitetura de integração (idêntica à atual)
```
Interface Web v4.x (FastAPI :7862)
    ├── ComfyUI jobs → HTTP POST → ComfyUI :8188      [existente]
    └── SkyReels jobs → subprocess → .venv/bin/python  [NOVO]
```

---

**Status:** Ambiente criado e dependências instaladas
**Próxima ação:** Testar os 3 task types e medir VRAM real
