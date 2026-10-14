"""Run explicitly once with Internet access; application itself remains offline."""
from pathlib import Path
from huggingface_hub import snapshot_download

if __name__=='__main__':
    destination=Path(__file__).resolve().parent/'models'/'Qwen3-VL-4B-Instruct'
    snapshot_download(repo_id='Qwen/Qwen3-VL-4B-Instruct',local_dir=str(destination))
    print(f'Веса сохранены: {destination}')
