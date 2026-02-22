#!/bin/bash
# Ativa o ambiente SkyReels V3
source /home/nmaldaner/projetos/SkyReels-V3/.venv/bin/activate
cd /home/nmaldaner/projetos/SkyReels-V3
echo "SkyReels V3 environment activated"
echo "Python: $(python --version)"
echo "PyTorch: $(python -c 'import torch; print(torch.__version__)')"
echo ""
echo "Exemplos de uso:"
echo "  python generate_video.py --task_type reference_to_video --ref_imgs img.png --prompt '...' --duration 5 --offload --seed 42"
echo "  python generate_video.py --task_type single_shot_extension --input_video video.mp4 --prompt '...' --duration 5 --offload --seed 42"
echo "  python generate_video.py --task_type talking_avatar --input_image img.jpg --input_audio audio.mp3 --prompt '...' --offload --seed 42"
