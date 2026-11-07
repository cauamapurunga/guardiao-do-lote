"""Transforma o log dos agentes numa linha do tempo para a 'Sala dos agentes' (animação)."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict

from .agentes import Guardiao
from . import linguagem as L


def rs(v: float) -> str:
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

DETECTOR = {"GOLPE_TROCA_CONTA": "Auditor", "BOLETO_SUSPEITO": "Auditor"}
NOMES = {"GOLPE_TROCA_CONTA": "Golpe: conta trocada", "JA_PAGO_FORA_DO_LOTE": "Já pago por fora",
         "DUPLICIDADE": "Duplicidade", "VALOR_DIVERGENTE": "Valor errado", "FORNECEDOR_ERRADO": "Fornecedor errado",
         "OC_INVALIDA": "OC inválida", "BOLETO_SUSPEITO": "Boleto suspeito"}


def _caso_min(c) -> dict:
    return {"id": c.id, "titulo": c.titulo_id, "fornecedor": c.fornecedor, "valor": round(c.valor, 2),
            "perda": round(c.perda_evitada, 2), "tipo": L.tipo(c.tipo)["titulo"], "resumo": c.resumo,
            "evidencias": c.evidencias[:4], "status": c.status}


def construir(g: Guardiao) -> dict:
    ag = g.b.agenda.sort_values(["data_prevista", "horario_fechamento", "lote_remessa"])
    casos_lote = defaultdict(list)
    for c in g.casos:
        casos_lote[c.lote].append(c)
    acoes_caso = defaultdict(list)
    for a in g.log:
        if a.caso:
            acoes_caso[a.caso].append(a)
    forn_alterados = set()
    eventos = []
    leu_caixa = False
    golpe_tratado = set()
    for lote, gl in ag.groupby("lote_remessa", sort=False):
        r0 = gl.iloc[0]
        casos = casos_lote.get(lote, [])
        flag = {c.titulo_id: NOMES.get(c.tipo, c.tipo) for c in casos}
        eventos.append({"t": "lote_abre", "lote": lote, "banco": r0.banco_pagador,
                        "fechamento": f"{r0.data_prevista:%d/%m} {r0.horario_fechamento}",
                        "n": int(len(gl)), "valor": round(float(gl.valor.sum()), 2),
                        "titulos": gl.titulo_id.tolist(), "flag": flag})
        eventos.append({"t": "pensa", "agente": "Maestro",
                        "texto": f"Lote {lote} fecha {r0.data_prevista:%d/%m} às {r0.horario_fechamento}. "
                                 f"{len(gl)} títulos, {rs(gl.valor.sum())}. Despachando conferência."})
        if not leu_caixa:
            leu_caixa = True
            n_msg = len(g.b.comunicacoes)
            eventos.append({"t": "pensa", "agente": "Leitor",
                            "texto": f"Lendo os {n_msg} e-mails de fornecedores. Procurando pedidos de troca de conta, "
                                     "boletos e cobranças, e cruzando o remetente com o cadastro."})
            # o que o Leitor achou vem das provas reais dos casos de golpe (nada escrito à mão)
            prova = next((e for c in g.casos if c.tipo == "GOLPE_TROCA_CONTA" for e in c.evidencias
                          if "pedido veio de" in str(e)), None)
            eventos.append({"t": "tool", "agente": "Leitor", "ferramenta": "listar_comunicacoes", "alvo": "caixa CP",
                            "detalhe": prova or f"{n_msg} e-mails lidos: nenhum pedido de troca de conta suspeito",
                            "modo": "auto"})
            if prova:
                eventos.append({"t": "handoff", "de": "Leitor", "para": "Auditor", "texto": "pedido de troca de conta suspeito"})
        eventos.append({"t": "confere", "agente": "Analista", "n": int(len(gl)),
                        "texto": f"Conferindo {len(gl)} títulos: OC × NF-e × duplicata × DDA × extrato."})
        eventos.append({"t": "pensa", "agente": "Auditor",
                        "texto": f"Checando cadastro de {gl.fornecedor_id.nunique()} fornecedores: alterações bancárias "
                                 "recentes, quem confirmou e por qual telefone, beneficiário dos boletos."})
        for c in casos:
            acs = acoes_caso.get(c.id, [])
            detector = DETECTOR.get(c.tipo, "Analista")
            if c.tipo == "GOLPE_TROCA_CONTA" and c.fornecedor_id in golpe_tratado:
                eventos.append({"t": "tool", "agente": "Auditor", "ferramenta": "bloquear_titulo", "alvo": c.titulo_id,
                                "detalhe": f"mais um título para a conta do golpe: {rs(c.valor)} retido",
                                "modo": "auto", "caso": _caso_min(c), "rapido": True})
                continue
            golpe_tratado.add(c.fornecedor_id) if c.tipo == "GOLPE_TROCA_CONTA" else None
            eventos.append({"t": "achado", "agente": detector, "caso": _caso_min(c),
                            "texto": f"{c.titulo_id} · {L.tipo(c.tipo)['frase']} Prova: {c.evidencias[0]}."})
            atual = detector
            for a in acs:
                quem = a.agente.split(" ")[0]
                if quem in ("Analista", "Auditor") and quem != atual:
                    eventos.append({"t": "handoff", "de": atual, "para": quem, "texto": a.ferramenta})
                    atual = quem
                ev = {"t": "tool", "agente": quem, "ferramenta": a.ferramenta, "alvo": a.alvo, "detalhe": a.detalhe,
                      "modo": a.modo, "caso": _caso_min(c)}
                eventos.append(ev)
                if a.modo in ("aprovacao", "humano") and quem != "Humano":
                    dec = next((x for x in reversed(c.acoes) if x["ferramenta"] in ("aprovar_acao", "recusar_acao")), None)
                    if dec and c.status == "aguardando_aprovacao":   # só a 1ª de 2 aprovações
                        dec = dict(dec, agente=dec["agente"][:-1] + " · falta a 2ª aprovação)")
                    eventos.append({"t": "humano", "agente": quem, "para": a.para, "ferramenta": a.ferramenta,
                                    "texto": a.detalhe, "caso": _caso_min(c),
                                    "decisao": ({"aprovado": dec["ferramenta"] == "aprovar_acao",
                                                 "quem": dec["agente"][len("Humano ("):-1] if dec["agente"].startswith("Humano (") else dec["agente"]} if dec else None)})
        retidos = [c for c in casos]
        eventos.append({"t": "lote_fecha", "lote": lote, "ok": int(len(gl) - len(retidos)),
                        "ok_valor": round(float(gl[~gl.titulo_id.isin([c.titulo_id for c in retidos])].valor.sum()), 2),
                        "retidos": len(retidos), "perda": round(sum(c.perda_evitada for c in retidos), 2)})
    # causa raiz no fim
    eventos.append({"t": "pensa", "agente": "Auditor",
                    "texto": "Todos os lotes conferidos. Procurando padrão nos erros: quem lançou, por qual canal, em qual processo."})
    for a in g.log:
        if a.ferramenta == "propor_correcao_processo":
            eventos.append({"t": "tool", "agente": "Auditor", "ferramenta": a.ferramenta, "alvo": a.alvo,
                            "detalhe": a.detalhe, "modo": "auto"})
    p = g.placar()
    return {"eventos": eventos, "placar": {k: v for k, v in p.items() if k != "por_tipo"}}
