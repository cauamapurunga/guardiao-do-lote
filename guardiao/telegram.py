"""Canal humano: o agente levanta a mão no Telegram (aprovar/recusar com um toque)."""
from __future__ import annotations

import json
import os

import requests
from .dados import brl2

API = "https://api.telegram.org/bot{token}/{metodo}"


def _cfg(chave: str) -> str | None:
    v = os.getenv(chave)
    if v:
        return v
    try:
        import streamlit as st
        return st.secrets.get(chave)
    except Exception:
        return None


def token() -> str | None:
    return _cfg("TELEGRAM_TOKEN")


def chat_id() -> str | None:
    return _cfg("TELEGRAM_CHAT_ID")


def _call(metodo: str, **params):
    tk = token()
    if not tk:
        raise RuntimeError("TELEGRAM_TOKEN não configurado")
    espera = int(params.get("timeout", 0)) + 15          # long polling: o HTTP espera mais que o Telegram
    try:
        r = requests.post(API.format(token=tk, metodo=metodo), json=params, timeout=espera)
    except requests.RequestException as e:
        raise ConnectionError(f"sem resposta do Telegram ({type(e).__name__})") from None   # nunca mostra a URL com o token
    if r.status_code == 409:
        raise ConnectionError("outro programa já está lendo este bot (feche o bot.py antigo; o servidor.py já liga o bot)")
    if not r.ok:
        raise ConnectionError(f"Telegram respondeu {r.status_code}: {r.json().get('description', '')}")
    return r.json()


def descobrir_chat_id() -> str | None:
    """Pega o chat de quem mandou a última mensagem para o bot."""
    res = _call("getUpdates").get("result", [])
    for u in reversed(res):
        msg = u.get("message") or u.get("callback_query", {}).get("message")
        if msg:
            return str(msg["chat"]["id"])
    return None


def enviar(texto: str, chat: str | None = None, botoes: list[list[dict]] | None = None):
    params = {"chat_id": chat or chat_id(), "text": texto, "parse_mode": "HTML", "disable_web_page_preview": True}
    if botoes:
        params["reply_markup"] = {"inline_keyboard": botoes}
    return _call("sendMessage", **params)


def pedir_aprovacao(caso: dict, chat: str | None = None, explicacao: str | None = None):
    ap = caso["aprovacao"]
    ev = "\n".join(f"• {e}" for e in caso["evidencias"][:5])
    texto = (f"🖐️ <b>Guardião do Lote precisa de você</b>\n"
             f"<b>Para:</b> {ap['nome']}{' (aprovação dupla)' if ap.get('dupla') else ''}\n\n"
             f"<b>{caso['resumo']}</b>\n"
             f"Título {caso['titulo_id']} · {caso['fornecedor']} · {brl2(caso['valor'])}\n"
             f"Lote {caso['lote']} fecha {caso['fechamento']}\n\n"
             f"<b>Evidências</b>\n{ev}\n\n"
             f"<b>Ação proposta:</b> {ap['acao']}\n<i>{ap['motivo']}</i>"
             + (f"\n\n🧠 <b>Resumo do agente</b>\n{explicacao}" if explicacao else ""))
    botoes = [[{"text": "✅ Aprovar", "callback_data": f"ap:{caso['id']}"},
               {"text": "❌ Recusar", "callback_data": f"rc:{caso['id']}"}]]
    return enviar(texto, chat, botoes)


def avisar(caso: dict, pessoa: str, motivo: str, chat: str | None = None):
    texto = (f"🔔 <b>Acionamento:</b> {pessoa}\n<b>{caso['resumo']}</b>\n"
             f"Título {caso['titulo_id']} · {caso['fornecedor']} · {brl2(caso['valor'])}\n"
             f"Motivo: {motivo}\n\nO agente já agiu no que estava na alçada dele; falta a sua parte.")
    return enviar(texto, chat)


def ler_respostas(offset: int | None = None) -> tuple[list[dict], int | None]:
    """Retorna [{'caso': 'C001', 'decisao': 'aprovado'|'recusado', 'quem': nome}] e o próximo offset."""
    params = {"timeout": 0}
    if offset:
        params["offset"] = offset
    res = _call("getUpdates", **params).get("result", [])
    out, prox = [], offset
    for u in res:
        prox = u["update_id"] + 1
        cq = u.get("callback_query")
        if cq and ":" in cq.get("data", ""):
            acao, caso = cq["data"].split(":", 1)
            quem = cq["from"].get("first_name", "?")
            out.append({"caso": caso, "decisao": "aprovado" if acao == "ap" else "recusado", "quem": quem,
                        "callback_id": cq["id"], "chat": cq["message"]["chat"]["id"],
                        "message_id": cq["message"]["message_id"]})
    return out, prox


def confirmar_clique(resp: dict, texto: str):
    try:
        _call("answerCallbackQuery", callback_query_id=resp["callback_id"], text=texto[:180])
        _call("editMessageReplyMarkup", chat_id=resp["chat"], message_id=resp["message_id"], reply_markup={"inline_keyboard": []})
        enviar(texto, str(resp["chat"]))
    except Exception:
        pass


def enviar_card(caso: dict, chat: str | None = None, modo: str = "aprovacao", para: str = "", motivo: str = "",
                legenda: str | None = None):
    """Manda o caso como imagem (card com a marca) + botões, quando for aprovação."""
    from . import cartao
    from . import linguagem as L
    png = cartao.gerar(caso, modo, para, motivo)
    t = L.tipo(caso["tipo"])
    cap = legenda or f"<b>{t['titulo']}</b> · {brl2(caso['valor'])} · {caso['fornecedor']}"
    data = {"chat_id": chat or chat_id(), "caption": cap[:1024], "parse_mode": "HTML"}
    if modo == "aprovacao":
        data["reply_markup"] = json.dumps({"inline_keyboard": [[
            {"text": "✅ Aprovar", "callback_data": f"ap:{caso['id']}"},
            {"text": "❌ Recusar", "callback_data": f"rc:{caso['id']}"}]]})
    tk = token()
    r = requests.post(API.format(token=tk, metodo="sendPhoto"), data=data,
                      files={"photo": (f"{caso['id']}.png", png, "image/png")}, timeout=30)
    r.raise_for_status()
    return r.json()
