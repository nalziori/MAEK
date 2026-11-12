#!/bin/bash
set -euo pipefail
cd /workspace/exp
PY=/venv/main/bin/python
$PY -c "import torch;print('torch',torch.__version__,torch.cuda.is_available())"
uv pip install -q --python $PY ultralytics scipy pandas pyyaml matplotlib
[ -d MAEK ] || GIT_LFS_SKIP_SMUDGE=1 git clone -q --depth 1 https://github.com/nalziori/MAEK.git
b=https://github.com/nalziori/MAEK/releases/download
curl -fsSL $b/e4-20261109/best.pt -o w/e4.pt
curl -fsSL $b/models-20261110/sim_pipe_yolov8s_640_S.pt -o w/sim_S.pt
curl -fsSL $b/models-20261110/pv_yolov8s_640_A.pt -o w/pv_A.pt
curl -fsSL https://ndownloader.figshare.com/files/31729733 -o data/vt.zip
curl -fsSL "https://zenodo.org/api/records/11235637/files/corrosion-in-industrial-complexes-in-ostrava.zip/content" -o data/ostrava.zip
cd data && md5sum vt.zip ostrava.zip && sha256sum ../w/*.pt
mkdir -p vt ostrava rf && unzip -q -o vt.zip -d vt && unzip -q -o ostrava.zip -d ostrava && unzip -q -o /workspace/thermal-leak-detection-acteabot.v1i.yolov8.zip -d rf
echo SETUP_DONE
