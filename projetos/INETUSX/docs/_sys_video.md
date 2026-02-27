# Guia de Geração de Vídeo (SkyReels V3)

Este arquivo define as regras para geração de vídeos via SkyReels V3.
O campo `prompt` de cada cena usa estas diretrizes.

## Tasks disponíveis
- **reference_to_video**: gera vídeo a partir de 1–4 imagens de referência + prompt
- **single_shot_extension**: estende vídeo existente (5–30s)
- **shot_switching_extension**: estende com transição cinemática (máx. 5s)
- **talking_avatar**: avatar falante (retrato + áudio, até 200s)

## Regras do prompt de vídeo
- Escreva em INGLÊS
- Inclua: composição, iluminação, movimento de câmera, emoção, ação dos personagens
- Seja específico sobre direções (up/down/left/right) — o vídeo seguirá exatamente
- ⚠ COERÊNCIA: o prompt de vídeo DEVE descrever a mesma ação/direção que o audio_text

## Referências visuais (ref_imgs)
- MÁXIMO 4 imagens por cena
- Use SEMPRE a imagem do ambiente + imagem do personagem que aparece
- NUNCA duas imagens do mesmo personagem (duplica o personagem na cena)

## Exemplo de prompt
"Medium shot, Valen stands at school corridor, morning sunlight through windows,
she turns to look at Lumi, curious expression, soft camera pan right,
anime style, 2030 futuristic school, cinematic lighting"
