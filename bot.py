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
from guardiao import ia, leitor_caixa

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


def resumos_ia(casos, chat):
    """Em paralelo ao bot: a IA escreve o resumo de cada caso para quem aprova."""
    for c in casos:
        try:
            tg.enviar(f"🧠 <b>Em poucas palavras · {c.id}</b>\n{leitor_caixa.explicar_caso(asdict(c))}", chat)
        except Exception as e:
            print("IA indisponível:", e)


def main():
    offset = None
    chats = set()
    print("Bot no ar. Mande /start para o bot no Telegram.")
    while True:
        try:
            res = tg._call("getUpdates", timeout=25, offset=offset).get("result", [])
        except Exception as e:
            print("Sem conexão com o Telegram agora; tentando de novo...", type(e).__name__)
            time.sleep(3)
            continue
        for u in res:
            offset = u["update_id"] + 1
            if "callback_query" in u:
                cq = u["callback_query"]
                acao, cid = cq["data"].split(":", 1)
                quem = cq["from"].get("first_name", "?")
                c = g.decidir(cid, acao == "ap", f"{quem} (Telegram)")
                resp = {"callback_id": cq["id"], "chat": cq["message"]["chat"]["id"], "message_id": cq["message"]["message_id"]}
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
            if texto.startswith("/start"):
                tg.enviar(status() + f"\n\n(seu chat_id: <code>{chat}</code>)", chat)
            elif texto.startswith("/resumo"):
                from guardiao import resumo as R
                tg.enviar(R.resumo_do_dia(g), chat)
            elif texto.startswith("/status"):
                tg.enviar(status(), chat)
            elif texto.startswith("/lote"):
                tg.enviar(lotes(), chat)
            elif texto.startswith("/pendentes"):
                pend = [c for c in g.casos if c.status == "aguardando_aprovacao"]
                for c in pend[:10]:
                    tg.enviar_card(asdict(c), chat)          # card em imagem + botões, chega na hora
                if pend and ia.disponivel():
                    threading.Thread(target=resumos_ia, args=(pend[:10], chat), daemon=True).start()
                if not pend:
                    tg.enviar("Nada pendente. 🎉", chat)
            elif texto.startswith("/avisos"):
                for c in g.casos:
                    for x in c.acoes:
                        if x["ferramenta"] == "acionar_pessoa":
                            tg.enviar_card(asdict(c), chat, "aviso", x["para"], x["detalhe"])
                            break
            elif tid:
                tg.enviar(titulo(tid.group(0)), chat)
            else:
                tg.enviar("Posso: /resumo · /status · /lote · /pendentes · /avisos · ou mande um número de título (TP…).", chat)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Bot parado.")
