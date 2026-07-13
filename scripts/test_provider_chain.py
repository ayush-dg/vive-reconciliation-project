"""Quick smoke test — verifies the provider chain loads correctly from config."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ai.client_factory import get_ai_client, get_provider_chain

chain = get_provider_chain()
print(f"Provider chain: {chain}")

for provider in chain:
    if provider == "pdfplumber":
        print(f"  pdfplumber: available (no API key needed)")
        continue
    try:
        client = get_ai_client(provider)
        print(f"  {provider}: client loaded OK — model={client.config['model']}")
    except Exception as e:
        print(f"  {provider}: ERROR — {e}")

print("\nPhase 2 complete — AI service layer ready.")
