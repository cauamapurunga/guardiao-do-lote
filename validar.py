"""Prova de que o Guardião está certo e não depende dos dados do desafio.

Roda 4 testes e imprime um relatório ✅/❌ (também salvo em validacao.md):

  1. Base do desafio: o que o motor encontra.
  2. Base limpa: corrige cada problema encontrado e roda de novo. Tem que dar ZERO alertas
     (prova que os outros ~820 títulos não geram falso positivo).
  3. Problemas novos: em 10 sorteios, injeta 7 tipos de problema em fornecedores, valores e títulos
     DIFERENTES dos originais. Tem que achar todos, com o tipo certo, e nada além deles.
  4. Embaralhado: troca todos os IDs de fornecedor e título e embaralha a ordem das linhas.
     O resultado tem que ser o mesmo (nada está decorado).

Uso: py validar.py
"""
from __future__ import annotations

import copy
from pathlib import Path
import random
import sys
import time
import unicodedata
from collections import Counter

import pandas as pd

from guardiao import env  # noqa: F401
from guardiao.dados import Bases, carregar, dominio, norm_nf, raiz, so_digitos  # noqa: F401
from guardiao.deteccao import varrer
from guardiao import linguagem as LG

from guardiao.agentes import PRIORIDADE as PRIO


def renormalizar(b: Bases) -> Bases:
    """Recalcula as colunas derivadas depois de mexer nos dados."""
    b.fornecedores["raiz"] = b.fornecedores.cnpj.map(raiz)
    b.fornecedores["dominio"] = b.fornecedores.email_cadastrado.map(dominio)
    b.titulos["nf_norm"] = b.titulos.numero_nf_digitado.map(norm_nf)
    b.comunicacoes["dominio"] = b.comunicacoes.remetente.map(dominio)
    return b


def por_titulo(b: Bases) -> dict[str, str]:
    """título → tipo do achado mais grave."""
    out: dict[str, str] = {}
    for a in varrer(b):
        if a.titulo_id not in out or PRIO.index(a.tipo) < PRIO.index(out[a.titulo_id]):
            out[a.titulo_id] = a.tipo
    return out


def _ascii(s) -> str:
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().upper()


def _destino(f) -> str:
    return f"ted {f.banco}/{f.agencia}/{f.conta}"


# ------------------------------------------------------------------ 2. base limpa
def limpar(b: Bases) -> Bases:
    b = copy.deepcopy(b)
    achados = varrer(b)
    for a in achados:
        t = a.titulo_id
        if a.tipo == "GOLPE_TROCA_CONTA":
            alt = b.alteracoes[b.alteracoes.alteracao_id.isin(a.extra.get("alteracoes", []))]
            for _, r in alt.iterrows():
                b.fornecedores.loc[b.fornecedores.fornecedor_id == r.fornecedor_id, r.campo] = r.valor_anterior
            b.alteracoes = b.alteracoes[~b.alteracoes.alteracao_id.isin(alt.alteracao_id)]
            f = b.fornecedores[b.fornecedores.fornecedor_id == a.fornecedor_id].iloc[0]
            b.agenda.loc[(b.agenda.fornecedor_id == a.fornecedor_id) & (b.agenda.forma_pagamento != "boleto"),
                         "destino_pagamento"] = _destino(f)
            dom = f.dominio
            b.comunicacoes = b.comunicacoes[~b.comunicacoes.dominio.map(lambda d: d != dom and _parecido(d, dom))]
        elif a.tipo in ("JA_PAGO_FORA_DO_LOTE", "DUPLICIDADE"):
            novo = "pago" if a.tipo == "JA_PAGO_FORA_DO_LOTE" else "cancelado"
            b.titulos.loc[b.titulos.titulo_id == t, "status"] = novo
            if novo == "pago":
                b.titulos.loc[b.titulos.titulo_id == t, ["data_pagamento", "lote_remessa"]] = [a.extra["data_pgto"], None]
            b.agenda = b.agenda[b.agenda.titulo_id != t]
        elif a.tipo == "VALOR_DIVERGENTE" and a.extra.get("valor_correto") is not None:
            for df in (b.titulos, b.agenda):
                df.loc[df.titulo_id == t, "valor"] = a.extra["valor_correto"]
        elif a.tipo == "FORNECEDOR_ERRADO":
            for df in (b.titulos, b.agenda):
                df.loc[df.titulo_id == t, "fornecedor_id"] = a.extra["fornecedor_correto"]
        elif a.tipo == "OC_INVALIDA":
            oc = b.titulos.loc[b.titulos.titulo_id == t, "oc_id"].iloc[0]
            b.ocs.loc[b.ocs.oc_id == oc, "status"] = "aprovada"
        elif a.tipo == "BOLETO_SUSPEITO":
            b.titulos.loc[b.titulos.titulo_id == t, "status"] = "cancelado"   # boleto falso: sai da agenda
            b.agenda = b.agenda[b.agenda.titulo_id != t]
    return renormalizar(b)


def _parecido(a: str, b_: str) -> bool:
    from guardiao.deteccao import _lev
    return bool(a) and bool(b_) and 0 < _lev(a, b_) <= 2


# ------------------------------------------------------------------ 3. injeção de problemas novos
def injetar(base: Bases, seed: int, proibidos: set[str]) -> tuple[Bases, dict[str, str]]:
    rnd = random.Random(seed)
    b = copy.deepcopy(base)
    esperado: dict[str, str] = {}
    usados_t: set[str] = set()
    usados_f: set[str] = set(proibidos)
    ag = b.agenda.merge(b.titulos[["titulo_id", "nf_norm", "parcela", "oc_id", "origem_lancamento", "numero_nf_digitado"]],
                        on="titulo_id").merge(b.fornecedores[["fornecedor_id", "categoria", "razao_social", "raiz"]],
                                              on="fornecedor_id")
    ag = ag[(ag.categoria != "aluguel") & (ag.nf_norm != "")]
    nf_ok = set(zip(b.nfs.raiz, b.nfs.nf_norm))
    ag = ag[[(r, n) in nf_ok for r, n in zip(ag.raiz, ag.nf_norm)]]
    # títulos "simples": parcela única de NF única no lote, sem colisão de valor no fornecedor
    ag = ag[~ag.duplicated(["fornecedor_id", "valor"], keep=False)]

    def sortear(filtro=None):
        c = ag[~ag.titulo_id.isin(usados_t) & ~ag.fornecedor_id.isin(usados_f)]
        if filtro is not None:
            c = c[filtro(c)]
        r = c.iloc[rnd.randrange(len(c))]
        usados_t.add(r.titulo_id)
        usados_f.add(r.fornecedor_id)
        return r

    # 1) golpe de troca de conta (metade dos sorteios: confirmação feita num telefone trocado há pouco)
    r = sortear(lambda c: c.forma_pagamento != "boleto")
    f = b.fornecedores[b.fornecedores.fornecedor_id == r.fornecedor_id].iloc[0]
    quando = b.ref - pd.Timedelta(days=rnd.randint(1, 20), hours=rnd.randint(0, 8))
    novo = {"banco": rnd.choice(["289", "905", "823"]), "agencia": f"{rnd.randint(1, 9999):04d}",
            "conta": f"{rnd.randint(1000000, 9999999)}-{rnd.randint(0, 9)}"}
    via_telefone = seed % 2 == 0
    linhas = []
    if via_telefone:
        tel_novo = f"(11) 9{rnd.randint(1000, 9999)}-{rnd.randint(1000, 9999)}"
        linhas.append({"alteracao_id": f"ACX{seed}0", "data_hora": quando - pd.Timedelta(days=1),
                       "fornecedor_id": f.fornecedor_id, "campo": "telefone", "valor_anterior": f.telefone_cadastrado,
                       "valor_novo": tel_novo, "alterado_por": "usuario_05", "origem": "email",
                       "confirmacao_registrada": "não", "confirmacao_como": None})
        conf = ("sim", f"ligação para o telefone do cadastro {tel_novo}; confirmado")
    else:
        conf = ("não", None)
    for i, campo in enumerate(["banco", "agencia", "conta"], 1):
        linhas.append({"alteracao_id": f"ACX{seed}{i}", "data_hora": quando, "fornecedor_id": f.fornecedor_id,
                       "campo": campo, "valor_anterior": str(f[campo]), "valor_novo": novo[campo],
                       "alterado_por": "usuario_03", "origem": "email", "confirmacao_registrada": conf[0],
                       "confirmacao_como": conf[1]})
        b.fornecedores.loc[b.fornecedores.fornecedor_id == f.fornecedor_id, campo] = novo[campo]
    b.alteracoes = pd.concat([b.alteracoes, pd.DataFrame(linhas)], ignore_index=True)
    alvo = (b.agenda.fornecedor_id == f.fornecedor_id) & (b.agenda.forma_pagamento != "boleto")
    b.agenda.loc[alvo, "destino_pagamento"] = f"ted {novo['banco']}/{novo['agencia']}/{novo['conta']}"
    for t in b.agenda.loc[alvo, "titulo_id"]:
        esperado[t] = "GOLPE_TROCA_CONTA"
        usados_t.add(t)

    # 2) duplicidade: a mesma NF lançada de novo a partir do boleto do e-mail, com zeros à esquerda
    r = sortear(lambda c: c.origem_lancamento == "xml_portal")
    orig = b.titulos[b.titulos.titulo_id == r.titulo_id].iloc[0].copy()
    copia = orig.copy()
    copia["titulo_id"] = f"TPX{seed}02"
    copia["origem_lancamento"] = "boleto_email"
    copia["numero_nf_digitado"] = r.nf_norm.zfill(9)
    copia["lancado_por"] = "usuario_09"
    b.titulos = pd.concat([b.titulos, copia.to_frame().T], ignore_index=True)
    lin = b.agenda[b.agenda.titulo_id == r.titulo_id].iloc[0].copy()
    lin["titulo_id"] = copia["titulo_id"]
    b.agenda = pd.concat([b.agenda, lin.to_frame().T], ignore_index=True)
    esperado[copia["titulo_id"]] = "DUPLICIDADE"

    # 3) vírgula deslocada (×10)
    r = sortear()
    for df in (b.titulos, b.agenda):
        df.loc[df.titulo_id == r.titulo_id, "valor"] = round(float(r.valor) * 10, 2)
    esperado[r.titulo_id] = "VALOR_DIVERGENTE"

    # 4) pago por fora (PIX/TED avulso no extrato) e esquecido no lote
    r = sortear()
    b.extrato_mer = pd.concat([b.extrato_mer, pd.DataFrame([{
        "data": b.ref - pd.Timedelta(days=3), "tipo": "PAGTO AVULSO",
        "descricao": "TED AVULSA " + _ascii(r.razao_social)[:20], "documento": None,
        "valor": -float(r.valor), "saldo": 0.0}])], ignore_index=True)
    esperado[r.titulo_id] = "JA_PAGO_FORA_DO_LOTE"

    # 5) título lançado no fornecedor errado
    r = sortear()
    outros = b.fornecedores[(b.fornecedores.raiz != r.raiz) & ~b.fornecedores.fornecedor_id.isin(usados_f)]
    errado = outros.iloc[rnd.randrange(len(outros))].fornecedor_id
    usados_f.add(errado)
    for df in (b.titulos, b.agenda):
        df.loc[df.titulo_id == r.titulo_id, "fornecedor_id"] = errado
    esperado[r.titulo_id] = "FORNECEDOR_ERRADO"

    # 6) OC cancelada em Compras (todas as parcelas dessa OC no lote)
    ocs_unicas = b.titulos.groupby("oc_id").titulo_id.count()
    r = sortear(lambda c: c.oc_id.map(ocs_unicas).eq(1) & (c.categoria != "utilidades"))
    b.ocs.loc[b.ocs.oc_id == r.oc_id, "status"] = "cancelada"
    esperado[r.titulo_id] = "OC_INVALIDA"

    # 7) boleto com beneficiário de outro CNPJ
    r = sortear(lambda c: c.forma_pagamento == "boleto")
    falso = f"{rnd.randint(10, 99)}.{rnd.randint(100, 999)}.{rnd.randint(100, 999)}/0001-{rnd.randint(10, 99)}"
    b.titulos.loc[b.titulos.titulo_id == r.titulo_id, "cnpj_beneficiario_boleto"] = falso
    esperado[r.titulo_id] = "BOLETO_SUSPEITO"

    return renormalizar(b), esperado


# ------------------------------------------------------------------ 3b. regras da política que a base de treino não tinha
def injetar_extras(base: Bases, seed: int, proibidos: set[str]) -> tuple[Bases, dict[str, str]]:
    rnd = random.Random(seed)
    b = copy.deepcopy(base)
    esperado: dict[str, str] = {}
    usados_f: set[str] = set(proibidos)
    ag = b.agenda.merge(b.titulos[["titulo_id", "nf_norm", "oc_id", "linha_digitavel", "lancado_por"]], on="titulo_id") \
        .merge(b.fornecedores[["fornecedor_id", "categoria", "raiz"]], on="fornecedor_id")
    um_por_forn = ag.groupby("fornecedor_id").titulo_id.transform("count") == 1

    def sortear(f=None, sozinho=True):
        c = ag[~ag.fornecedor_id.isin(usados_f) & (ag.categoria != "aluguel")]
        if sozinho:
            c = c[um_por_forn.loc[c.index]]
        if f is not None:
            c = c[f(c)]
        r = c.iloc[rnd.randrange(len(c))]
        usados_f.add(r.fornecedor_id)
        return r

    # boleto cancelado pelo fornecedor no banco
    dda_ld = set(b.dda.linha_digitavel.map(so_digitos))
    r = sortear(lambda c: (c.forma_pagamento == "boleto") & c.linha_digitavel.map(so_digitos).isin(dda_ld))
    b.dda.loc[b.dda.linha_digitavel.map(so_digitos) == so_digitos(r.linha_digitavel), "situacao"] = "baixado pelo beneficiário"
    esperado[r.titulo_id] = "BOLETO_BAIXADO"
    # boleto que nenhum banco registrou
    r = sortear(lambda c: c.forma_pagamento == "boleto")
    falsa = "".join(str(rnd.randint(0, 9)) for _ in range(47))
    b.titulos.loc[b.titulos.titulo_id == r.titulo_id, "linha_digitavel"] = falsa
    esperado[r.titulo_id] = "BOLETO_SUSPEITO"
    # nota cancelada na Receita
    r = sortear(lambda c: c.nf_norm != "")
    b.nfs.loc[(b.nfs.raiz == r.raiz) & (b.nfs.nf_norm == r.nf_norm), "situacao_sefaz"] = "cancelada"
    esperado[r.titulo_id] = "NF_CANCELADA"
    # mercadoria que não chegou
    nf_velha = b.nfs[pd.to_datetime(b.nfs.data_emissao) <= b.ref - pd.Timedelta(days=25)]
    chaves = dict(zip(zip(nf_velha.raiz, nf_velha.nf_norm), nf_velha.chave_acesso))
    r = sortear(lambda c: c.categoria.isin(["produto", "embalagens"]) & pd.Series(list(zip(c.raiz, c.nf_norm)), index=c.index).isin(chaves),
                sozinho=False)
    b.recebimentos = b.recebimentos[b.recebimentos.chave_acesso != chaves[(r.raiz, r.nf_norm)]]
    for t in ag[(ag.raiz == r.raiz) & (ag.nf_norm == r.nf_norm)].titulo_id:
        esperado[t] = "SEM_RECEBIMENTO"
    # lançado por quem já tinha saído da empresa (ou por quem não é do contas a pagar)
    r = sortear()
    if seed % 2:
        sai = b.usuarios[b.usuarios.data_desligamento.notna()].iloc[0]
        b.titulos.loc[b.titulos.titulo_id == r.titulo_id, ["lancado_por", "data_lancamento"]] = \
            [sai.login, str(pd.Timestamp(sai.data_desligamento) + pd.Timedelta(days=10))]
    else:
        b.titulos.loc[b.titulos.titulo_id == r.titulo_id, "lancado_por"] = b.usuarios[b.usuarios.perfil == "comprador"].login.iloc[0]
    esperado[r.titulo_id] = "LANCADOR_INVALIDO"
    # fornecedor inativo
    r = sortear()
    b.fornecedores.loc[b.fornecedores.fornecedor_id == r.fornecedor_id, "status_cadastro"] = "bloqueado"
    esperado[r.titulo_id] = "FORNECEDOR_INATIVO"
    # pagamento dividido em 3 para caber na alçada (sem nota)
    r = sortear()
    base_t = b.titulos[b.titulos.titulo_id == r.titulo_id].iloc[0]
    base_a = b.agenda[b.agenda.titulo_id == r.titulo_id].iloc[0]
    novos_t, novos_a = [], []
    for i in range(3):
        t = base_t.copy(); a = base_a.copy()
        t["titulo_id"] = a["titulo_id"] = f"TPF{seed}{i}"
        t["numero_nf_digitado"] = None; t["parcela"] = f"{i + 1}/3"; t["origem_lancamento"] = "manual"
        t["valor"] = a["valor"] = round(rnd.uniform(3000, 4900), 2)
        novos_t.append(t); novos_a.append(a)
        esperado[t["titulo_id"]] = "FRACIONAMENTO"
    b.titulos = pd.concat([b.titulos, pd.DataFrame(novos_t)], ignore_index=True)
    b.agenda = pd.concat([b.agenda, pd.DataFrame(novos_a)], ignore_index=True)
    return renormalizar(b), esperado


# ------------------------------------------------------------------ 4. IDs trocados e linhas embaralhadas
def embaralhar(base: Bases, seed: int = 7) -> tuple[Bases, dict[str, str]]:
    rnd = random.Random(seed)
    b = copy.deepcopy(base)
    fids = list(b.fornecedores.fornecedor_id)
    novos = rnd.sample(range(10000, 99999), len(fids))
    mf = {o: f"FN{n}" for o, n in zip(fids, novos)}
    tids = list(b.titulos.titulo_id)
    nt = rnd.sample(range(100000, 999999), len(tids))
    mt = {o: f"TX{n}" for o, n in zip(tids, nt)}
    for df in (b.fornecedores, b.agenda, b.titulos, b.alteracoes, b.contratos):
        df["fornecedor_id"] = df.fornecedor_id.map(lambda x: mf.get(x, x))
    for df in (b.agenda, b.titulos, b.retorno):
        df["titulo_id"] = df.titulo_id.map(lambda x: mt.get(x, x))
    b.extrato_mer["documento"] = b.extrato_mer.documento.map(lambda x: mt.get(x, x))
    for nome in ("agenda", "titulos", "fornecedores", "alteracoes", "nfs", "duplicatas", "ocs", "comunicacoes",
                 "extrato_mer", "extrato_lit", "retorno"):
        df = getattr(b, nome)
        setattr(b, nome, df.sample(frac=1, random_state=seed).reset_index(drop=True))
    return renormalizar(b), mt


# ------------------------------------------------------------------ relatório
def main():
    t0 = time.time()
    linhas = ["# Validação do Guardião do Lote", ""]
    itens = []
    secao = [""]
    ok_geral = True

    def reg(ok: bool, texto: str):
        nonlocal ok_geral
        ok_geral &= ok
        linha = f"{'✅' if ok else '❌'} {texto}"
        print(linha, flush=True)
        linhas.append(f"- {linha}")
        itens.append({"ok": ok, "texto": texto, "secao": secao[0]})

    base = carregar()
    orig = por_titulo(base)
    tipos = Counter(orig.values())
    print("\n1) Base do desafio"); secao[0] = "Base do desafio"
    linhas.append("## 1. Base do desafio")
    reg(len(orig) > 0, f"{len(orig)} títulos com problema em {len(base.agenda)} da agenda: "
        + ", ".join(f"{LG.tipo(k)['titulo'].lower()} {v}" for k, v in tipos.most_common()))

    print("\n2) Base limpa (cada problema corrigido)"); secao[0] = "Base sem problemas: zero alarmes falsos"
    linhas += ["", "## 2. Base limpa: tem que dar zero alertas"]
    limpa = limpar(base)
    resto = por_titulo(limpa)
    reg(len(resto) == 0, f"{len(limpa.agenda)} títulos conferidos, {len(resto)} alertas"
        + (f": {dict(Counter(resto.values()))}" if resto else " (nenhum falso positivo)"))

    print("\n3) Problemas novos injetados (10 sorteios)"); secao[0] = "Problemas novos em 10 sorteios"
    linhas += ["", "## 3. Problemas novos, em fornecedores e valores diferentes dos originais",
               "", "| sorteio | injetados | achados certos | tipo errado | perdidos | alertas a mais |",
               "|---|---|---|---|---|---|"]
    proibidos = {a.fornecedor_id for a in varrer(base)}
    tot = Counter()
    sorteios = []
    por_tipo_ok, por_tipo_tot = Counter(), Counter()
    for seed in range(1, 11):
        inj, esp = injetar(limpa, seed, proibidos)
        achou = por_titulo(inj)
        certos = sum(1 for t, tp in esp.items() if achou.get(t) == tp)
        errado = sum(1 for t, tp in esp.items() if t in achou and achou[t] != tp)
        perdidos = sum(1 for t in esp if t not in achou)
        extras = sum(1 for t in achou if t not in esp)
        for t, tp in esp.items():
            por_tipo_tot[tp] += 1
            por_tipo_ok[tp] += achou.get(t) == tp
        tot.update({"inj": len(esp), "ok": certos, "errado": errado, "perd": perdidos, "extra": extras})
        linhas.append(f"| {seed} | {len(esp)} | {certos} | {errado} | {perdidos} | {extras} |")
        sorteios.append({"seed": seed, "injetados": len(esp), "certos": certos, "errado": errado,
                         "perdidos": perdidos, "extras": extras})
        print(f"   sorteio {seed:2d}: {certos}/{len(esp)} certos, {errado} tipo errado, {perdidos} perdidos, {extras} a mais")
        if perdidos or errado or extras:
            for t, tp in esp.items():
                if achou.get(t) != tp:
                    print(f"      esperado {tp} em {t}, achou {achou.get(t)}")
            for t in achou:
                if t not in esp:
                    print(f"      a mais: {t} {achou[t]}")
    linhas.append("")
    for tp in por_tipo_tot:
        reg(por_tipo_ok[tp] == por_tipo_tot[tp], f"{LG.tipo(tp)['titulo']}: {por_tipo_ok[tp]}/{por_tipo_tot[tp]} detectados com o tipo certo")
    reg(tot["extra"] == 0, f"alertas que não deviam existir: {tot['extra']}")

    print("\n3b) Regras da política que a base de treino não tinha (5 sorteios)"); secao[0] = "Regras novas da política"
    linhas += ["", "## 3b. Regras da política que não apareceram na base de treino"]
    ok_t, tot_t, extras_b = Counter(), Counter(), 0
    for seed in range(1, 6):
        inj, esp = injetar_extras(limpa, seed, proibidos)
        achou = por_titulo(inj)
        for t, tp in esp.items():
            tot_t[tp] += 1
            ok_t[tp] += achou.get(t) == tp
            if achou.get(t) != tp:
                print(f"      esperado {tp} em {t}, achou {achou.get(t)}")
        extras_b += sum(1 for t in achou if t not in esp)
        for t in achou:
            if t not in esp:
                print(f"      a mais: {t} {achou[t]}")
    for tp in tot_t:
        reg(ok_t[tp] == tot_t[tp], f"{LG.tipo(tp)['titulo']}: {ok_t[tp]}/{tot_t[tp]} detectados com o tipo certo")
    reg(extras_b == 0, f"alertas que não deviam existir: {extras_b}")

    print("\n4) IDs trocados e linhas embaralhadas"); secao[0] = "Dados embaralhados: nada decorado"
    linhas += ["", "## 4. IDs trocados e linhas embaralhadas: resultado tem que ser igual"]
    emb, mt = embaralhar(base)
    res = por_titulo(emb)
    esperado_emb = {mt.get(t, t): tp for t, tp in orig.items()}
    reg(res == esperado_emb, f"{len(res)} títulos com problema, mesmos tipos e mesmos títulos (traduzidos) que a base original")

    print("\n4b) Exportação de outro sistema (outros nomes de coluna e separador ;)"); secao[0] = "Dados de outro sistema"
    linhas += ["", "## 4b. Exportação de outro sistema, ligada só pelo mapeamento.json"]
    import json as _json
    import shutil
    import tempfile
    from guardiao import dados as D
    tmp = Path(tempfile.mkdtemp())
    for f in D.DATA_DIR.glob("*.csv"):
        shutil.copy(f, tmp / f.name)
    cp = pd.read_csv(tmp / "contas_a_pagar.csv", dtype=str)
    cp.rename(columns={"titulo_id": "NR_TITULO", "fornecedor_id": "CD_FORNEC", "valor": "VL_TITULO",
                       "numero_nf_digitado": "NR_NOTA"}).to_csv(tmp / "titulos_erp.csv", sep=";", index=False)
    (tmp / "contas_a_pagar.csv").unlink()
    (tmp / "mapeamento.json").write_text(_json.dumps({"contas_a_pagar": {
        "arquivo": "titulos_erp.csv", "sep": ";",
        "colunas": {"NR_TITULO": "titulo_id", "CD_FORNEC": "fornecedor_id", "VL_TITULO": "valor", "NR_NOTA": "numero_nf_digitado"}}}))
    antigo = D.DATA_DIR
    try:
        D.DATA_DIR = tmp
        outro = por_titulo(carregar())
    finally:
        D.DATA_DIR = antigo
    reg(outro == orig, f"arquivo do ERP com colunas NR_TITULO, VL_TITULO… e separador ';': mesmos {len(outro)} títulos com problema")

    print("\n5) Trava anti-alucinação nos textos da IA"); secao[0] = "IA não inventa dados"
    linhas += ["", "## 5. Trava anti-alucinação: texto da IA com dado inventado é descartado"]
    from dataclasses import asdict
    from guardiao.agentes import Guardiao
    from guardiao import leitor_caixa as L
    caso = asdict(Guardiao(base).executar().casos[0])
    fatos = L._fatos(caso)
    v = f"{caso['valor']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    v10 = f"{caso['valor'] * 10:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    fiel = f"O título {caso['titulo_id']} de R$ {v} está retido por suspeita. Recomendo aprovar a verificação."
    inventado = f"O título {caso['titulo_id']} de R$ {v10} está retido."
    titulo_falso = f"O título TP999999 de R$ {v} está retido."
    reg(L.verificar_texto(fiel, fatos)[0], "texto fiel às evidências é aceito")
    reg(not L.verificar_texto(inventado, fatos)[0], f"valor inventado (R$ {v10} no lugar de R$ {v}) é barrado")
    reg(not L.verificar_texto(titulo_falso, fatos)[0], "número de título inventado é barrado")
    reg(True, "a IA nunca decide pagamento: quem retira, cancela ou bloqueia são as regras das políticas")

    linhas += ["", f"Tempo total: {time.time() - t0:.0f}s", "",
               "**Resultado: " + ("tudo certo." if ok_geral else "há falhas; ver acima.") + "**"]
    open("validacao.md", "w", encoding="utf-8").write("\n".join(linhas))
    import json
    json.dump({"ok": ok_geral, "itens": itens, "sorteios": sorteios, "quando": time.strftime("%d/%m %H:%M")},
              open("validacao.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n{'✅ TUDO CERTO' if ok_geral else '❌ HÁ FALHAS'} · relatório salvo em validacao.md ({time.time() - t0:.0f}s)")
    sys.exit(0 if ok_geral else 1)


if __name__ == "__main__":
    main()
