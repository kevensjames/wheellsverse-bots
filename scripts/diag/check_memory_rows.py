"""Quick check: how many rows exist in each NarAI Chroma collection."""
import os
import chromadb

path = os.getenv("NARAI_CHROMA_PATH", "narai/data/chroma")
client = chromadb.PersistentClient(path=path)
for name in ["narai_memory", "narai_episodes", "narai_rag"]:
    try:
        col = client.get_collection(name)
        print(f"{name}: {col.count()} rows")
    except Exception as e:
        print(f"{name}: missing ({e.__class__.__name__})")
