"""Bot do Guardião no Telegram: qualquer pessoa do time aciona o agente e aprova/recusa com um toque.

Rodar:  python bot.py   (precisa de TELEGRAM_TOKEN no .env)

Comandos:
  /start        registra o chat e mostra o resumo
  /resumo       resumo do dia (também chega sozinho às 8h quando o servidor está ligado)
  /status       placar em R$ e o que está pendente
  /lote         próximos lotes e o que o agente segurou em cada um
  /pendentes    pedidos de aprovação (card em imagem + botões)
  /avisos       pessoas acionadas pelo agente (card em imagem)
  /titulo TP…   situação de um título (ou só mande o número TP… no texto)
  /sou renata   este chat passa a ser da Renata: /pendentes e /avisos mostram só o que é dela
  /sair         este chat volta a ver tudo   ·   /quem   quem está cadastrado
Botões ✅/❌ aplicam a decisão e o agente executa o resto.
"""
import re
import threading
import time
from dataclasses import asdict

from guardiao import env  # noqa: F401
from guardiao import telegram as tg
from guardiao.agentes import Guardiao
from guardiao.dados import carregar
from guardiao import contatos

g = Guardiao(carregar()).executar()
brl = lambda v: f"R$ {v:,.0f}".replace(",", ".")


def status() -> str:
    p = g.placar()
    pend = sum(1 for c in g.casos if c.status == "aguardando_aprovacao")
    return (f"🛡️ <b>Guardião do Lote</b>\n{p['titulos_conferidos']} títulos conferidos em {p['lotes']} lotes "
            f"({brl(p['valor_na_agenda'])})\n\n"
            f"💸 Sairia indevidamente sem o agente: <b>{brl(p['perda_sem_agente'])}</b>\n"
            f"✅ Custo com o agente: <b>{brl(p['custo_agente'])}</b>\n"
            f"⚙️ {p['acoes_executadas']} ações feitas sozinho · {p['resolvidos_sozinho']}/{p['casos']} casos resolvidos\n"
            f"🖐️ {pend} decisões esperando aprovação → /pendentes")


def lotes() -> str:
    linhas = []
    for lote, gdf in g.b.agenda.groupby("lote_remessa"):
        segurado = [c for c in g.casos if c.lote == lote]
        val = sum(c.perda_evitada for c in segurado)
        linhas.append(f"• <b>{lote}</b> fecha {gdf.data_prevista.iloc[0]:%d/%m} {gdf.horario_fechamento.iloc[0]} — "
                      f"{len(gdf)} títulos, {len(segurado)} casos, {brl(val)} segurados")
    return "📦 <b>Lotes</b>\n" + "\n".join(linhas[:10])


def titulo(tid: str) -> str:
    st = g.titulo_status.get(tid)
    if not st:
        return f"Não achei {tid} na agenda de remessa."
    c = next((x for x in g.casos if x.titulo_id == tid), None)
    if not c:
        r = g.b.agenda[g.b.agenda.titulo_id == tid].iloc[0]
        return f"✅ {tid} conferido sem problema: {g.forn_nome.get(r.fornecedor_id)} {brl(r.valor)} no lote {r.lote_remessa}."
    ev = "\n".join(f"• {e}" for e in c.evidencias[:4])
    return f"⚠️ <b>{tid}</b> — {c.resumo}\nSituação no ERP: <b>{st}</b> · caso {c.id}: {c.status}\n{ev}"


def main():
    offset = None
    chats = set()
    print("Bot no ar. Mande /start para o bot no Telegram.")
    while True:
        try:
            res = tg._call("getUpdates", timeout=25, offset=offset).get("result", [])
        except Exception as e:
            print("Telegram:", e, "— tentando de novo em 3s")
            time.sleep(3)
            continue
        for u in res:
            offset = u["update_id"] + 1
            if "callback_query" in u:
                cq = u["callback_query"]
                acao, cid = cq["data"].split(":", 1)
                resp = {"callback_id": cq["id"], "chat": cq["message"]["chat"]["id"], "message_id": cq["message"]["message_id"]}
                eu = contatos.pessoa_do_chat(resp["chat"])
                caso = next((x for x in g.casos if x.id == cid), None)
                dono = (caso.aprovacao or {}).get("pessoa") if caso else None
                if eu and dono and eu != dono:            # só quem tem a alçada decide
                    tg._call("answerCallbackQuery", callback_query_id=cq["id"], show_alert=True,
                             text=f"Esta decisão é de {contatos.primeiro(dono)}. Você está cadastrado como {contatos.primeiro(eu)}.")
                    continue
                quem = contatos.nome(eu).split("(")[0].strip() if eu else cq["from"].get("first_name", "?")
                c = g.decidir(cid, acao == "ap", f"{quem} (Telegram)")
                txt = (f"{'✅ Aprovado' if acao == 'ap' else '❌ Recusado'} por {quem}: {c.resumo}\n"
                       f"Agente executou: " + ", ".join(a["ferramenta"] for a in c.acoes[-3:])) if c else "Caso não encontrado."
                tg.confirmar_clique(resp, txt)
                continue
            m = u.get("message")
            if not m or "text" not in m:
                continue
            chat = str(m["chat"]["id"])
            chats.add(chat)
            texto = m["text"].strip()
            tid = re.search(r"TP\d{6}", texto.upper())
            eu = contatos.pessoa_do_chat(chat)
            so_eu = {eu} if eu else None
            if texto.startswith("/start"):
                tg.enviar(status() + "\n\nQuem é você? Mande <b>/sou</b> e o seu nome (ex.: /sou renata) "
                          "para receber só o que é seu.", chat)
            elif texto.startswith("/sou"):
                arg = texto[4:].strip()
                pid = contatos.achar_pessoa(arg)
                if not pid:
                    lista = "\n".join(f"• /sou {contatos.primeiro(p).lower()} — {contatos.nome(p)}" for p in contatos.PESSOAS)
                    tg.enviar(("Não achei essa pessoa. " if arg else "") + "Quem é você?\n" + lista, chat)
                else:
                    contatos.registrar(chat, pid)
                    n = sum(1 for c in g.casos if c.status == "aguardando_aprovacao" and (c.aprovacao or {}).get("pessoa") == pid)
                    tg.enviar(f"👋 Pronto, <b>{contatos.nome(pid)}</b>. Daqui em diante este chat recebe só o que é seu.\n"
                              f"Você tem {n} {'decisão esperando' if n == 1 else 'decisões esperando'} → /pendentes · avisos → /avisos\n"
                              f"(para voltar a ver tudo: /sair)", chat)
            elif texto.startswith("/sair"):
                pid = contatos.sair(chat)
                tg.enviar(f"Ok, este chat não é mais de {contatos.primeiro(pid)}. Volta a ver tudo." if pid
                          else "Este chat não estava cadastrado para ninguém.", chat)
            elif texto.startswith("/quem"):
                cad = contatos.cadastrados()
                tg.enviar("<b>Quem está no Telegram</b>\n" + ("\n".join(f"• {contatos.nome(p)}" for p in cad) or "ninguém cadastrado ainda")
                          + (f"\n\nEste chat: {contatos.nome(eu)}" if eu else "\n\nEste chat: vê tudo"), chat)
            elif texto.startswith("/resumo"):
                from guardiao import resumo as R
                tg.enviar(R.resumo_do_dia(g), chat)
            elif texto.startswith("/status"):
                tg.enviar(status(), chat)
            elif texto.startswith("/lote"):
                tg.enviar(lotes(), chat)
            elif texto.startswith("/pendentes"):
                tg.enviar_pendentes(g, chat, pessoas=so_eu)   # 1 abertura + 1 imagem com resumo e botões por caso
            elif texto.startswith("/avisos"):
                tg.enviar_avisos(g, chat, pessoas=so_eu)
            elif tid:
                tg.enviar(titulo(tid.group(0)), chat)
            else:
                tg.enviar("Posso: /sou (quem é você) · /pendentes · /avisos · /resumo · /status · /lote · ou mande um número de título (TP…).", chat)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Bot parado.")
