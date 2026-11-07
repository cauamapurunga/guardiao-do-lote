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


def enviar_pendentes(g, chat: str | None = None, n: int = 5, pessoas: set | None = None) -> int:
    """Decisões pendentes no Telegram: 1 mensagem de abertura e, para cada caso, 1 imagem com o resumo,
    o que acontece se aprovar / se recusar e os botões. Os que saem primeiro do banco vêm antes."""
    from concurrent.futures import ThreadPoolExecutor
    from dataclasses import asdict
    from html import escape
    from . import ia, leitor_caixa
    from . import linguagem as L

    from . import contatos
    pend = [c for c in g.casos if c.status == "aguardando_aprovacao"
            and (pessoas is None or (c.aprovacao or {}).get("pessoa") in pessoas)]
    so_uma = contatos.primeiro(next(iter(pessoas))) if pessoas and len(pessoas) == 1 else None
    if not pend:
        enviar(f"✅ Nada esperando a sua decisão{', ' + so_uma if so_uma else ''}. O agente resolveu o resto sozinho.", chat)
        return 0
    from .agentes import PRIORIDADE
    grav = lambda t: PRIORIDADE.index(t) if t in PRIORIDADE else len(PRIORIDADE)
    pend.sort(key=lambda c: (c.fechamento[3:5], c.fechamento[0:2], c.fechamento[6:], grav(c.tipo), -c.valor))
    vez = pend[:n]
    parado = sum(c.valor for c in pend)
    quem = f"{so_uma}, " if so_uma else ""
    enviar(f"🖐️ <b>{quem}{len(pend)} {'decisões esperando' if len(pend) > 1 else 'decisão esperando'} você</b> · {brl2(parado)} parados fora do lote\n"
           f"Mando {'as ' + str(len(vez)) + ' que saem' if len(vez) > 1 else 'a que sai'} primeiro do banco.", chat)

    resumos: dict[str, str] = {}
    if ia.disponivel():                                     # a IA escreve os resumos em paralelo, com limite de tempo
        ex = ThreadPoolExecutor(max_workers=len(vez))
        futs = {c.id: ex.submit(leitor_caixa.explicar_caso, asdict(c)) for c in vez}
        for cid, f in futs.items():
            try:
                r = f.result(timeout=25)
                if r:
                    resumos[cid] = r
            except Exception:
                pass                                         # sem resumo da IA: usa a frase padrão
        ex.shutdown(wait=False)

    for c in vez:
        d = asdict(c)
        t = L.tipo(c.tipo)
        n_forn = sum(1 for x in g.casos if x.fornecedor_id == c.fornecedor_id)
        sim, nao = L.consequencias(d, n_forn)
        resumo = resumos.get(c.id) or t["frase"]
        if len(resumo) > 420:
            resumo = resumo[:417].rsplit(" ", 1)[0] + "…"
        cap = (f"<b>{escape(t['titulo'])}</b> · {brl2(c.valor)}\n{escape(c.fornecedor)} · sai do banco {escape(c.fechamento)}\n\n"
               f"{escape(resumo)}\n\n✅ <b>Se aprovar:</b> {escape(sim)}\n❌ <b>Se recusar:</b> {escape(nao)}")
        enviar_card(d, chat, legenda=cap)
    resto = len(pend) - len(vez)
    if resto:
        enviar(f"Faltam {resto}. Decida estas e mande /pendentes de novo, ou veja todas no app (aba Decisões).", chat)
    return len(vez)


def enviar_avisos(g, chat: str | None = None, pessoas: set | None = None) -> int:
    """Pessoas que o agente acionou (sem precisar aprovar nada): 1 card por caso."""
    from dataclasses import asdict
    n = 0
    for c in g.casos:
        for x in c.acoes:
            if x["ferramenta"] == "acionar_pessoa" and (pessoas is None or x["alvo"] in pessoas):
                enviar_card(asdict(c), chat, "aviso", x["para"], x["detalhe"])
                n += 1
                break
    if not n:
        enviar("✅ Nenhum aviso para você agora.", chat)
    return n


def rotear_pendentes(g, chat_principal: str | None) -> dict:
    """Cada pessoa cadastrada (/sou) recebe só as decisões dela; o resto vai para o chat principal."""
    from . import contatos
    donos = {(c.aprovacao or {}).get("pessoa") for c in g.casos if c.status == "aguardando_aprovacao"}
    cad = contatos.cadastrados()
    enviados = {}
    for pid in sorted(donos):
        if pid in cad:
            enviados[contatos.primeiro(pid)] = enviar_pendentes(g, cad[pid], pessoas={pid})
    resto = {p for p in donos if p not in cad}
    if resto and chat_principal:
        enviados["chat principal"] = enviar_pendentes(g, chat_principal, pessoas=resto)
    return enviados
