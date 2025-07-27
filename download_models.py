# download_models.py

from sentence_transformers import SentenceTransformer
from transformers import pipeline

# --- Constants from the main script ---
RETRIEVER_MODEL = 'sentence-transformers/all-MiniLM-L6-v2'
REASONING_MODEL = 't5-small'

def download_and_cache_models():
    """
    Downloads and caches the specified models to the default
    Hugging Face cache directory.
    """
    print(f"Downloading and caching retriever model: {RETRIEVER_MODEL}...")
    SentenceTransformer(RETRIEVER_MODEL)
    print("Retriever model cached.")

    print(f"Downloading and caching reasoner model: {REASONING_MODEL}...")
    pipeline('text2text-generation', model=REASONING_MODEL)
    print("Reasoner model cached.")

    print("\nAll models have been downloaded and cached successfully.")

if __name__ == '__main__':
    download_and_cache_models()