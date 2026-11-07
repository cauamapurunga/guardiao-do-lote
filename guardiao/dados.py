"""Carrega e normaliza as bases dos sistemas de Pagamentos (ERP, Compras, NF-e, DDA, bancos)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
REF = pd.Timestamp("2026-11-02 08:00:00")


def so_digitos(x) -> str:
    return re.sub(r"\D", "", str(x)) if pd.notna(x) else ""


def brl2(v) -> str:
    """R$ no formato brasileiro: R$ 1.234,56"""
    return "R$ " + f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def raiz(cnpj) -> str:
    return so_digitos(cnpj)[:8]


def norm_nf(x) -> str:
    """'000073535', '73535-1', '73535/1' -> '73535'."""
    if pd.isna(x) or str(x).strip() == "":
        return ""
    s = re.split(r"[-/]", str(x).strip())[0]
    s = so_digitos(s).lstrip("0")
    return s


def dominio(email) -> str:
    if pd.isna(email) or "@" not in str(email):
        return ""
    return str(email).split("@")[-1].lower().strip()


@dataclass
class Bases:
    agenda: pd.DataFrame
    titulos: pd.DataFrame
    fornecedores: pd.DataFrame
    alteracoes: pd.DataFrame
    nfs: pd.DataFrame
    duplicatas: pd.DataFrame
    ocs: pd.DataFrame
    dda: pd.DataFrame
    usuarios: pd.DataFrame
    comunicacoes: pd.DataFrame
    contratos: pd.DataFrame
    extrato_mer: pd.DataFrame
    extrato_lit: pd.DataFrame
    politicas: pd.DataFrame
    ferramentas: pd.DataFrame
    ref: pd.Timestamp = REF


def _csv(nome: str, **kw) -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / f"{nome}.csv", **kw)


def carregar(data_dir: Path | None = None) -> Bases:
    global DATA_DIR
    if data_dir:
        DATA_DIR = Path(data_dir)
    ag = _csv("agenda_remessa", dtype={"titulo_id": str})
    tit = _csv("contas_a_pagar", dtype={"numero_nf_digitado": str, "linha_digitavel": str})
    forn = _csv("fornecedores", dtype={"agencia": str, "conta": str, "banco": str, "telefone_cadastrado": str})
    alt = _csv("alteracoes_cadastro", dtype=str)
    nfs = _csv("notas_fiscais", dtype={"chave_acesso": str, "cnpj_emitente": str, "numero_nf": str})
    dup = _csv("nf_duplicatas", dtype={"chave_acesso": str, "n_dup": str})
    ocs = _csv("pedidos_compra", dtype={"cnpj_fornecedor": str})
    dda = _csv("dda_boletos", dtype={"linha_digitavel": str, "banco_cobrador": str})
    usu = _csv("usuarios_sistema")
    com = _csv("comunicacoes_fornecedores")
    ctr = _csv("contratos_fornecedores")
    mer = _csv("extrato_banco_meridiano")
    lit = pd.read_csv(DATA_DIR / "extrato_banco_litoral.csv", sep=";", decimal=",", thousands=".")
    pol = _csv("politicas")
    fer = _csv("ferramentas")

    forn["raiz"] = forn.cnpj.map(raiz)
    forn["dominio"] = forn.email_cadastrado.map(dominio)
    tit["nf_norm"] = tit.numero_nf_digitado.map(norm_nf)
    nfs["raiz"] = nfs.cnpj_emitente.map(raiz)
    nfs["nf_norm"] = nfs.numero_nf.map(norm_nf)
    ocs["raiz"] = ocs.cnpj_fornecedor.map(raiz)
    dda["raiz"] = dda.cnpj_beneficiario.map(raiz)
    alt["data_hora"] = pd.to_datetime(alt.data_hora)
    com["data_hora"] = pd.to_datetime(com.data_hora)
    com["dominio"] = com.remetente.map(dominio)
    for c in ("vencimento",):
        tit[c] = pd.to_datetime(tit[c])
        ag[c] = pd.to_datetime(ag[c])
    ag["data_prevista"] = pd.to_datetime(ag.data_prevista)
    dup["vencimento"] = pd.to_datetime(dup.vencimento)
    lit["Data"] = pd.to_datetime(lit["Data"], format="%d/%m/%Y")
    mer["data"] = pd.to_datetime(mer["data"])
    return Bases(ag, tit, forn, alt, nfs, dup, ocs, dda, usu, com, ctr, mer, lit, pol, fer)
