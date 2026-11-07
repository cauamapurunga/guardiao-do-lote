"""Checagens genéricas sobre cada título da agenda de remessa.

Nenhuma regra é amarrada a ID de fornecedor ou título: tudo vem de cruzamento entre sistemas
(ERP x Compras x NF-e x DDA x bancos x caixa de e-mail) e das políticas.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from .dados import Bases, raiz, so_digitos
from .dados import brl2

TOL_ARREDONDAMENTO = 0.10
JANELA_TROCA_BANCARIA_DIAS = 30


@dataclass
class Achado:
    tipo: str                 # código do problema
    titulo_id: str
    fornecedor_id: str
    valor: float
    lote: str
    fechamento: str
    severidade: str           # critica, alta, media
    resumo: str
    evidencias: list[str] = field(default_factory=list)
    agente: str = "Analista"  # quem detectou
    perda_evitavel: float = 0.0   # quanto sairia indevidamente se nada fosse feito
    extra: dict = field(default_factory=dict)


def _lev(a: str, b: str) -> int:
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _base_agenda(b: Bases) -> pd.DataFrame:
    t = b.titulos[["titulo_id", "nf_norm", "numero_nf_digitado", "parcela", "oc_id", "linha_digitavel",
                   "cnpj_beneficiario_boleto", "origem_lancamento", "lancado_por", "data_lancamento"]]
    f = b.fornecedores[["fornecedor_id", "raiz", "razao_social", "categoria", "banco", "agencia", "conta",
                        "dominio", "email_cadastrado", "telefone_cadastrado", "contrato_id"]]
    return b.agenda.merge(t, on="titulo_id", how="left").merge(f, on="fornecedor_id", how="left")


def _achado(r, tipo, sev, resumo, ev, agente="Analista", perda=0.0, **extra) -> Achado:
    return Achado(tipo, r.titulo_id, r.fornecedor_id, float(r.valor), r.lote_remessa,
                  f"{r.data_prevista:%d/%m} {r.horario_fechamento}", sev, resumo, ev, agente, perda, extra)


# ---------------------------------------------------------------- 1. troca bancária suspeita
def troca_bancaria_suspeita(b: Bases, A: pd.DataFrame) -> list[Achado]:
    al = b.alteracoes
    bancarios = al[al.campo.isin(["banco", "agencia", "conta", "chave_pix"])]
    recentes = bancarios[bancarios.data_hora >= b.ref - pd.Timedelta(days=JANELA_TROCA_BANCARIA_DIAS)]
    tel_trocado = al[(al.campo == "telefone") & (al.data_hora >= b.ref - pd.Timedelta(days=JANELA_TROCA_BANCARIA_DIAS))]
    dominios_oficiais = set(b.fornecedores.dominio) - {""}
    out = []
    suspeitos: dict[str, tuple] = {}
    # cada troca (fornecedor + momento) é avaliada sozinha: um fornecedor pode ter uma troca legítima e outra fraudulenta
    for (forn, _), g in recentes.sort_values("data_hora").groupby(["fornecedor_id", "data_hora"]):
        motivos = []
        conf = g.confirmacao_registrada.iloc[0]
        como = str(g.confirmacao_como.iloc[0]) if pd.notna(g.confirmacao_como.iloc[0]) else ""
        if conf != "sim":
            motivos.append("alteração bancária SEM confirmação registrada")
        elif "ligação" not in como.lower():
            motivos.append(f"confirmação não foi por ligação ao telefone anterior ('{como[:60]}')")
        else:
            tel_conf = re.findall(r"\(\d{2}\) ?\d{4,5}-\d{4}", como)
            novos = set(tel_trocado[tel_trocado.fornecedor_id == forn].valor_novo)
            if tel_conf and tel_conf[0] in novos:
                motivos.append(f"confirmação feita em telefone trocado há menos de 30 dias ({tel_conf[0]})")
        # e-mail que originou o pedido veio de domínio parecido com o oficial?
        f = b.fornecedores[b.fornecedores.fornecedor_id == forn].iloc[0]
        quando = g.data_hora.iloc[0]
        msgs = b.comunicacoes[(b.comunicacoes.data_hora <= quando) &
                              (b.comunicacoes.data_hora >= quando - pd.Timedelta(days=5)) &
                              (b.comunicacoes.texto.str.contains("banc|conta", case=False, regex=True))]
        for _, m in msgs.iterrows():
            d = m.dominio
            if d and d not in dominios_oficiais and f.dominio and 0 < _lev(d, f.dominio) <= 2:
                motivos.append(f"pedido veio de '{m.remetente}' — domínio parecido com o oficial '{f.dominio}' ({m.comunicacao_id})")
        if motivos:
            suspeitos[forn] = (g, motivos, quando)   # a troca suspeita mais recente manda
    for forn, (g, motivos, quando) in suspeitos.items():
        alt_ids = ", ".join(g.alteracao_id)
        antes = "/".join(g.sort_values("campo").valor_anterior.astype(str))
        depois = "/".join(g.sort_values("campo").valor_novo.astype(str))
        tits = A[A.fornecedor_id == forn]
        for _, r in tits.iterrows():
            if r.forma_pagamento == "boleto":
                continue  # boleto vai ao beneficiário registrado, não à conta do cadastro
            ev = motivos + [f"alteração {alt_ids} em {quando:%d/%m %H:%M} por {g.alterado_por.iloc[0]} (origem: {g.origem.iloc[0]})",
                            f"conta {antes} → {depois}", f"destino do pagamento hoje: {r.destino_pagamento}"]
            out.append(_achado(r, "GOLPE_TROCA_CONTA", "critica",
                               f"Pagamento iria para conta trocada sem confirmação válida ({r.razao_social})",
                               ev, agente="Auditor", perda=float(r.valor),
                               alteracoes=list(g.alteracao_id), telefone_anterior=None))
    return out


# ---------------------------------------------------------------- 2. já pago fora do lote
def ja_pago_fora_do_lote(b: Bases, A: pd.DataFrame) -> list[Achado]:
    ret = b.retorno
    pagos_ok = ret[ret.codigo_ocorrencia.astype(str).str.zfill(2) == "00"]
    mer = b.extrato_mer[b.extrato_mer.tipo == "PAGTO AVULSO"].assign(v=lambda d: -d.valor, txt=lambda d: d.descricao, banco="Banco Meridiano")
    lit = b.extrato_lit[(b.extrato_lit["Valor (R$)"] < 0) & ~b.extrato_lit["Histórico"].str.startswith("TAR")]
    lit = lit.assign(v=-lit["Valor (R$)"], txt=lit["Histórico"], data=lit["Data"], banco="Banco Litoral")
    rl = pagos_ok[pagos_ok.lote_remessa.str.endswith("LIT")]
    chave_lote = set(zip(rl.data_pagamento, rl.valor_pago.round(2)))
    lit = lit[[(d, round(v, 2)) not in chave_lote for d, v in zip(lit.data, lit.v)]]
    deb = pd.concat([mer[["data", "v", "txt", "banco"]], lit[["data", "v", "txt", "banco"]]])
    pg = b.titulos[(b.titulos.status == "pago") & b.titulos.lote_remessa.isna()]
    baixados = set(zip(pd.to_datetime(pg.data_pagamento), pg.valor.round(2)))
    sem_baixa = deb[[(d, round(v, 2)) not in baixados for d, v in zip(deb.data, deb.v)]]
    out = []
    for _, d in sem_baixa.iterrows():
        txt = _ascii(d.txt)
        cand = A[(abs(A.valor - d.v) < 0.01)]
        cand = cand[[_ascii(rs).split()[0] in txt for rs in cand.razao_social]]
        for _, r in cand.iterrows():
            out.append(_achado(r, "JA_PAGO_FORA_DO_LOTE", "critica",
                               f"Título já foi pago por fora em {d.data:%d/%m} e continua no lote ({r.razao_social})",
                               [f"extrato {d.banco} {d.data:%d/%m}: '{d.txt}' {brl2(d.v)}",
                                "pagamento manual sem baixa no ERP (política: baixa no mesmo dia)"],
                               perda=float(r.valor), data_pgto=str(d.data.date()), banco_pgto=d.banco))
    return out


def b_path(b: Bases, nome: str):
    from . import dados
    return dados.DATA_DIR / f"{nome}.csv"


def _ascii(s) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().upper()


# ---------------------------------------------------------------- 3. duplicidade
def duplicidade(b: Bases, A: pd.DataFrame) -> list[Achado]:
    t = b.titulos[(b.titulos.status != "cancelado") & (b.titulos.nf_norm != "")]
    grupos = t[t.duplicated(["fornecedor_id", "nf_norm", "parcela"], keep=False)]
    out = []
    for (forn, nf, parc), g in grupos.groupby(["fornecedor_id", "nf_norm", "parcela"]):
        # mantém o lançado a partir do XML (fonte oficial); os demais são cópia
        g = g.assign(pref=(g.origem_lancamento != "xml_portal").astype(int)).sort_values(["pref", "data_lancamento"])
        manter = g.iloc[0]
        for _, d in g.iloc[1:].iterrows():
            r = A[A.titulo_id == d.titulo_id]
            if r.empty:
                continue
            r = r.iloc[0]
            out.append(_achado(r, "DUPLICIDADE", "alta",
                               f"NF {nf} parcela {parc} lançada 2x — {r.razao_social}",
                               [f"original {manter.titulo_id} ({manter.origem_lancamento}, {manter.lancado_por}, NF digitada '{manter.numero_nf_digitado}', {brl2(manter.valor)})",
                                f"cópia {d.titulo_id} ({d.origem_lancamento}, {d.lancado_por}, NF digitada '{d.numero_nf_digitado}', {brl2(d.valor)})",
                                "mesma NF normalizada (zeros/série removidos), mesmo fornecedor e parcela"],
                               perda=float(r.valor), original=manter.titulo_id))
    return out


# ---------------------------------------------------------------- 4/5. três vias: NF, duplicata, fornecedor, OC
def tres_vias(b: Bases, A: pd.DataFrame) -> list[Achado]:
    out = []
    nfs = b.nfs
    dup = b.duplicatas
    ocs = b.ocs.set_index("oc_id")
    forn_por_raiz = b.fornecedores.drop_duplicates("raiz").set_index("raiz")
    # índices em memória: busca O(1) por título (escala para dezenas de milhares de títulos)
    nf_idx = {k: g for k, g in nfs.groupby(["raiz", "nf_norm"], sort=False)}
    nf_por_num = {k: g for k, g in nfs.groupby("nf_norm", sort=False)}
    dup_idx = {(k1, k2): float(v) for k1, k2, v in zip(dup.chave_acesso, dup.n_dup, dup.valor)}
    dup_por_chave = {k: g for k, g in dup.groupby("chave_acesso", sort=False)}
    ocs = ocs[~ocs.index.duplicated()]
    ctr_idx = b.contratos.drop_duplicates("fornecedor_id").set_index("fornecedor_id").valor_mensal.to_dict()
    vazio = nfs.iloc[0:0]
    for _, r in A.iterrows():
        if r.categoria == "aluguel":
            vm = ctr_idx.get(r.fornecedor_id)
            if vm is not None and abs(vm - r.valor) > TOL_ARREDONDAMENTO:
                out.append(_achado(r, "VALOR_DIVERGENTE", "alta", "Aluguel diferente do contrato",
                                   [f"contrato {brl2(vm)} x título {brl2(r.valor)}"],
                                   perda=max(0.0, r.valor - vm)))
            continue
        if not r.nf_norm:
            out.append(_achado(r, "SEM_NF", "media", "Pagamento sem NF (exige aprovação dupla)", ["título sem número de NF"]))
            continue
        nf = nf_idx.get((r.raiz, r.nf_norm), vazio)
        if nf.empty:
            mesma_nf = nf_por_num.get(r.nf_norm, vazio)
            chaves_ok = {ch for ch in mesma_nf.chave_acesso
                         if ch in dup_por_chave and (abs(dup_por_chave[ch].valor - r.valor) < 1).any()}
            outra = mesma_nf[(abs(mesma_nf.valor_total - r.valor) < 1) | mesma_nf.chave_acesso.isin(chaves_ok)]
            if len(outra):
                o = outra.iloc[0]
                certo = forn_por_raiz.loc[o.raiz] if o.raiz in forn_por_raiz.index else None
                certo_id = certo.fornecedor_id if certo is not None else None
                out.append(_achado(r, "FORNECEDOR_ERRADO", "critica",
                                   f"Título lançado no fornecedor errado: NF é de {o.razao_social_emitente}",
                                   [f"NF {o.numero_nf} emitida por CNPJ {o.cnpj_emitente} ({o.razao_social_emitente})",
                                    f"título está em {r.fornecedor_id} {r.razao_social} (raiz {r.raiz})",
                                    f"fornecedor correto no ERP: {certo_id} {certo.razao_social if certo is not None else '?'}",
                                    f"pagamento sairia para {r.destino_pagamento} (conta de outra empresa)"],
                                   perda=float(r.valor), fornecedor_correto=certo_id))
            else:
                out.append(_achado(r, "NF_NAO_ENCONTRADA", "alta", "NF digitada não existe no portal",
                                   [f"NF '{r.numero_nf_digitado}' não encontrada para a raiz {r.raiz}"], perda=float(r.valor)))
            continue
        nf = nf.iloc[0]
        n_dup = str(r.parcela).split("/")[0].zfill(3)
        vd = dup_idx.get((nf.chave_acesso, n_dup))
        if vd is not None:
            dif = r.valor - vd
            if abs(dif) > TOL_ARREDONDAMENTO:
                razao = r.valor / vd if vd else 0
                virgula = abs(razao - 10) < 0.05 or abs(razao - 0.1) < 0.005
                out.append(_achado(r, "VALOR_DIVERGENTE", "alta" if virgula or abs(dif) > 1000 else "media",
                                   ("Erro de digitação (vírgula deslocada): " if virgula else "Valor diferente da duplicata: ")
                                   + f"{brl2(r.valor)} x {brl2(vd)}",
                                   [f"duplicata {n_dup} da NF {nf.numero_nf}: {brl2(vd)}",
                                    f"título digitado por {r.lancado_por}: {brl2(r.valor)} (diferença {brl2(dif)})"],
                                   perda=max(0.0, dif), valor_correto=vd, virgula=virgula))
        # OC
        if r.categoria != "utilidades":
            if pd.isna(r.oc_id) or r.oc_id not in ocs.index:
                out.append(_achado(r, "SEM_OC", "media", "Pagamento sem OC válida", [f"OC informada: {r.oc_id}"]))
            else:
                oc = ocs.loc[r.oc_id]
                if oc.status in ("cancelada", "pendente_aprovacao"):
                    out.append(_achado(r, "OC_INVALIDA", "alta", f"OC {r.oc_id} está {oc.status}",
                                       [f"OC {r.oc_id} ({oc.descricao}) status '{oc.status}' em Compras",
                                        f"comprador: {oc.comprador}"],
                                       perda=float(r.valor) if oc.status == "cancelada" else 0.0,
                                       comprador=oc.comprador, oc_status=oc.status))
                elif oc.tipo == "pontual":
                    lim = max(oc.valor_total * 0.02, 50)
                    if nf.valor_total - oc.valor_total > lim:
                        out.append(_achado(r, "NF_ACIMA_DA_OC", "media", "NF acima da OC além da tolerância",
                                           [f"NF {brl2(nf.valor_total)} x OC {brl2(oc.valor_total)}"], comprador=oc.comprador))
    return out


# ---------------------------------------------------------------- 6. boleto
def boleto(b: Bases, A: pd.DataFrame) -> list[Achado]:
    out = []
    hist = b.titulos[(b.titulos.forma_pagamento == "boleto") & (b.titulos.status == "pago")].copy()
    hist["banco_ld"] = hist.linha_digitavel.astype(str).str[:3]
    usuais = hist.groupby("fornecedor_id").banco_ld.agg(set).to_dict()
    for _, r in A[A.forma_pagamento == "boleto"].iterrows():
        ld = so_digitos(r.linha_digitavel)
        ev = []
        rb = raiz(r.cnpj_beneficiario_boleto) if pd.notna(r.cnpj_beneficiario_boleto) else ""
        if rb and rb != r.raiz and ((b.nfs.raiz == rb) & (b.nfs.nf_norm == r.nf_norm)).any():
            continue  # o boleto é do emitente real da NF: o erro é o fornecedor do título (tres_vias trata)
        if rb and rb != r.raiz:
            dono = b.fornecedores[b.fornecedores.raiz == raiz(r.cnpj_beneficiario_boleto)]
            ev.append(f"beneficiário do boleto CNPJ {r.cnpj_beneficiario_boleto} ≠ fornecedor {r.razao_social} "
                      f"({'cadastro: ' + dono.razao_social.iloc[0] if len(dono) else 'CNPJ fora do cadastro'})")
        if len(ld) == 47:
            banco_ld = ld[:3]
            us = usuais.get(r.fornecedor_id, set())
            if us and banco_ld not in us and banco_ld != str(r.banco):
                ev.append(f"boleto emitido pelo banco {banco_ld}; fornecedor sempre cobrou por {sorted(us)}")
        if ev:
            out.append(_achado(r, "BOLETO_SUSPEITO", "critica", f"Boleto com beneficiário/banco divergente ({r.razao_social})",
                               ev, agente="Auditor", perda=float(r.valor)))
    return out


CHECAGENS = [troca_bancaria_suspeita, ja_pago_fora_do_lote, duplicidade, tres_vias, boleto]


def varrer(b: Bases, lotes: list[str] | None = None) -> list[Achado]:
    A = _base_agenda(b)
    if lotes:
        A = A[A.lote_remessa.isin(lotes)]
    achados: list[Achado] = []
    for chk in CHECAGENS:
        achados.extend(chk(b, A))
    # um título pode ter vários achados; mantém todos (a orquestração decide a ação)
    return achados
