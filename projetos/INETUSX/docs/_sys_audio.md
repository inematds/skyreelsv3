# Guia de Geração de Áudio (ElevenLabs TTS)

Este arquivo define as regras para geração de áudio via ElevenLabs TTS.
O campo `audio_text` de cada cena usa estas diretrizes.

## Idioma
- PORTUGUÊS BRASILEIRO exclusivamente

## Tom e estilo
- Narração: terceira pessoa, tempo presente, tom cinemático e envolvente
- Diálogos: primeira pessoa, tom natural e expressivo para cada personagem
- Mantenha a personalidade definida nos documentos do projeto

## Regras
- Inclua APENAS o que será falado ou narrado — sem descrições de cena
- Se a cena for silenciosa ou apenas musical, use string vazia: ""
- Duração do áudio determina a duração do vídeo — escreva com ritmo adequado à cena
- Evite texto muito longo que não couça no tempo de duração da cena (~5s ≈ 2-3 frases curtas)

## Casting de vozes
Definido na tabela de personagens nos documentos do projeto (campo voice_id).
