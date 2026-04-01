FROM pytorch/pytorch:2.1.0-cuda11.8-cudnn8-runtime

RUN apt-get update && apt-get install -y ffmpeg libsox-dev gcc && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Установка зависимостей напрямую (requirements.txt содержит fastapi uvicorn speechbrain torchaudio)
RUN pip install --no-cache-dir fastapi uvicorn python-multipart speechbrain torchaudio soundfile

# Предварительная загрузка модели SpeechBrain ( VoxCeleb ECAPA-TDNN)
RUN python -c "import os; os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = '1'; from speechbrain.inference.speaker import SpeakerRecognition; SpeakerRecognition.from_hparams(source='speechbrain/spkrec-ecapa-voxceleb', savedir='/app/pretrained_models')"

COPY app.py .

RUN mkdir -p /app/profiles

EXPOSE 8001

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001"]
