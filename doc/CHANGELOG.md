# INEMA SkyReels V3 — Changelog da Web UI

Convenção de versão: **Major.Recursos.Correções**
- **Major** = versão principal do projeto (fixo em 3)
- **Recursos** = número acumulado de funcionalidades adicionadas
- **Correções** = número acumulado de correções aplicadas

---

## 3.49.19 — 2026-04-22

### Recursos (fase 0 — integração imkt4 / orquestração externa)
- **`GET /health` estruturado** — retorna `{status: ready|busy, queue_depth,
  gpu_free_gb, version, uptime_s}`. Permite que orquestradores (imkt4, etc.)
  detectem disponibilidade do worker sem abrir o SSE de `/stream`.
- **Webhook callback ao final da fila** — `POST /nqueues/<id>/run?callback_url=...`
  registra URL; quando a fila termina (done ou error), POSTa payload JSON
  `{queue_id, queue_name, project, status, duration_s, output_videos[],
  failed_jobs[]}` no callback. Retry 3× com backoff exponencial (1s, 2s, 4s)
  em timeout / 5xx; 4xx não é retry-able. Callback_url também aceito em
  `resume-from-error`. Fields ephemeral (prefixados com `_`) não são
  persistidos em `queues.json`.
- **`POST /nqueues/<id>/resume-from-error`** — retoma a fila pulando jobs
  com status=error. `{{prev}}` passa a andar para trás até achar o último
  job com `output_video` setado (ignora erros). Recusa com erro claro se
  o primeiro job falhou sem nenhuma cena `done` anterior.
- **Namespacing por projeto** — quando a fila tem `project` setado, vídeos
  renderizados são movidos para `result/<project>/<task_type>/` e
  `finalize` grava em `result/<project>/finalized/`. Filas sem `project`
  mantêm o layout atual (`result/<task_type>/...`) — retrocompat.
- **Input sidecar por cena** — ao lado de `<seed>_<ts>.mp4` agora também
  é salvo `<seed>_<ts>.input.json` com o payload original do job (antes da
  resolução de `{{prev}}`/`{{job:N}}`), permitindo auditoria e re-render
  determinístico.

---

## 3.8.3 — 2026-02-24

### Correções
- **OOM em tarefas de extensão sem flash_attn** — tarefas `single_shot_extension` e
  `shot_switching_extension` falhavam com kill silencioso no step 0 em hardware ARM64
  (sem `flash_attn`). Root cause: atenção O(n²) com 471K tokens a 720P excedia RAM.
  Solução: definir `low_vram: true` nessas tarefas ativa o block-level offload durante
  o denoising + FP8 quantization + `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`.
  Atualizado em: `queues.json`, `uploads/fila1/exemplo_10_cenas.json`,
  `doc/exemplo_10_cenas.json`.

---

## 3.8.2 — 2026-02-24

### Recursos
- **Banner de execução na aba Fila** — ao rodar uma fila, um banner roxo aparece no topo
  da aba Fila mostrando nome da fila, cena atual e botão "→ Ver" para abrir o detalhe.
- **Persistência de filas** — filas nomeadas são salvas em `uploads/queues.json` e
  recarregadas ao reiniciar o servidor. Jobs interrompidos voltam para `idle`.
- **Resolução automática de referências entre cenas** — campos `input_video`, `input_image`
  e `input_audio` suportam referências ao output de cenas anteriores da mesma fila:
  - `{{prev}}` → output da cena imediatamente anterior
  - `{{job:N}}` → output da cena no índice N (base 0)
  - `result/<task>/<seed>_<timestamp>.mp4` → resolve pelo seed (compatível com JSONs legados)

### Correções
- **Cadeado global entre abas** — `updatePrivacyBtn()` agora sincroniza os botões 🔒
  de todas as abas (Vídeos e Galeria) ao mesmo tempo.
- **Sincronização do cadeado por card** — ao travar/destravar um vídeo em qualquer aba,
  todos os cards com o mesmo `data-path` no DOM são atualizados imediatamente.

---

## 3.5.0 — 2026-02-24

### Recursos
- **Sistema de filas nomeadas** (Named Queues) — aba Fila redesenhada:
  - Lista de filas com nome, status, contagem de cenas e barra de progresso
  - Visão de detalhe com todas as cenas, status individual e player de vídeo inline
  - Execução da fila completa (todas as cenas pendentes em sequência)
  - Execução de cena individual
  - Serialização: fila B aguarda fila A terminar completamente
  - Importação de `.json` ou `.md` como nova fila
  - Exclusão de fila (com confirmação implícita; bloqueada se em execução)
  - Botão **Finalizar Vídeo** (desabilitado — previsto com ffmpeg)
- **Painel de progresso integrado à fila** — `nq-progress-info` exibe
  "Cena N/Total — Label" durante execução via SSE
- **Galeria de Vídeos** (aba dedicada) — grade responsiva com todos os vídeos gerados,
  controles de layout (lista/grade) e cadeado de privacidade
- **Página de Ajuda** (`/help`) — documentação completa do formato de fila JSON e Markdown,
  exemplos de referência entre cenas, notas de uso
- **Exemplos de fila** — `doc/exemplo_10_cenas.json` (10 cenas cinematográficas encadeadas)
  e `doc/exemplo_roteiro.json`; 13 imagens de referência renomeadas descritivamente em
  `uploads/fila1/`

---

## 1.2.0 → 3.5.0 — (rebaseado para versão 3)

Renumeração da versão major de 1 para 3 para refletir o projeto base (SkyReels V3).

---

## 1.2.0 — 2026-02-23

### Recursos
- **Controle de posição da galeria** — botões para galeria à esquerda, direita, cima e baixo
  dentro da aba Vídeos
- **Cadeado de privacidade** — oculta thumbnails e players de vídeo com máscara 🔒,
  persistido em `localStorage`
- **Download de documentos** — endpoint `/doc/download/<filename>` para baixar arquivos
  do diretório `doc/`
- **Link `? Ajuda`** na aba Fila aponta para `/help` (página renderizada), não mais para
  o markdown bruto

### Correções
- Rota `/help` ausente — adicionada
- Link "? Ajuda" apontava para `/doc/QUEUE_FORMAT.md` (texto bruto) — corrigido para `/help`

---

## 1.0.0 — 2026-02-22 (primeira versão da Web UI)

### Recursos
- **Web UI completa** (`webui/app.py` + `webui/templates/index.html`):
  - Aba **Progresso** — log em tempo real via SSE, barra de progresso, controles de geração
  - Aba **Vídeos** — galeria inline com player de vídeo e detalhes de geração (metadados JSON)
  - Formulário de geração com todos os parâmetros: task_type, prompt, resolução, duração,
    seed, offload, low_vram, ref_imgs, input_video, input_image, input_audio
  - Fila de geração simples (jobs em sequência, uma GPU)
- **Geração concluída**: `reference_to_video` 720P, 5s, seed 42 — OK (~18 min, ~66 GB RAM)
- **Infraestrutura**: `.venv/` Python 3.12, PyTorch 2.10+cu130, sem flash_attn (ARM64 fallback)
- **Scripts**: `ativar.sh`, `CLAUDE.md`, `doc/ANALISE_E_PLANO.md`

---

## Arquitetura da Web UI

```
webui/
  app.py                  # Flask: rotas, fila, SSE, named queues, persistência
  templates/
    index.html            # SPA: abas Progresso / Vídeos / Galeria / Fila
    help.html             # Documentação do formato de fila

uploads/
  queues.json             # Persistência das filas nomeadas (gerado automaticamente)
  fila1/                  # Imagens de referência para exemplo de 10 cenas

doc/
  QUEUE_FORMAT.md         # Formato detalhado do JSON/MD de fila
  CHANGELOG.md            # Este arquivo
  ANALISE_E_PLANO.md      # Análise de hardware e plano de execução
  exemplo_10_cenas.json   # JSON de exemplo com 10 cenas cinematográficas
  exemplo_roteiro.json    # JSON de exemplo de roteiro
```

## Endpoints da API

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/` | Interface principal |
| GET | `/help` | Página de ajuda |
| GET | `/status` | Estado atual da geração (JSON) |
| GET | `/stream` | SSE — log de progresso em tempo real |
| POST | `/generate` | Iniciar geração avulsa |
| POST | `/cancel` | Cancelar geração em andamento |
| GET | `/videos` | Lista de vídeos gerados |
| GET | `/video/<path>` | Servir arquivo de vídeo |
| GET | `/video-meta/<path>` | Metadados JSON do vídeo |
| GET | `/queue` | Lista flat de jobs (legado) |
| POST | `/queue` | Adicionar job avulso |
| DELETE | `/queue/<id>` | Remover job |
| GET | `/nqueues` | Listar filas nomeadas |
| POST | `/nqueues` | Criar nova fila |
| POST | `/nqueues/import` | Importar fila de arquivo |
| GET | `/nqueues/<id>` | Detalhe de uma fila |
| DELETE | `/nqueues/<id>` | Excluir fila |
| POST | `/nqueues/<id>/run` | Executar fila completa |
| POST | `/nqueues/<id>/jobs/<jid>/run` | Executar cena individual |
| POST | `/nqueues/<id>/finalize` | Finalizar vídeo (501 — previsto) |
| GET | `/doc/<path>` | Servir arquivo de doc |
| GET | `/doc/download/<path>` | Download de arquivo de doc |

## Sintaxe de referência entre cenas (Named Queue)

```json
{ "input_video": "{{prev}}" }           // cena imediatamente anterior
{ "input_video": "{{job:0}}" }          // cena no índice 0 (base 0)
{ "input_video": "{{job:3}}" }          // cena no índice 3
{ "input_video": "result/reference_to_video/1001_<timestamp>.mp4" }  // legado (resolve por seed)
```
