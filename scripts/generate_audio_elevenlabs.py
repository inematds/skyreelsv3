"""
Gera os 38 arquivos de áudio do Episódio "Primeiro Dia" via ElevenLabs API.

Uso:
    pip install elevenlabs
    python scripts/generate_audio_elevenlabs.py

Configure as variáveis ELEVENLABS_API_KEY e VOICES antes de rodar.
"""

import os
from pathlib import Path

# ─────────────────────────────────────────────
#  CONFIGURAÇÃO — preencha antes de rodar
# ─────────────────────────────────────────────

ELEVENLABS_API_KEY = "sk-..."   # sua chave da API ElevenLabs

# Voice IDs dos personagens.
# Para obter: ElevenLabs → Voices → clique na voz → botão "ID"
VOICES = {
    "valen": "VOICE_ID_VALEN",   # ex: "21m00Tcm4TlvDq8ikWAM"
    "lumi":  "VOICE_ID_LUMI",
    "maya":  "VOICE_ID_MAYA",
    "caio":  "VOICE_ID_CAIO",
}

# Modelo de voz — eleven_multilingual_v2 é o melhor para português
MODEL = "eleven_multilingual_v2"

# Configurações de voz (opcionais — ajuste por personagem se quiser)
VOICE_SETTINGS = {
    "stability":         0.50,   # 0.0–1.0: mais baixo = mais expressivo
    "similarity_boost":  0.75,   # 0.0–1.0: fidelidade à voz original
    "style":             0.20,   # 0.0–1.0: expressividade de estilo
    "use_speaker_boost": True,
}

# ─────────────────────────────────────────────
#  FALAS — 38 linhas
#  formato: (cena, personagem, número, texto)
# ─────────────────────────────────────────────

LINES = [
    # Cena 1 — Corredor
    ("c01", "valen", "01", "Foi mal."),
    ("c01", "lumi",  "01", "Tudo bem… eu que estava parada no meio."),
    ("c01", "valen", "02", "Primeiro dia?"),
    ("c01", "lumi",  "02", "Dá pra perceber, né?"),

    # Cena 2 — Mesa
    ("c02", "lumi",  "01", "Você já entendeu essa parte?"),
    ("c02", "valen", "01", "Quase. Acho que é mais simples do que parece."),
    ("c02", "lumi",  "02", "Ou mais complicado."),
    ("c02", "valen", "02", "Espero que não."),

    # Cena 3 — Fila do Lanche
    ("c03", "lumi",  "01", "Você desenhou isso agora?"),
    ("c03", "maya",  "01", "Sim… eu gosto de desenhar enquanto espero."),
    ("c03", "valen", "01", "É um cachorro-robô?"),
    ("c03", "maya",  "02", "É. Ele parece abandonado… mas não devia estar."),

    # Cena 4 — Lugar Vago
    ("c04", "caio",  "01", "Está ocupado?"),
    ("c04", "maya",  "01", "Não."),
    ("c04", "lumi",  "01", "Você já mexeu nesse sistema antes?"),
    ("c04", "caio",  "02", "Um pouco… ele é mais intuitivo do que parece."),

    # Cena 5 — Troca de Caneta
    ("c05", "maya",  "01", "Acho que esqueci minha caneta…"),
    ("c05", "valen", "01", "Pode usar essa."),
    ("c05", "maya",  "02", "Sério?"),
    ("c05", "valen", "02", "Depois você me devolve."),

    # Cena 6 — Risada
    ("c06", "caio",  "01", "Você ouviu isso também, né?"),
    ("c06", "maya",  "01", "Eu tentei não rir."),
    ("c06", "valen", "01", "Falhou miseravelmente."),

    # Cena 7 — Biblioteca
    ("c07", "maya",  "01", "Vocês também vão pra biblioteca?"),
    ("c07", "caio",  "01", "Preciso terminar a atividade."),
    ("c07", "lumi",  "01", "Eu queria ver os livros digitais novos."),
    ("c07", "valen", "01", "Então vamos juntos."),

    # Cena 8 — Grupos
    ("c08", "valen", "01", "Já somos quatro."),
    ("c08", "caio",  "01", "Facilita bastante."),
    ("c08", "maya",  "01", "Melhor do que procurar pela sala inteira."),

    # Cena 9 — Chuva
    ("c09", "maya",  "01", "Eu gosto do som da chuva."),
    ("c09", "caio",  "01", "A previsão não falava nisso."),
    ("c09", "lumi",  "01", "Às vezes a previsão erra."),
    ("c09", "valen", "01", "Melhor esperar juntos."),

    # Cena 10 — Saída
    ("c10", "lumi",  "01", "Foi um dia legal."),
    ("c10", "caio",  "01", "Foi mesmo."),
    ("c10", "maya",  "01", "Não foi tão assustador quanto eu achei que seria."),
    ("c10", "valen", "01", "A gente sobreviveu ao primeiro dia. Já é um começo."),
]

# ─────────────────────────────────────────────
#  GERAÇÃO
# ─────────────────────────────────────────────

def main():
    from elevenlabs import ElevenLabs
    from elevenlabs.types import VoiceSettings

    client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

    out_dir = Path(__file__).parent.parent / "uploads" / "audio"
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(LINES)
    ok = 0
    skip = 0

    for i, (scene, char, num, text) in enumerate(LINES, 1):
        filename = out_dir / f"{scene}_{char}_{num}.mp3"

        if filename.exists():
            print(f"[{i:02d}/{total}] SKIP  {filename.name}  (já existe)")
            skip += 1
            continue

        voice_id = VOICES.get(char)
        if not voice_id or voice_id.startswith("VOICE_ID_"):
            print(f"[{i:02d}/{total}] ERRO  {char}: voice ID não configurado")
            continue

        print(f"[{i:02d}/{total}] GEN   {filename.name}  → \"{text}\"")

        try:
            audio = client.text_to_speech.convert(
                voice_id=voice_id,
                text=text,
                model_id=MODEL,
                voice_settings=VoiceSettings(**VOICE_SETTINGS),
                output_format="mp3_44100_128",
            )
            with open(filename, "wb") as f:
                for chunk in audio:
                    f.write(chunk)
            ok += 1
            print(f"           salvo: {filename}")
        except Exception as e:
            print(f"           FALHA: {e}")

    print(f"\nPronto: {ok} gerados, {skip} pulados, {total - ok - skip} com erro.")
    print(f"Arquivos em: {out_dir}")


if __name__ == "__main__":
    main()
