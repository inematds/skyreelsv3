# 🎬 StoryForge AI

Sistema de Criação Automatizada de Séries com IA

------------------------------------------------------------------------

# 📌 Visão Geral

StoryForge AI é uma plataforma que permite:

1.  Criar um projeto de série
2.  Gerar mundo, personagens e episódios automaticamente
3.  Editar e aprovar cada etapa
4.  Gerar roteiro
5.  Gerar imagens
6.  Gerar áudio
7.  Gerar música
8.  Gerar vídeo
9.  Fazer montagem final automática

Fluxo estruturado em 10 etapas.

------------------------------------------------------------------------

# 🏗️ Estrutura do Projeto

Cada projeto contém:

Projeto_X/ ├── 1_Descricao_Geral ├── 2_Mundo ├── 3_Personagens ├──
4_Arco_Temporada ├── 5_Lista_Episodios ├── 6_Episodio_Selecionado ├──
7_Roteiro_Aprovado ├── 8_Audio_Imagens ├── 9_Video_Cenas └──
10_Montagem_Final

------------------------------------------------------------------------

# 🔁 Fluxo de Execução (1 → 10)

## 1️⃣ Descrição Geral

Usuário escreve ideia base.

Sistema gera: - Tema - Gênero - Público-alvo - Tom narrativo -
Referências

Status possíveis: - draft - generated - edited - approved

------------------------------------------------------------------------

## 2️⃣ Mundo

Sistema gera: - Ano - Ambientação - Tecnologia - Regras do universo -
Conflitos globais

------------------------------------------------------------------------

## 3️⃣ Personagens

Sistema gera: - Protagonista - Antagonista - Secundários - Conflitos
internos - Motivação

Usuário pode editar e aprovar.

------------------------------------------------------------------------

## 4️⃣ Arco da Temporada

Sistema gera: - Conflito central - Mistério principal - Clímax - Final
da temporada

------------------------------------------------------------------------

## 5️⃣ Lista de Episódios

Sistema gera 5--10 episódios:

-   Ep 1 -- Título
-   Ep 2 -- Título
-   Ep 3 -- Título
-   ...

Usuário pode: - Criar novo - Reordenar - Apagar - Selecionar episódio

------------------------------------------------------------------------

## 6️⃣ Episódio Selecionado

Sistema gera: - Sinopse detalhada - Estrutura em 3 atos - Cliffhanger

Após aprovação → libera roteiro completo.

------------------------------------------------------------------------

## 7️⃣ Roteiro Completo

Formato profissional:

INT. LABORATÓRIO -- NOITE

CAEL: (voz baixa) --- Isso não é um eco.

Inclui: - Divisão por cenas - Descrição visual - Emoção - Movimentos de
câmera - Duração estimada

------------------------------------------------------------------------

## 8️⃣ Geração de Mídia

Para cada cena:

### 🎨 Imagem

-   Prompt estruturado
-   Estilo consistente
-   Seed fixa para personagens

### 🎙️ Áudio

-   Voz por personagem
-   Emoção ajustada
-   Sons ambiente

### 🎵 Música

-   Trilha cinematográfica
-   Loop base ou faixa completa

Arquivos organizados:

/assets/images/ /assets/audio/ /assets/music/ /assets/video/

------------------------------------------------------------------------

## 9️⃣ Geração de Vídeo

Processo: - Animar imagens - Sincronizar áudio - Inserir música -
Adicionar transições

Ferramentas possíveis: - FFmpeg - MoviePy - Runway API - Pika API

Saídas: - MP4 horizontal - MP4 vertical - Trailer automático

------------------------------------------------------------------------

## 🔟 Montagem Final

Sistema: - Junta cenas - Equaliza áudio - Aplica LUT cinematográfico -
Adiciona créditos - Exporta versão final

Status final: - rendered - final

------------------------------------------------------------------------

# 🧠 Arquitetura Técnica

## Backend

-   Python + FastAPI ou
-   Node.js + Express

## Banco de Dados

Inicial: - SQLite local

Produção: - Supabase (PostgreSQL)

------------------------------------------------------------------------

# 🗄️ Estrutura de Banco (Supabase)

## Tabela: projects

-   id (uuid)
-   user_id (uuid)
-   title (text)
-   description (text)
-   status (text)
-   created_at (timestamp)

------------------------------------------------------------------------

## Tabela: episodes

-   id (uuid)
-   project_id (uuid)
-   number (int)
-   title (text)
-   synopsis (text)
-   approved (boolean)

------------------------------------------------------------------------

## Tabela: scenes

-   id (uuid)
-   episode_id (uuid)
-   scene_number (int)
-   script (text)
-   image_prompt (text)
-   audio_status (text)
-   video_status (text)

------------------------------------------------------------------------

## Tabela: assets

-   id (uuid)
-   scene_id (uuid)
-   type (image/audio/video/music)
-   url (text)
-   status (text)

------------------------------------------------------------------------

# 🤖 APIs Integradas

## LLM (roteiro)

-   OpenAI
-   Anthropic
-   OpenRouter
-   Ollama (local)

## Imagem

-   Stable Diffusion API
-   Leonardo
-   OpenAI Images

## Áudio

-   ElevenLabs
-   OpenAI TTS
-   PlayHT

## Música

-   Suno
-   Udio
-   Stable Audio

## Vídeo

-   Runway
-   Pika
-   FFmpeg (local)

------------------------------------------------------------------------

# 🌐 Interface

## Web (principal)

-   Next.js
-   React
-   Tailwind

Menu lateral:

\[1\] Descrição \[2\] Mundo \[3\] Personagens \[4\] Arco \[5\] Episódios
\[6\] Episódio Atual \[7\] Roteiro \[8\] Mídia \[9\] Vídeo \[10\] Final

------------------------------------------------------------------------

## Telegram (extensão)

Permite: - Criar projeto - Aprovar etapas - Gerar novo episódio -
Receber vídeo final

------------------------------------------------------------------------

# 🔄 Sistema de Status

draft generated edited approved rendered final

Cada etapa só desbloqueia a próxima quando estiver `approved`.

------------------------------------------------------------------------

# 🚀 Roadmap de Desenvolvimento

## Fase 1

-   Backend
-   Banco
-   Geração de roteiro

## Fase 2

-   Imagem
-   Áudio

## Fase 3

-   Vídeo automático

## Fase 4

-   Plataforma SaaS completa

------------------------------------------------------------------------

# 🎯 Objetivo Final

Criar um:

🎬 Estúdio Automatizado de Séries com IA

Possibilidades: - SaaS - Ferramenta para criadores - Plataforma de anime
IA - Gerador de novelas IA - Sistema de produção automatizada

------------------------------------------------------------------------

# FIM DO DOCUMENTO
