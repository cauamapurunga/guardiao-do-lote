"""Resumo do dia e relatório de auditoria (texto simples, para Telegram e controller)."""
from __future__ import annotations

import csv
import io

from . import linguagem as L
from .dados import brl2


def resumo_do_dia(g) -> str:
    b = g.b
    ag = b.agenda.sort_values(["data_prevista", "horario_fechamento"])
    prox = ag.drop_duplicates("lote_remessa").iloc[0]
    lote = ag[ag.lote_remessa == prox.lote_remessa]
    casos_lote = [c for c in g.casos if c.lote == prox.lote_remessa]
    pend = [c for c in g.casos if c.status == "aguardando_aprovacao"]
    urg = [c for c in pend if c.lote == prox.lote_remessa]
    p = g.placar()
    linhas = [
        "☀️ <b>Bom dia! Resumo do Guardião do Lote</b>",
        "",
        f"<b>Próxima saída:</b> {prox.data_prevista:%d/%m} às {prox.horario_fechamento}, {prox.banco_pagador}",
        f"{len(lote)} títulos · {brl2(lote.valor.sum())}",
        f"Retive {len(casos_lote)} títulos ({brl2(sum(c.perda_evitada for c in casos_lote))} que sairiam errado).",
        "",
        f"<b>Na semana:</b> {p['titulos_conferidos']} títulos conferidos, {brl2(p['perda_sem_agente'])} segurados.",
        f"Resolvi {p['resolvidos_sozinho']} problemas sozinho.",
    ]
    if pend:
        linhas += ["", f"<b>Preciso de você em {len(pend)} decisões</b>"
                   + (f", {len(urg)} antes da próxima saída:" if urg else ":")]
        for c in (urg or pend)[:5]:
            linhas.append(f"• {L.tipo(c.tipo)['titulo']} · {c.fornecedor} · {brl2(c.valor)} → {L.primeiro_nome(c.aprovacao['nome'])}")
        linhas.append("Mande /pendentes para ver e decidir.")
    else:
        linhas += ["", "Nada esperando decisão. ✅"]
    return "\n".join(linhas)


def auditoria_csv(g) -> str:
    """Uma linha por ação: quem fez, em qual título, por quê e com qual evidência."""
    casos = {c.id: c for c in g.casos}
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["quando", "quem", "ferramenta", "alvo", "detalhe", "modo", "pessoa_acionada", "caso", "tipo",
                "titulo", "fornecedor", "valor", "evidencia_principal"])
    for a in g.log:
        c = casos.get(a.caso)
        w.writerow([a.ts, a.agente, a.ferramenta, a.alvo, a.detalhe, a.modo, a.para, a.caso,
                    L.tipo(c.tipo)["titulo"] if c else "", c.titulo_id if c else "", c.fornecedor if c else "",
                    f"{c.valor:.2f}".replace(".", ",") if c else "", c.evidencias[0] if c else ""])
    return "﻿" + buf.getvalue()
