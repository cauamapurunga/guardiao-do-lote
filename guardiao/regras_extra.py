"""Regras que a política de pagamentos exige e que não apareceram na base de treino, mas podem aparecer em dados reais.

Cada uma é genérica (nada amarrado a ID) e testada no validar.py com problemas injetados.
"""
from __future__ import annotations

import pandas as pd

from .dados import Bases, brl2, raiz, so_digitos

ALCADA_ANALISTA = 5000.0
PERFIS_QUE_LANCAM = {"analista_cp", "integracao", "aprovador", "tesouraria"}


def _ac(r, tipo, sev, resumo, ev, agente="Analista", perda=0.0, **extra):
    from .deteccao import _achado
    return _achado(r, tipo, sev, resumo, ev, agente, perda, **extra)


# ------------------------------------------------------------ boleto x DDA (o que o banco registrou de verdade)
def boleto_no_dda(b: Bases, A: pd.DataFrame):
    out = []
    if b.dda is None or b.dda.empty:
        return out
    dda = b.dda.assign(ld=b.dda.linha_digitavel.map(so_digitos)).drop_duplicates("ld").set_index("ld")
    for _, r in A[A.forma_pagamento == "boleto"].iterrows():
        ld = so_digitos(r.linha_digitavel)
        if len(ld) != 47:
            continue
        if ld not in dda.index:
            out.append(_ac(r, "BOLETO_SUSPEITO", "critica", f"Boleto não está registrado no banco (DDA) ({r.razao_social})",
                           ["a linha digitável do título não aparece no DDA da empresa: nenhum banco registrou esse boleto",
                            "boleto fora do DDA é o padrão do golpe do boleto falso"], agente="Auditor", perda=float(r.valor)))
            continue
        d = dda.loc[ld]
        if d.situacao == "liquidado":
            out.append(_ac(r, "JA_PAGO_FORA_DO_LOTE", "critica", f"Boleto já consta como pago no banco ({r.razao_social})",
                           [f"DDA: boleto {d.numero_documento} liquidado em {d.data_situacao}",
                            "título continua agendado: sairia em dobro"], perda=float(r.valor), data_pgto=str(d.data_situacao),
                           banco_pgto=f"DDA {d.nome_banco_cobrador}"))
        elif d.situacao == "baixado pelo beneficiário":
            out.append(_ac(r, "BOLETO_BAIXADO", "alta", f"O fornecedor cancelou este boleto ({r.razao_social})",
                           [f"DDA: boleto {d.numero_documento} baixado pelo beneficiário em {d.data_situacao}",
                            "pagar boleto baixado gera devolução ou pagamento sem baixa; pedir o boleto novo"],
                           perda=0.0))
    return out


# ------------------------------------------------------------ nota cancelada ou recusada
def nota_invalida(b: Bases, A: pd.DataFrame):
    out = []
    nfs = b.nfs.drop_duplicates(["raiz", "nf_norm"]).set_index(["raiz", "nf_norm"])
    ruins_sefaz = {"cancelada", "denegada", "inutilizada"}
    ruins_manif = {"desconhecimento da operação", "operação não realizada"}
    for _, r in A[A.nf_norm.astype(str) != ""].iterrows():
        k = (r.raiz, r.nf_norm)
        if k not in nfs.index:
            continue
        nf = nfs.loc[k]
        sit = str(nf.get("situacao_sefaz", "autorizada")).lower()
        man = str(nf.get("manifestacao_destinatario", "")).lower()
        if sit in ruins_sefaz or man in ruins_manif:
            motivo = f"NF {nf.numero_nf} está '{sit}' na Receita" if sit in ruins_sefaz else f"a empresa registrou '{man}' para a NF {nf.numero_nf}"
            out.append(_ac(r, "NF_CANCELADA", "critica", f"Pagamento de nota cancelada ou recusada ({r.razao_social})",
                           [motivo, "sem nota válida não existe dívida a pagar"], perda=float(r.valor)))
    return out


# ------------------------------------------------------------ mercadoria que não chegou
def sem_recebimento(b: Bases, A: pd.DataFrame, dias: int = 20):
    out = []
    if b.recebimentos is None:
        return out
    recebidas = set(b.recebimentos.chave_acesso.astype(str))
    nfs = b.nfs.drop_duplicates(["raiz", "nf_norm"]).set_index(["raiz", "nf_norm"])
    for _, r in A[A.categoria.isin(["produto", "embalagens", "insumos_capa"])].iterrows():
        k = (r.raiz, r.nf_norm)
        if k not in nfs.index:
            continue
        nf = nfs.loc[k]
        emitida = pd.Timestamp(nf.data_emissao)
        if nf.chave_acesso not in recebidas and (b.ref - emitida).days >= dias:
            out.append(_ac(r, "SEM_RECEBIMENTO", "alta", f"Mercadoria não chegou ao CD ({r.razao_social})",
                           [f"NF {nf.numero_nf} emitida em {emitida:%d/%m}: nenhum recebimento no WMS há {(b.ref - emitida).days} dias",
                            "política: conferência de 3 vias (OC × NF × recebimento) antes de pagar"], perda=0.0))
    return out


# ------------------------------------------------------------ dividir para caber na alçada
def fracionamento(b: Bases, A: pd.DataFrame):
    out = []
    dup_ok = set(zip(b.duplicatas.chave_acesso, b.duplicatas.n_dup))
    nf_chave = b.nfs.drop_duplicates(["raiz", "nf_norm"]).set_index(["raiz", "nf_norm"]).chave_acesso.to_dict()
    for (forn, dia), g in A.groupby(["fornecedor_id", "data_prevista"]):
        g = g[g.valor <= ALCADA_ANALISTA]          # só os pedaços que cabem sozinhos na alçada
        if len(g) < 2 or g.valor.sum() <= ALCADA_ANALISTA:
            continue
        # parcelas que existem de verdade na nota fiscal explicam a divisão; o resto é suspeito
        suspeitos = []
        for _, r in g.iterrows():
            ch = nf_chave.get((r.raiz, r.nf_norm))
            n_dup = str(r.parcela).split("/")[0].zfill(3)
            if ch is None or (ch, n_dup) not in dup_ok:
                suspeitos.append(r)
        if len(suspeitos) < 2 or sum(x.valor for x in suspeitos) <= ALCADA_ANALISTA:
            continue
        soma = sum(x.valor for x in suspeitos)
        for r in suspeitos:
            out.append(_ac(r, "FRACIONAMENTO", "alta", f"Pagamento dividido para caber na alçada ({r.razao_social})",
                           [f"{len(suspeitos)} títulos de até {brl2(ALCADA_ANALISTA)} para o mesmo fornecedor no mesmo dia, somando {brl2(soma)}",
                            "as parcelas não existem na nota fiscal",
                            "política: a alçada vale pela soma; dividir para caber é ação indevida"],
                           agente="Auditor", perda=0.0, soma=soma))
    return out


# ------------------------------------------------------------ quem lançou não podia lançar
def lancador_invalido(b: Bases, A: pd.DataFrame):
    out = []
    u = b.usuarios.drop_duplicates("login").set_index("login")
    for _, r in A.iterrows():
        if r.lancado_por not in u.index:
            out.append(_ac(r, "LANCADOR_INVALIDO", "alta", "Título lançado por usuário desconhecido",
                           [f"usuário '{r.lancado_por}' não existe no cadastro de usuários do ERP"], agente="Auditor"))
            continue
        x = u.loc[r.lancado_por]
        desl = pd.to_datetime(x.get("data_desligamento"), errors="coerce")
        quando = pd.to_datetime(r.data_lancamento, errors="coerce")
        if pd.notna(desl) and pd.notna(quando) and quando > desl:
            out.append(_ac(r, "LANCADOR_INVALIDO", "critica", f"Título lançado depois que o usuário saiu da empresa",
                           [f"{x.nome} ({r.lancado_por}) foi desligado em {desl:%d/%m/%Y}; o título foi lançado em {quando:%d/%m/%Y}",
                            "acesso que deveria estar bloqueado"], agente="Auditor", perda=float(r.valor)))
        elif str(x.get("perfil")) not in PERFIS_QUE_LANCAM:
            out.append(_ac(r, "LANCADOR_INVALIDO", "alta", "Título lançado por quem não é do contas a pagar",
                           [f"{x.nome} ({x.cargo}, perfil '{x.perfil}') lançou o título", "segregação de funções"],
                           agente="Auditor"))
    return out


# ------------------------------------------------------------ contrato recorrente cobrado acima do valor
def acima_do_contrato(b: Bases, A: pd.DataFrame):
    out = []
    c = b.contratos[b.contratos.valor_variavel.astype(str).str.lower() == "não"]
    por_oc = c.dropna(subset=["oc_id"]).drop_duplicates("oc_id").set_index("oc_id")
    for _, r in A[A.oc_id.isin(por_oc.index)].iterrows():
        ct = por_oc.loc[r.oc_id]
        lim = ct.valor_mensal + max(ct.valor_mensal * 0.01, 50)
        if r.valor > lim:
            out.append(_ac(r, "ACIMA_DO_CONTRATO", "alta", f"Cobrança acima do contrato ({r.razao_social})",
                           [f"contrato {ct.contrato_id}: {brl2(ct.valor_mensal)} por mês, valor fixo",
                            f"título: {brl2(r.valor)} (a mais: {brl2(r.valor - ct.valor_mensal)})"],
                           perda=float(r.valor - ct.valor_mensal), gestor=ct.get("gestor_pessoa_id")))
    return out


# ------------------------------------------------------------ fornecedor bloqueado ou inativo
def fornecedor_inativo(b: Bases, A: pd.DataFrame):
    out = []
    st = b.fornecedores.drop_duplicates("fornecedor_id").set_index("fornecedor_id")
    if "status_cadastro" not in st.columns:
        return out
    for _, r in A.iterrows():
        s = str(st.status_cadastro.get(r.fornecedor_id, "ativo")).lower()
        if s not in ("ativo", "nan"):
            out.append(_ac(r, "FORNECEDOR_INATIVO", "alta", f"Pagamento para fornecedor '{s}' ({r.razao_social})",
                           [f"cadastro do fornecedor está '{s}' no ERP"], perda=float(r.valor)))
    return out


EXTRAS = [boleto_no_dda, nota_invalida, sem_recebimento, fracionamento, lancador_invalido, acima_do_contrato,
          fornecedor_inativo]
