"""Textos em português simples: o que aparece para as pessoas (app, Telegram, cards)."""
from __future__ import annotations

TIPOS = {
    "GOLPE_TROCA_CONTA": {"titulo": "Possível golpe", "frase": "A conta bancária do fornecedor foi trocada sem a ligação de confirmação.",
                          "cor": "#E5484D"},
    "JA_PAGO_FORA_DO_LOTE": {"titulo": "Pagamento em dobro", "frase": "Esse título já foi pago por fora e continua no lote.",
                             "cor": "#E5484D"},
    "DUPLICIDADE": {"titulo": "Nota lançada duas vezes", "frase": "A mesma nota fiscal está no lote em dois títulos.",
                    "cor": "#F76B15"},
    "VALOR_DIVERGENTE": {"titulo": "Valor digitado errado", "frase": "O valor do título não bate com o da nota fiscal.",
                         "cor": "#F76B15"},
    "FORNECEDOR_ERRADO": {"titulo": "Empresa errada", "frase": "O pagamento iria para uma empresa diferente da que emitiu a nota.",
                          "cor": "#E5484D"},
    "OC_INVALIDA": {"titulo": "Compra não aprovada", "frase": "O pedido de compra está cancelado ou pendente em Compras.",
                    "cor": "#F5A524"},
    "BOLETO_SUSPEITO": {"titulo": "Boleto de outra empresa", "frase": "Quem recebe o boleto não é o fornecedor do cadastro.",
                        "cor": "#E5484D"},
}

FEITO = {
    "retirar_do_lote": "Tirei o título do lote",
    "cancelar_titulo": "Cancelei o título",
    "corrigir_lancamento": "Corrigi o lançamento",
    "bloquear_fornecedor": "Bloqueei os pagamentos ao fornecedor",
    "bloquear_titulo": "Bloqueei o título",
    "contatar_fornecedor": "Contatei o fornecedor pelo contato do cadastro",
    "abrir_incidente": "Abri um incidente",
    "reverter_alteracao_cadastro": "Voltei o cadastro para a conta confirmada",
    "agendar_titulo": "Coloquei de volta no lote",
    "propor_correcao_processo": "Propus uma correção de processo",
}

PEDIDO = {
    "reverter_alteracao_cadastro": "Aprovar a volta para a conta antiga, que estava confirmada",
    "cancelar_titulo": "Aprovar o cancelamento",
    "corrigir_lancamento valor": "Aprovar a correção do valor",
    "corrigir_lancamento fornecedor": "Aprovar a troca para o fornecedor certo",
    "liberar com exceção": "Aprovar o pagamento como exceção",
}


def tipo(t: str) -> dict:
    return TIPOS.get(t, {"titulo": t.replace("_", " ").capitalize(), "frase": "", "cor": "#F5A524"})


def pedido(acao: str) -> str:
    for k, v in PEDIDO.items():
        if acao.startswith(k):
            return v
    return acao


def feito(ferramenta: str) -> str:
    return FEITO.get(ferramenta, ferramenta.replace("_", " "))


def primeiro_nome(pessoa: str) -> str:
    """'Renata Paiva (coord. contas a pagar)' -> 'Renata Paiva'"""
    return pessoa.split("(")[0].strip()
