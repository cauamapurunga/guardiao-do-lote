"""Quem é quem no Telegram: cada pessoa registra o próprio chat com /sou <nome> e passa a receber só o que é dela.

O cadastro fica em contatos_telegram.json (fora do git). Sem ninguém cadastrado, tudo vai para o chat principal.
"""
from __future__ import annotations

import json
import threading
import unicodedata
from pathlib import Path

from .agentes import PESSOAS

ARQ = Path(__file__).resolve().parent.parent / "contatos_telegram.json"
_lock = threading.Lock()

# outros jeitos de a pessoa se chamar
APELIDOS = {
    "tesoureiro": "PS02", "tesouraria": "PS02", "diretora": "PS03", "diretoria": "PS03", "financeiro": "PS03",
    "compras": "PS05", "comprador": "PS04", "compradora": "PS04", "logistica": "PS07", "juridico": "PS08",
    "marketing": "PS06", "controller": "PS09", "facilities": "PS10", "ti": "PS11", "contas a pagar": "PS01", "cp": "PS01",
}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return " ".join(s.lower().split())


def nome(pid: str) -> str:
    return PESSOAS.get(pid, pid)


def primeiro(pid: str) -> str:
    return nome(pid).split("(")[0].strip().split(" ")[0]


def achar_pessoa(texto: str) -> str | None:
    t = _norm(texto)
    if not t:
        return None
    if t.upper() in PESSOAS:
        return t.upper()
    for pid, n in PESSOAS.items():
        completo = _norm(n.split("(")[0])
        if t == completo or t == completo.split(" ")[0]:
            return pid
    return APELIDOS.get(t)


def _ler() -> dict[str, str]:
    try:
        return json.loads(ARQ.read_text(encoding="utf-8"))
    except Exception:
        return {}


def registrar(chat: str, pid: str) -> None:
    with _lock:
        d = {p: c for p, c in _ler().items() if c != str(chat)}   # um chat é de uma pessoa só
        d[pid] = str(chat)
        ARQ.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def sair(chat: str) -> str | None:
    with _lock:
        d = _ler()
        pid = next((p for p, c in d.items() if c == str(chat)), None)
        if pid:
            del d[pid]
            ARQ.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        return pid


def pessoa_do_chat(chat) -> str | None:
    return next((p for p, c in _ler().items() if c == str(chat)), None)


def chat_da_pessoa(pid: str) -> str | None:
    return _ler().get(pid)


def cadastrados() -> dict[str, str]:
    return _ler()
