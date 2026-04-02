import os
import torch
import torchaudio
import tempfile
import uvicorn
import shutil
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from speechbrain.inference.speaker import EncoderClassifier
from scipy.spatial.distance import cosine
from typing import Dict

# Настройка устройства: используем CUDA если доступно, иначе CPU
# Для P104-100 и i5-2500K образ PyTorch 2.1.0-cuda11.8 должен быть стабилен
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Using device: {device}")

# Ограничение памяти GPU для предотвращения конфликтов с whisper (опционально)
if device == "cuda":
    torch.cuda.set_per_process_memory_fraction(0.1, 0) # Используем 10% VRAM одного GPU

app = FastAPI()
profiles_dir = 'profiles'
pretrained_dir = 'pretrained_models/spkrec-ecapa-voxceleb'

# Инициализация модели (ECAPA-TDNN)
verification = EncoderClassifier.from_hparams(
    source="speechbrain/spkrec-ecapa-voxceleb", 
    savedir=pretrained_dir,
    run_opts={"device": device}
)

profiles: Dict[str, torch.Tensor] = {}

def convert_to_16k(input_path, output_path):
    # Команда для конвертации в моно 16кГц (совместимо с raw и wav)
    os.system(f'ffmpeg -y -i {input_path} -ar 16000 -ac 1 {output_path} > /dev/null 2>&1')

def load_profiles():
    global profiles
    profiles = {}
    if not os.path.exists(profiles_dir):
        os.makedirs(profiles_dir)
    for f in os.listdir(profiles_dir):
        if f.endswith('.pt'):
            user_id = f[:-3]
            try:
                profiles[user_id] = torch.load(os.path.join(profiles_dir, f), map_location=device)
            except Exception as e:
                print(f'Error loading {f}: {e}')

load_profiles()

@app.post('/enroll')
async def enroll(user_id: str = Form(...), file: UploadFile = File(...)):
    tmp_in = tempfile.NamedTemporaryFile(delete=False, suffix='.raw').name
    tmp_out = tmp_in + '.wav'
    print(f"Enrolling user: {user_id}")
    try:
        with open(tmp_in, 'wb') as f:
            f.write(await file.read())
        convert_to_16k(tmp_in, tmp_out)
        
        waveform, sr = torchaudio.load(tmp_out)
        with torch.no_grad():
            embedding = verification.encode_batch(waveform.to(device))
        
        # Сохранение эмбеддинга
        torch.save(embedding, os.path.join(profiles_dir, f'{user_id}.pt'))
        profiles[user_id] = embedding
        
        return {'status': 'success', 'user_id': user_id}
    except Exception as e:
        print(f'Enroll error: {e}')
        raise HTTPException(500, str(e))
    finally:
        for p in (tmp_in, tmp_out):
            if os.path.exists(p): os.remove(p)

@app.post('/identify')
async def identify(file: UploadFile = File(...)):
    tmp_in = tempfile.NamedTemporaryFile(delete=False, suffix='.raw').name
    tmp_out = tmp_in + '.wav'
    try:
        with open(tmp_in, 'wb') as f:
            f.write(await file.read())
        convert_to_16k(tmp_in, tmp_out)
        
        waveform, sr = torchaudio.load(tmp_out)
        with torch.no_grad():
            emb1 = verification.encode_batch(waveform.to(device))
        
        results = []
        print('--- Speaker ID Comparison ---')
        for u, emb2 in profiles.items():
            # Косинусное сходство (1 - distance)
            score = 1 - cosine(emb1[0, 0].cpu().numpy(), emb2[0, 0].cpu().numpy())
            print(f'User: {u}, Score: {score:.4f}')
            results.append({'user_id': u, 'score': score})
        
        if not results:
            print('No profiles loaded.')
            return {'identified': 'Unknown', 'score': 0.0}
            
        results.sort(key=lambda x: x['score'], reverse=True)
        
        # Порог 0.30 для лучшей стабильности (снижен с 0.35)
        id_user = results[0]['user_id'] if results[0]['score'] > 0.30 else 'Unknown'
        print(f'Result: {id_user} (Score: {results[0]["score"]:.4f})')
        
        return {'identified': id_user, 'score': float(results[0]['score'])}
    except Exception as e:
        print(f'Identify error: {e}')
        raise HTTPException(500, str(e))
    finally:
        for p in (tmp_in, tmp_out):
            if os.path.exists(p): os.remove(p)

@app.get('/list')
async def list_users():
    return {'users': list(profiles.keys())}

@app.delete('/delete/{user_id}')
async def delete_user(user_id: str):
    path = os.path.join(profiles_dir, f'{user_id}.pt')
    if os.path.exists(path):
        os.remove(path)
        if user_id in profiles:
            del profiles[user_id]
        return {'status': 'deleted', 'user_id': user_id}
    raise HTTPException(404, 'User not found')

if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8001)
