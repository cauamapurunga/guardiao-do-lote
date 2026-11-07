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
    "BOLETO_SUSPEITO": {"titulo": "Boleto suspeito", "frase": "O boleto não bate com o fornecedor ou não foi registrado no banco.",
                        "cor": "#E5484D"},
    "BOLETO_BAIXADO": {"titulo": "Boleto cancelado", "frase": "O próprio fornecedor cancelou este boleto no banco.", "cor": "#F5A524"},
    "NF_CANCELADA": {"titulo": "Nota cancelada", "frase": "A nota fiscal deste pagamento foi cancelada ou recusada.", "cor": "#E5484D"},
    "SEM_RECEBIMENTO": {"titulo": "Mercadoria não chegou", "frase": "A nota chegou, mas a mercadoria não entrou no CD.", "cor": "#F5A524"},
    "FRACIONAMENTO": {"titulo": "Pagamento dividido", "frase": "O pagamento foi quebrado em partes para caber na alçada.", "cor": "#F76B15"},
    "LANCADOR_INVALIDO": {"titulo": "Lançamento indevido", "frase": "Quem lançou este título não tinha permissão para lançar.", "cor": "#E5484D"},
    "ACIMA_DO_CONTRATO": {"titulo": "Acima do contrato", "frase": "A cobrança passa do valor fixo do contrato.", "cor": "#F76B15"},
    "FORNECEDOR_INATIVO": {"titulo": "Fornecedor inativo", "frase": "O fornecedor está bloqueado ou inativo no cadastro.", "cor": "#F76B15"},
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


def consequencias(caso: dict, n_mesmo_fornecedor: int = 1) -> tuple[str, str]:
    """O que acontece se a pessoa aprovar ou recusar, em uma frase cada."""
    acao = (caso.get("aprovacao") or {}).get("acao", "")
    t = caso["tipo"]
    if acao.startswith("reverter_alteracao_cadastro"):
        n = f"os {n_mesmo_fornecedor} títulos" if n_mesmo_fornecedor > 1 else "o título"
        return (f"O cadastro volta para a conta antiga, que estava confirmada, e {n} pagam o fornecedor de verdade.",
                f"{n.capitalize()} seguem bloqueados até alguém confirmar a nova conta por telefone com o fornecedor.")
    if acao.startswith("cancelar_titulo"):
        if t == "JA_PAGO_FORA_DO_LOTE":
            return ("O título é cancelado porque já foi pago por fora. Nada sai em dobro.",
                    "O título continua fora do lote, sem pagar, até o tesoureiro conferir o extrato.")
        return ("A cópia é cancelada. A nota é paga uma vez só, pelo título original.",
                "A cópia continua fora do lote, sem pagar. O título original segue normal.")
    if acao.startswith("corrigir_lancamento valor"):
        novo = acao.split("=", 1)[-1] if "=" in acao else "o valor da nota"
        return (f"O título volta ao lote com {novo}, o valor da nota fiscal.",
                "O título fica fora do lote até alguém corrigir à mão. O fornecedor pode receber com atraso.")
    if acao.startswith("corrigir_lancamento fornecedor"):
        return ("O título passa para a empresa que emitiu a nota e volta ao lote.",
                "O título fica fora do lote. Ninguém recebe até o lançamento ser corrigido.")
    return ("O pagamento sai como exceção aprovada.", "O título continua fora do lote.")


GLOSSARIO = {
    "lote": "Arquivo com os pagamentos do dia que vai ao banco num horário fixo. O que estiver nele, sai.",
    "título": "Uma conta a pagar lançada no ERP (uma parcela de uma nota, um boleto, um aluguel).",
    "NF": "Nota fiscal do fornecedor. Diz quanto cobrar e em quantas parcelas.",
    "OC": "Ordem de compra: o pedido aprovado em Compras antes da compra acontecer.",
    "DDA": "Lista de boletos que os bancos registraram contra o CNPJ da empresa. Mostra quem de verdade vai receber.",
    "alçada": "Até quanto cada pessoa (ou o agente) pode aprovar sozinha.",
    "aprovação dupla": "Duas pessoas diferentes precisam aprovar. Vale para troca de conta bancária.",
}
