"""Teste rápido do AI Proxy: roda 1 chamada no Jev e 1 no chat e mostra o custo (💲) de cada uma.
Uso: python teste_ia.py   (precisa de AI_PROXY_API_KEY no .env)
"""
from guardiao import env  # noqa: F401
from guardiao import ia

if not ia.disponivel():
    raise SystemExit("Coloque AI_PROXY_API_KEY no .env")

j = ia.jev({"assunto": "Atualização de dados bancários - Embalarte",
            "texto": "Informamos que a Embalarte passou a receber exclusivamente na conta abaixo. Favor atualizar com urgência."},
           {"tipo": {"type": "choice", "instructions": "Pedido principal",
                     "criteria": {"troca_conta": "muda conta bancária", "cobranca_boleto": "cobra boleto", "outro": "outro"}},
            "pressao": {"type": "noul", "instructions": "Usa urgência ou pressão?"}})
print("Jev →", j["answers"]["tipo"]["choice"], f"(confiança {j['answers']['tipo'].get('confidence')})",
      "· pressão", j["answers"]["pressao"]["noul"])

print("Chat →", ia.chat("Em 1 frase: por que trocar a conta de um fornecedor por e-mail sem ligar é arriscado?"))
print("Total:", ia.resumo_uso())
