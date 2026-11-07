"""Carrega variáveis do arquivo .env (fora do git) sem dependência extra."""
import os
from pathlib import Path

_p = Path(__file__).resolve().parent.parent / ".env"
if _p.exists():
    for linha in _p.read_text().splitlines():
        if "=" in linha and not linha.strip().startswith("#"):
            k, v = linha.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
