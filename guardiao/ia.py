"""Cliente do AI Proxy do evento (https://ai-proxy.gogroupbr.com/v1).

- Jev (/v1/systemone): decisões tipadas (classificar, sim/não) — usado pelo Leitor da Caixa.
- Chat (/v1/chat/completions): texto — usado para explicar casos ao aprovador.
Cada chamada registra o custo (linha 💲) e o acumulado da sessão. O token vem de AI_PROXY_API_KEY (.env, fora do git).
DeepSeek não é usado (regra do evento).
"""
from __future__ import annotations

import os
import threading
import time

import requests

BASE = "https://ai-proxy.gogroupbr.com/v1"
MODELO_CHAT = "latest"

_lock = threading.Lock()
USO = {"chamadas": 0, "chat_tokens": 0, "jev_tokens": 0, "usd": 0.0, "linhas": []}


def chave() -> str | None:
    k = os.getenv("AI_PROXY_API_KEY")
    if k:
        return k
    try:
        import streamlit as st
        return st.secrets.get("AI_PROXY_API_KEY")
    except Exception:
        return None


def disponivel() -> bool:
    return bool(chave())


def _registrar(linha: str, chat_tok: int = 0, jev_tok: int = 0, usd: float = 0.0):
    with _lock:
        USO["chamadas"] += 1
        USO["chat_tokens"] += chat_tok
        USO["jev_tokens"] += jev_tok
        USO["usd"] += usd
        tok = f"{USO['chat_tokens'] + USO['jev_tokens']:,}".replace(",", ".")
        sessao = f"sessão: {USO['chamadas']} chamadas, {tok} tok · US$ {USO['usd']:.7f}"
        USO["linhas"].append(f"{linha} | {sessao}")
        USO["linhas"] = USO["linhas"][-200:]
        print(f"{linha} | {sessao}", flush=True)


def _post(caminho: str, body: dict, timeout: int = 60, tentativas: int = 4) -> requests.Response:
    hdr = {"Authorization": f"Bearer {chave()}", "Content-Type": "application/json"}
    for i in range(tentativas):
        r = requests.post(f"{BASE}{caminho}", json=body, headers=hdr, timeout=timeout)
        if r.status_code in (429, 503, 502) and i < tentativas - 1:
            espera = float(r.headers.get("x-ratelimit-reset", 2 ** i) or 2 ** i)
            time.sleep(min(espera, 20))
            continue
        r.raise_for_status()
        return r
    r.raise_for_status()
    return r


def jev(state, questions: dict) -> dict:
    """Decisão estruturada. Retorna o JSON com 'answers'."""
    r = _post("/systemone", {"state": state, "questions": questions}, timeout=30)
    j = r.json()
    u = j.get("usage", {}) or {}
    usd = float(u.get("estimated_cost_usd") or r.headers.get("x-estimated-cost-usd") or 0)
    tok = int(u.get("input_tokens", 0))
    _registrar(f"💲 {j.get('model', 'jev')} · entrada {tok} tok · US$ {usd:.7f}", jev_tok=tok, usd=usd)
    return j


def chat(prompt: str, modelo: str = MODELO_CHAT, sistema: str | None = None, max_tokens: int | None = None) -> str:
    msgs = ([{"role": "system", "content": sistema}] if sistema else []) + [{"role": "user", "content": prompt}]
    body = {"model": modelo, "messages": msgs}
    if max_tokens:
        body["max_tokens"] = max_tokens
    r = _post("/chat/completions", body, timeout=90)
    j = r.json()
    u = j.get("usage", {}) or {}
    pt, ct = int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0))
    rt = (u.get("completion_tokens_details") or {}).get("reasoning_tokens")
    servido = r.headers.get("x-model-served") or j.get("model", modelo)
    _registrar(f"💲 {servido} · entrada {pt} tok · saída {ct} tok{f' (raciocínio {rt})' if rt else ''} · sem preço por chamada",
               chat_tok=pt + ct)
    return j["choices"][0]["message"]["content"]


def resumo_uso() -> str:
    ct = f"{USO['chat_tokens']:,}".replace(",", ".")
    jt = f"{USO['jev_tokens']:,}".replace(",", ".")
    return f"{USO['chamadas']} chamadas · chat {ct} tok · Jev {jt} tok (US$ {USO['usd']:.6f})"
