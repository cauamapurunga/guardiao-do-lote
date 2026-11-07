"""Guardião do Lote — app web (FastAPI) + bot do Telegram no mesmo processo.

Rodar:  py servidor.py      → abre http://localhost:8000
O que você aprova no Telegram aparece no app na hora, e vice-versa (mesmo estado).
"""
from __future__ import annotations

import json
import os
import threading
import webbrowser
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from guardiao import env  # noqa: F401
from guardiao import cartao, ia, leitor_caixa
from guardiao import linguagem as L
from guardiao import telegram as tg
from guardiao.agentes import Guardiao
from guardiao.dados import brl2, carregar
from guardiao.timeline import construir
from guardiao import resumo as R

RAIZ = Path(__file__).resolve().parent
WEB = RAIZ / "web"

app = FastAPI(title="Guardião do Lote")
app.mount("/assets", StaticFiles(directory=RAIZ / "assets"), name="assets")
app.mount("/static", StaticFiles(directory=WEB), name="static")

ESTADO: dict = {}
_lock = threading.Lock()


def iniciar(repetir_decisoes: list | None = None, base=None):
    with _lock:
        b = base if base is not None else carregar()
        ESTADO["b"] = b
        ESTADO["g"] = Guardiao(b).executar()
        ESTADO["caixa"] = leitor_caixa.ler(b, usar_ia=False)
        ESTADO["caixa_ia"] = False
        ESTADO["eventos_humanos"] = []
        g = ESTADO["g"]
        _decidir = g.decidir

        def decidir_e_registrar(cid, aprovado, quem="humano"):
            c = _decidir(cid, aprovado, quem)
            if c:
                ESTADO["eventos_humanos"].append({"quem": quem, "caso": c.id, "titulo": c.titulo_id,
                                                  "aprovado": aprovado, "resumo": c.resumo})
            return c
        g.decidir = decidir_e_registrar
        ESTADO["conferido_em"] = pd.Timestamp.now().strftime("%d/%m %H:%M")
        # nova conferência: decisões que pessoas já tomaram continuam valendo (pelo número do título)
        for h in repetir_decisoes or []:
            c = next((x for x in g.casos if x.titulo_id == h["titulo"]), None)
            if c:
                g.decidir(c.id, h["aprovado"], h["quem"])
    try:
        import bot
        bot.g = ESTADO["g"]
    except Exception:
        pass


def caso_json(c) -> dict:
    d = asdict(c)
    t = L.tipo(c.tipo)
    d["tipo_titulo"] = t["titulo"]
    d["tipo_frase"] = t["frase"]
    d["cor"] = t["cor"]
    d["valor_fmt"] = brl2(c.valor)
    d["perda_fmt"] = brl2(c.perda_evitada)
    d["feito"] = []
    for a in c.acoes:
        if a["modo"] == "auto":
            txt = L.feito(a["ferramenta"])
            if txt not in d["feito"]:
                d["feito"].append(txt)
    d["pedido"] = L.pedido(c.aprovacao["acao"]) if c.aprovacao else None
    d["para"] = L.primeiro_nome(c.aprovacao["nome"]) if c.aprovacao else None
    avisos = [a for a in c.acoes if a["ferramenta"] == "acionar_pessoa"]
    d["avisado"] = [{"pessoa": L.primeiro_nome(a["para"]), "motivo": a["detalhe"]} for a in avisos]
    n_forn = sum(1 for x in ESTADO["g"].casos if x.fornecedor_id == c.fornecedor_id)
    d["se_aprovar"], d["se_recusar"] = L.consequencias(d, n_forn) if c.aprovacao else (None, None)
    # urgência: horas até o lote ir ao banco, a partir do relógio do ambiente
    sai = pd.Timestamp(f"{ESTADO['b'].ref.year}-{c.fechamento[3:5]}-{c.fechamento[0:2]} {c.fechamento[6:]}")
    d["horas"] = max(0, int((sai - ESTADO["b"].ref).total_seconds() // 3600))
    return d


@app.get("/", response_class=HTMLResponse)
def index():
    return (WEB / "index.html").read_text(encoding="utf-8")


@app.get("/sala", response_class=HTMLResponse)
def sala():
    html = (RAIZ / "guardiao" / "sala.html").read_text(encoding="utf-8")
    return html.replace("__DATA__", json.dumps(construir(ESTADO["g"]), default=str, ensure_ascii=False))


@app.get("/api/estado")
def estado():
    g: Guardiao = ESTADO["g"]
    b = ESTADO["b"]
    p = g.placar()
    ag = b.agenda
    casos = [caso_json(c) for c in g.casos]
    lotes = []
    for lote, gl in ag.sort_values(["data_prevista", "horario_fechamento"]).groupby("lote_remessa", sort=False):
        cs = [c for c in g.casos if c.lote == lote]
        lotes.append({"lote": lote, "banco": gl.banco_pagador.iloc[0].replace("Banco ", ""),
                      "fecha": f"{gl.data_prevista.iloc[0]:%d/%m} {gl.horario_fechamento.iloc[0]}",
                      "titulos": int(len(gl)), "valor": float(gl.valor.sum()), "retidos": len(cs),
                      "segurado": float(sum(c.perda_evitada for c in cs)),
                      "pendentes": sum(1 for c in cs if c.status != "resolvido")})
    val = None
    if (RAIZ / "validacao.json").exists():
        val = json.loads((RAIZ / "validacao.json").read_text(encoding="utf-8"))
    log = [asdict(a) for a in g.log]
    return {"placar": {k: v for k, v in p.items() if k != "por_tipo"},
            "por_tipo": [{"tipo": L.tipo(k)["titulo"], "cor": L.tipo(k)["cor"], **v} for k, v in p["por_tipo"].items()],
            "casos": casos, "lotes": lotes, "validacao": val, "log": log[-400:],
            "humanos": ESTADO["eventos_humanos"][-30:], "conferido_em": ESTADO.get("conferido_em"),
            "simulacao": ESTADO.get("simulacao"),
            "telegram": {"token": bool(tg.token()), "chat": bool(tg.chat_id() or ESTADO.get("chat"))},
            "ia": {"ativa": ia.disponivel(), "uso": ia.resumo_uso(), "linhas": ia.USO["linhas"][-8:]},
            "causa_raiz": [asdict(a) for a in g.log if a.ferramenta in ("propor_correcao_processo", "abrir_incidente")]}


class Decisao(BaseModel):
    caso: str
    aprovar: bool
    quem: str = "Painel"


@app.post("/api/decidir")
def decidir(d: Decisao):
    with _lock:
        c = ESTADO["g"].decidir(d.caso, d.aprovar, d.quem)
    if not c:
        raise HTTPException(404, "caso não encontrado")
    return caso_json(c)


@app.get("/api/card/{caso_id}.png")
def card(caso_id: str):
    c = next((x for x in ESTADO["g"].casos if x.id == caso_id), None)
    if not c:
        raise HTTPException(404)
    d = asdict(c)
    if c.aprovacao:
        png = cartao.gerar(d, "aprovacao")
    else:
        av = next((a for a in c.acoes if a["ferramenta"] == "acionar_pessoa"), None)
        png = cartao.gerar(d, "aviso", av["para"] if av else "", av["detalhe"] if av else "")
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.post("/api/telegram/enviar")
def telegram_enviar():
    if not tg.token():
        raise HTTPException(400, "TELEGRAM_TOKEN não configurado no .env")
    chat = tg.chat_id() or ESTADO.get("chat") or tg.descobrir_chat_id()
    if not chat:
        raise HTTPException(400, "Mande /start para o bot no Telegram e tente de novo")
    ESTADO["chat"] = chat
    por_pessoa = tg.rotear_pendentes(ESTADO["g"], chat)     # cada um recebe o seu; o resto vai ao chat principal
    return {"enviados": sum(por_pessoa.values()), "por_pessoa": por_pessoa}


@app.get("/api/caixa")
def caixa():
    df = ESTADO["caixa"].copy()
    df["data"] = df["data"].astype(str)
    return {"ia": ESTADO["caixa_ia"], "linhas": json.loads(df.to_json(orient="records", force_ascii=False))}


@app.post("/api/caixa/ia")
def caixa_ia():
    if not ia.disponivel():
        raise HTTPException(400, "AI_PROXY_API_KEY não configurado")
    ESTADO["caixa"] = leitor_caixa.ler(ESTADO["b"], usar_ia=True)
    ESTADO["caixa_ia"] = bool(ia.USO["chamadas"])
    return caixa()


@app.post("/api/explicar/{caso_id}")
def explicar(caso_id: str):
    c = next((x for x in ESTADO["g"].casos if x.id == caso_id), None)
    if not c:
        raise HTTPException(404)
    if not ia.disponivel():
        return {"texto": leitor_caixa.texto_padrao(asdict(c)), "fonte": "padrão"}
    try:
        txt = leitor_caixa.explicar_caso(asdict(c))
        return {"texto": txt, "fonte": "IA, conferida contra as evidências"}
    except Exception:
        return {"texto": leitor_caixa.texto_padrao(asdict(c)), "fonte": "texto padrão (IA fora do ar)"}


@app.post("/api/reiniciar")
def reiniciar():
    ESTADO.pop("simulacao", None)
    iniciar()
    return {"ok": True}


@app.post("/api/conferir")
def conferir():
    """Relê os arquivos dos sistemas e confere tudo de novo, mantendo as decisões já tomadas."""
    ESTADO.pop("simulacao", None)
    try:
        iniciar(list(ESTADO.get("eventos_humanos", [])))
    except Exception as e:
        raise HTTPException(400, f"Não consegui ler os dados: {e}")
    return {"ok": True, "conferido_em": ESTADO["conferido_em"], "casos": len(ESTADO["g"].casos)}


@app.post("/api/simular")
def simular():
    """Dia novo: coloca 7 problemas novos em fornecedores e valores sorteados e os agentes conferem de novo.
    Mostra que o resultado depende dos dados, não de respostas decoradas."""
    import random
    import validar
    from guardiao.deteccao import varrer
    base = carregar()
    seed = random.randint(1000, 999999)
    proibidos = {a.fornecedor_id for a in varrer(base)}
    novo, esperado = validar.injetar(base, seed, proibidos)
    novo, esperado2 = validar.injetar_extras(novo, seed + 1, proibidos | {novo.agenda.set_index("titulo_id").fornecedor_id.get(t) for t in esperado})
    esperado = {**esperado, **esperado2}
    iniciar(base=novo)
    achados = {c.titulo_id for c in ESTADO["g"].casos}
    pegos = sum(1 for t in esperado if t in achados)
    ESTADO["simulacao"] = {"seed": seed, "injetados": len(esperado), "pegos": pegos}
    return ESTADO["simulacao"] | {"casos": len(ESTADO["g"].casos)}


@app.get("/api/resumo")
def resumo():
    return {"texto": R.resumo_do_dia(ESTADO["g"])}


@app.post("/api/resumo/telegram")
def resumo_telegram():
    chat = tg.chat_id() or ESTADO.get("chat") or (tg.descobrir_chat_id() if tg.token() else None)
    if not chat:
        raise HTTPException(400, "Mande /start para o bot no Telegram e tente de novo")
    ESTADO["chat"] = chat
    tg.enviar(R.resumo_do_dia(ESTADO["g"]), chat)
    return {"ok": True}


@app.get("/api/auditoria.csv")
def auditoria():
    return Response(R.auditoria_csv(ESTADO["g"]), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=guardiao_auditoria.csv"})


@app.get("/api/glossario")
def glossario():
    return L.GLOSSARIO


def _rotina():
    """Acompanha o dia a dia: confere de novo de hora em hora e manda o resumo às 8h no Telegram."""
    import time as _t
    intervalo = int(os.getenv("INTERVALO_MIN", "60")) * 60
    ultimo_resumo = None
    while True:
        _t.sleep(60)
        agora = pd.Timestamp.now()
        if (agora - pd.Timestamp(ESTADO.get("_ultima", agora))).total_seconds() >= intervalo:
            try:
                iniciar(list(ESTADO.get("eventos_humanos", [])))
                print(f"🔁 Conferência automática às {agora:%H:%M}: {len(ESTADO['g'].casos)} casos")
            except Exception as e:
                print("Conferência automática falhou:", type(e).__name__)
            ESTADO["_ultima"] = agora
        chat = tg.chat_id() or ESTADO.get("chat")
        if tg.token() and chat and agora.hour == 8 and ultimo_resumo != agora.date():
            try:
                tg.enviar(R.resumo_do_dia(ESTADO["g"]), chat)
                ultimo_resumo = agora.date()
            except Exception:
                pass


def _bot():
    try:
        import bot
        bot.g = ESTADO["g"]
        bot.main()
    except Exception as e:
        print("Bot do Telegram parado:", e)


if __name__ == "__main__":
    iniciar()
    ESTADO["_ultima"] = pd.Timestamp.now()
    threading.Thread(target=_rotina, daemon=True).start()
    if tg.token():
        threading.Thread(target=_bot, daemon=True).start()
        print("🤖 Bot do Telegram ligado (mande /start para ele).")
    porta = int(os.getenv("PORTA", "8000"))
    threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{porta}")).start()
    print(f"🛡️  Guardião do Lote em http://localhost:{porta}")
    uvicorn.run(app, host="0.0.0.0", port=porta, log_level="warning")
