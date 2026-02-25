<p align="center">
  <img src="assets/logo2.png" alt="SkyReels Logo" width="40%">
</p>

<h1 align="center">SkyReels V3 — INEMA Web UI</h1>

<p align="center">
  Fork do <a href="https://github.com/SkyworkAI/SkyReels-V3">SkyworkAI/SkyReels-V3</a> com Web UI completa para produção de episódios em batch.
</p>

---

## O que é este projeto

Este repositório é um fork do modelo de geração de vídeo **SkyReels V3**, com uma interface Web (Web UI) construída sobre ele para produção de vídeos em escala — especialmente séries animadas com múltiplos personagens e cenas.

### Funcionalidades adicionadas neste fork

- **Web UI completa** — geração individual ou em fila, sem linha de comando
- **Named Queues** — filas nomeadas com dezenas de cenas, controle por cena, retomada após erro
- **Suporte a `talking_avatar` na UI** — imagem de personagem + áudio MP3 → vídeo falante
- **Importação de episódio via JSON** — uma cena por objeto, suporte a tipos mistos
- **Edição de cenas em runtime** — altere prompt, seed, resolução sem reiniciar a fila
- **Finalização automática** — concatenação das cenas concluídas em um vídeo final via ffmpeg
- **Galeria de vídeos** — visualização de todos os vídeos gerados com player e privacidade por card

---

## Modelos suportados (SkyReels V3)

| Task | Modelo | HuggingFace |
|---|---|---|
| `reference_to_video` | 14B | [SkyReels-V3-R2V-14B](https://huggingface.co/Skywork/SkyReels-V3-R2V-14B) |
| `single_shot_extension` | 14B | [SkyReels-V3-V2V-14B](https://huggingface.co/Skywork/SkyReels-V3-V2V-14B) |
| `shot_switching_extension` | 14B | [SkyReels-V3-V2V-14B](https://huggingface.co/Skywork/SkyReels-V3-V2V-14B) |
| `talking_avatar` | 19B | [SkyReels-V3-A2V-19B](https://huggingface.co/Skywork/SkyReels-V3-A2V-19B) |

---

## Instalação

```bash
git clone https://github.com/inematds/skyreelsv3
cd skyreelsv3

python3.12 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

# Opcional mas recomendado
pip install flash-attn --no-build-isolation  # atenção flash (hardware compatível)
pip install xfuser                           # multi-GPU
pip install torchao                          # FP8 / Low VRAM mode
```

Os modelos são baixados automaticamente do HuggingFace na primeira execução.

---

## Rodando a Web UI

```bash
source .venv/bin/activate
python webui/app.py
# → http://localhost:7860
```

Acesse de qualquer dispositivo na rede local via `http://<ip-do-servidor>:7860`.

---

## Web UI — Painel de Geração

### Campos do formulário

| Campo | Descrição |
|---|---|
| **Task Type** | `reference_to_video` · `single_shot_extension` · `shot_switching_extension` · `talking_avatar` |
| **Prompt** | Descrição textual do vídeo desejado |
| **Reference Images** | Caminhos separados por vírgula — 1 a 4 imagens (`reference_to_video`) |
| **Input Video** | Caminho local ou URL para tasks de extensão |
| **Portrait Image** | Imagem de retrato para `talking_avatar` (jpg / png / gif / bmp) |
| **Audio File** | Áudio de condução para `talking_avatar` (mp3 / wav · máx 200 s) |
| **Resolution** | `480P` / `540P` / `720P` — `talking_avatar` só aceita `480P` ou `720P` |
| **Duration** | Segundos de saída — ignorado em `talking_avatar` (definido pelo áudio) |
| **Seed** | Semente para reprodutibilidade |
| **Offload CPU** | Move modelos para CPU entre passes — reduz VRAM |
| **Low VRAM** | Quantização FP8 + block offload — necessário para `talking_avatar` em GPUs < 24 GB |

### Botões de ação

- **Gerar Vídeo** — inicia geração imediata
- **+ Fila** — adiciona à fila simples (tab Fila)

---

## Web UI — Named Queues (Produção em Batch)

A aba **Fila** suporta filas nomeadas com múltiplas cenas. Ideal para produção de episódios com dezenas de takes.

### Ações por fila

| Botão | Ação |
|---|---|
| **↑ Importar** | Carrega um arquivo `.json` como nova fila nomeada |
| **▶ Continuar** | Executa todas as cenas `idle` em sequência, pula erros |
| **↩ Repetir do erro** | Reseta cenas com erro e retoma daquele ponto |
| **↺ Reiniciar do zero** | Reseta todas (incluindo `done`) e começa do início |
| **🎬 Finalizar** | Concatena todos os vídeos `done` em um `.mp4` final via ffmpeg |
| **🗑** | Exclui a fila |

Cada card de cena exibe status, tipo, resolução e seed. Ao abrir a fila as cenas aparecem expandidas. Controles ⊞ (expandir todas) / ⊟ (colapsar todas) disponíveis.

### Edição de cena em runtime

Clique em ✏️ em qualquer cena com status `idle` ou `error` para editar prompt, seed, resolução, arquivos de referência e outros campos — sem precisar reiniciar o servidor.

### API REST (PATCH)

```bash
# Alterar parâmetros de uma cena específica
curl -X PATCH http://localhost:7860/nqueues/<fila_id>/jobs/<job_id> \
  -H "Content-Type: application/json" \
  -d '{"resolution": "720P", "seed": 9999, "prompt": "novo prompt"}'
```

Campos protegidos (não alteráveis): `id`, `nq_id`, `status`, `task_type`, `created_at`, `output_video`.

---

## Formato JSON de Episódio

Importe um arquivo `.json` com um array de cenas para criar uma fila nomeada. Tipos de task podem ser misturados no mesmo arquivo.

```json
[
  {
    "label": "C01-A · Corredor — Estabelecimento",
    "task_type": "reference_to_video",
    "prompt": "A modern school hallway on the first day of school...",
    "resolution": "540P",
    "duration": 4,
    "seed": 1001,
    "offload": true,
    "low_vram": false,
    "ref_imgs": [
      "uploads/projeto/cena01.png",
      "uploads/projeto/personagem_a.png",
      "uploads/projeto/personagem_b.png"
    ]
  },
  {
    "label": "C01-B · Personagem A — 'Foi mal!'",
    "task_type": "talking_avatar",
    "prompt": "A teenage girl, composed but slightly embarrassed, speaking a brief apology.",
    "resolution": "480P",
    "seed": 1002,
    "low_vram": true,
    "input_image": "uploads/projeto/personagem_a.png",
    "input_audio": "uploads/projeto/audio/c01_a_linha1.mp3"
  }
]
```

### Campos por tipo de task

| Campo | `reference_to_video` | `talking_avatar` | extensão |
|---|---|---|---|
| `label` | recomendado | recomendado | recomendado |
| `task_type` | obrigatório | obrigatório | obrigatório |
| `prompt` | obrigatório | obrigatório | obrigatório |
| `resolution` | `480P`/`540P`/`720P` | **`480P` ou `720P`** | `480P`/`540P`/`720P` |
| `duration` | obrigatório (segundos) | — (definido pelo áudio) | obrigatório |
| `seed` | opcional | opcional | opcional |
| `offload` | opcional | opcional | opcional |
| `low_vram` | opcional | **obrigatório** em < 24 GB | opcional |
| `ref_imgs` | obrigatório (1–4 caminhos) | — | — |
| `input_image` | — | obrigatório | — |
| `input_audio` | — | obrigatório | — |
| `input_video` | — | — | obrigatório |

> ⚠️ **Atenção:** caminhos em `ref_imgs` não podem conter vírgulas — a CLI usa vírgula como separador.

---

## Organização de Assets

```
uploads/
└── <projeto>/
    └── <episodio>/
        ├── cena01.png          # cenários / planos de estabelecimento
        ├── cena02.png
        ├── personagem_a.png    # retratos de personagens (reutilizados entre cenas)
        ├── personagem_b.png
        └── c01_a_linha1.mp3    # áudios (um por fala)

doc/
└── ep01_primeiro_dia.json      # exemplo: 59 cenas (21 r2v + 38 talking_avatar)
```

---

## Modos de Memória

| Modo | Flag | VRAM aprox. | Quando usar |
|---|---|---|---|
| Completo | _(nenhuma)_ | ~49 GB (14B) / ~38 GB (19B) | Multi-GPU de alto nível |
| Offload | `--offload` | ~20 GB (14B) | GPU única ≥ 20 GB |
| Low VRAM | `--low_vram` | ~12 GB (14B) / ~19 GB (19B) | GPU única < 24 GB |

Para Low VRAM, defina também:

```bash
export PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True"
```

### Notas sobre `talking_avatar` em Low VRAM

- Usar sempre `--low_vram` (quantização FP8 + block offload)
- Somente `480P` e `720P` são suportados (não `540P`)
- Tempo estimado: ~50 s/step × 4 steps × N chunks (~3 chunks para 5 s de vídeo)

---

## CLI — Referência rápida

```bash
python3 generate_video.py \
  --task_type reference_to_video \
  --ref_imgs "img1.png,img2.png" \
  --prompt "descrição do vídeo" \
  --resolution 540P \
  --duration 5 \
  --seed 42 \
  --offload
```

```bash
python3 generate_video.py \
  --task_type talking_avatar \
  --input_image personagem.png \
  --input_audio fala.mp3 \
  --resolution 480P \
  --seed 42 \
  --low_vram
```

Saída salva em `result/<task_type>/<seed>_<timestamp>.mp4`.
Para `talking_avatar`, também é gerado `<seed>_<timestamp>_with_audio.mp4` com o áudio mixado.

---

## Créditos

Baseado em [SkyReels V3](https://github.com/SkyworkAI/SkyReels-V3) da [Skywork AI](https://skywork.ai).
Agradecimentos aos projetos: [Wan 2.1](https://github.com/Wan-Video/Wan2.1) · [MultiTalk](https://github.com/MeiGen-AI/MultiTalk) · [xDiT](https://github.com/xdit-project/xDiT) · [diffusers](https://github.com/huggingface/diffusers).
