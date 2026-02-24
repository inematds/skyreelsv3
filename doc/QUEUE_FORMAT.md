# Formato da Fila de Geração — SkyReels V3

A fila aceita dois formatos: **JSON** e **Markdown**. O arquivo pode ser
importado pela interface web (botão "↑ Importar" na aba Fila) ou enviado
diretamente ao endpoint `/queue/import`.

---

## Formato JSON

Um array de objetos. Cada objeto representa um job de geração.

```json
[
  {
    "task_type": "reference_to_video",
    "prompt": "Uma mulher caminhando em um jardim japonês ao entardecer.",
    "resolution": "540P",
    "duration": 5,
    "seed": 42,
    "offload": true,
    "low_vram": false,
    "ref_imgs": ["uploads/personagem.jpg", "uploads/fundo.png"],
    "label": "Cena jardim - personagem A"
  },
  {
    "task_type": "single_shot_extension",
    "prompt": "A câmera avança lentamente pelo corredor.",
    "resolution": "720P",
    "duration": 10,
    "seed": 100,
    "offload": true,
    "input_video": "result/reference_to_video/42_2026-02-22_06-22-44.mp4"
  },
  {
    "task_type": "shot_switching_extension",
    "prompt": "[ZOOM_IN_CUT] Close-up no rosto da personagem.",
    "resolution": "540P",
    "duration": 5,
    "seed": 7,
    "offload": true,
    "input_video": "uploads/cena_base.mp4"
  },
  {
    "task_type": "talking_avatar",
    "prompt": "Uma apresentadora de notícias falando com confiança.",
    "resolution": "480P",
    "seed": 99,
    "low_vram": true,
    "input_image": "uploads/retrato.jpg",
    "input_audio": "uploads/locucao.mp3",
    "label": "Avatar notícias - EP01"
  }
]
```

### Campos por task_type

| Campo | Tipo | Obrigatório em | Descrição |
|---|---|---|---|
| `task_type` | string | todos | `reference_to_video`, `single_shot_extension`, `shot_switching_extension`, `talking_avatar` |
| `prompt` | string | todos | Descrição do vídeo a gerar |
| `resolution` | string | todos | `480P`, `540P`, `720P`. talking_avatar só aceita 480P e 720P |
| `duration` | int | todos exceto talking_avatar | Duração em segundos. talking_avatar ignora (usa o áudio) |
| `seed` | int | todos | Semente de reprodutibilidade |
| `offload` | bool | todos | Move modelos para CPU entre passes (reduz VRAM) |
| `low_vram` | bool | talking_avatar (obrigatório) | FP8 + block offload. Obrigatório para o modelo 19B |
| `ref_imgs` | array de strings | reference_to_video | Caminhos locais de 1–4 imagens de referência |
| `input_video` | string | single/shot_extension | Caminho ou URL do vídeo a estender |
| `input_image` | string | talking_avatar | Caminho ou URL da imagem do retrato |
| `input_audio` | string | talking_avatar | Caminho ou URL do áudio (mp3, wav, m4a, mp4, mov…) |
| `label` | string | opcional | Nome amigável exibido na lista da fila |

---

## Formato Markdown

Cada job é uma seção `##`. Os campos são linhas `- chave: valor`.

```markdown
# SkyReels Queue

## Cena jardim - personagem A
- task_type: reference_to_video
- prompt: Uma mulher caminhando em um jardim japonês ao entardecer.
- resolution: 540P
- duration: 5
- seed: 42
- offload: true
- ref_imgs: uploads/personagem.jpg, uploads/fundo.png

## Extensão corredor
- task_type: single_shot_extension
- prompt: A câmera avança lentamente pelo corredor.
- resolution: 720P
- duration: 10
- seed: 100
- offload: true
- input_video: result/reference_to_video/42_2026-02-22_06-22-44.mp4

## Transição close-up
- task_type: shot_switching_extension
- prompt: [ZOOM_IN_CUT] Close-up no rosto da personagem.
- resolution: 540P
- duration: 5
- seed: 7
- offload: true
- input_video: uploads/cena_base.mp4

## Avatar notícias - EP01
- task_type: talking_avatar
- prompt: Uma apresentadora de notícias falando com confiança.
- resolution: 480P
- seed: 99
- low_vram: true
- input_image: uploads/retrato.jpg
- input_audio: uploads/locucao.mp3
```

### Tipos de valor no Markdown

| Tipo | Exemplo |
|---|---|
| String | `- prompt: Texto livre aqui` |
| Inteiro | `- duration: 5` ou `- seed: 42` |
| Booleano | `- offload: true` (aceita `true`, `false`, `yes`, `no`, `1`, `0`, `sim`) |
| Lista | `- ref_imgs: img1.jpg, img2.png, img3.jpg` (separado por vírgulas) |

---

## Regras e limites por task_type

| Tarefa | Duração | Resolução | Nota |
|---|---|---|---|
| `reference_to_video` | 1–30 s, recomendado 5 s | 480P / 540P / 720P | 1–4 imagens ref |
| `single_shot_extension` | 5–30 s | 480P / 540P / 720P | Vídeo de entrada obrigatório |
| `shot_switching_extension` | máx 5 s | 480P / 540P / 720P | Prefixo no prompt obrigatório |
| `talking_avatar` | ignorado (= duração do áudio, máx 200 s) | 480P / 720P | `low_vram: true` obrigatório |

### Prefixos para shot_switching_extension

```
[ZOOM_IN_CUT]     — aproximação de câmera
[ZOOM_OUT_CUT]    — afastamento de câmera
[STATIC_CUT]      — corte simples, câmera estática
[PAN_LEFT_CUT]    — panorâmica para a esquerda
[PAN_RIGHT_CUT]   — panorâmica para a direita
```

---

## Notas sobre caminhos de arquivos

- Caminhos são relativos à **raiz do projeto** (`SkyReels-V3/`)
- Arquivos enviados pela interface web ficam em `uploads/`
- Resultados anteriores ficam em `result/<task_type>/`
- URLs públicas (http/https) também são aceitas — o sistema baixa automaticamente

### Exemplos de caminhos válidos

```
uploads/minha_foto.jpg
result/reference_to_video/42_2026-02-22_06-22-44.mp4
https://exemplo.com/audio.mp3
/caminho/absoluto/no/servidor.png
```
