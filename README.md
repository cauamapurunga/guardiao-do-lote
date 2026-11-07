# 🛡️ Guardião do Lote

Time de agentes de IA de **contas a pagar** do Gogroup. Antes de cada lote de remessa fechar, eles conferem **todos os títulos** contra ERP, Compras, Portal NF-e, DDA, extratos dos dois bancos e caixa de e-mail/WhatsApp. Dentro da alçada, eles agem sozinhos nos sistemas. Fora dela, chamam a pessoa certa no Telegram, já com as evidências.

> **Hoje**, o tesoureiro assina o lote sem conferir e o dinheiro sai às 10h (Meridiano) ou às 14h (Litoral).
> **Com o Guardião**, nos 876 títulos e 17 lotes de 03 a 13/11 (R$ 10,2 mi), seriam **R$ 639 mil saindo indevidamente**. O agente segura tudo, e o custo dele é de **~R$ 860**: acionamentos humanos e atraso de um título legítimo, pela fórmula oficial do `parametros.md`.

## O que ele pega (regras genéricas, sem nada amarrado a ID)

| Problema | Como detecta | O que o agente faz sozinho | Quem ele chama |
|---|---|---|---|
| 🚨 Golpe de troca de conta | alteração bancária há menos de 30 dias sem ligação ao telefone **anterior** + e-mail de domínio parecido (`embalartte` × `embalarte`) | `bloquear_fornecedor`, `bloquear_titulo`, `abrir_incidente` | aprovação dupla para reverter o cadastro + jurídico (PS08) |
| 💸 Já pago fora do lote | débito avulso no extrato (2 formatos de banco) sem baixa no ERP | `retirar_do_lote`, `cancelar_titulo` (até R$ 5 mil) | tesoureiro (PS02) |
| 👯 Duplicidade | mesma raiz de CNPJ + NF normalizada (`000073535` = `73535-1`) + parcela | retira e cancela a cópia | aprovador, se passar de R$ 5 mil |
| 🔢 Vírgula deslocada | título × duplicata do XML (×10 / ÷10) | `corrigir_lancamento` até R$ 5 mil | aprovador acima disso |
| 🏷️ Fornecedor errado | raiz do CNPJ da NF ≠ fornecedor do título (Cartonart × Gráfica Cartonar) | retira do lote | aprovação da correção |
| 📦 OC cancelada ou pendente | Compras | retira do lote | comprador (PS04/PS05) |
| 🧾 Boleto suspeito | CNPJ do beneficiário ≠ fornecedor; banco fora do histórico | bloqueia e contata pelo canal do cadastro | — |

O **Auditor** também procura a causa raiz. Exemplo: 8 títulos com vírgula deslocada vieram do mesmo analista júnior, admitido em 01/10, e foi ele também quem aceitou a troca de conta do golpe. A partir disso ele propõe uma trava no ERP e treinamento.

## Agentes

- **Sentinela (orquestrador)**: abre cada lote antes do fechamento e despacha os títulos.
- **Analista CP**: faz as três vias, duplicidade, pagamento fora do lote e correções. Alçada de R$ 5 mil.
- **Auditor**: cuida de fraude, bloqueios, incidentes e causa raiz.
- **Leitor da Caixa**: classifica e-mails e WhatsApps com IA (Jev no AI Proxy) e cruza com o cadastro. O texto de terceiros é tratado como dado, nunca como instrução.
- **Humanos**: aprovam ou recusam no Telegram. O agente executa o resto e nunca aprova a própria ação.

## Rodar

```bash
pip install -r requirements.txt
cp .env.example .env         # AI_PROXY_API_KEY e TELEGRAM_TOKEN (opcionais)
python servidor.py           # app em http://localhost:8000 + bot do Telegram no mesmo processo
python validar.py            # prova de que está certo (base limpa, problemas novos, IDs embaralhados, trava da IA)
python teste_ia.py           # 1 chamada ao Jev + 1 ao chat, com custo
```

O que você aprova no Telegram aparece no app na hora, e vice-versa. No Telegram: `/status`, `/lote`, `/pendentes` (cards em imagem com Aprovar/Recusar), `/avisos` ou um número de título.

## Como sabemos que está certo (`validar.py`)

1. **Base limpa**: corrige cada problema e roda de novo → 0 alertas em 860 títulos (zero falso positivo).
2. **Problemas novos**: em 10 sorteios, injeta 7 tipos de problema em fornecedores e valores diferentes dos originais → 203/203 achados com o tipo certo, nenhum alerta a mais.
3. **Dados embaralhados**: todos os IDs trocados e linhas embaralhadas → resultado idêntico.
4. **IA não inventa**: todo texto da IA é conferido contra as evidências; valor ou título que não existe faz o texto ser descartado. A IA nunca decide pagamento.

A validação encontrou 2 bugs reais que foram corrigidos: fornecedor com duas trocas de conta (a fraudulenta passava) e título no fornecedor errado pago por boleto (classificado com o tipo errado).

Os dados ficam em `data/` (bases fictícias da organização, desafio Pagamentos). Com dados reais, os mesmos cruzamentos rodariam sobre as exportações do ERP, o DDA e os extratos CNAB/OFX, a cada hora.

## IA (AI Proxy do evento)

- `guardiao/ia.py` é o cliente do AI Proxy. Toda chamada imprime uma linha 💲 com os tokens e o custo, além do total acumulado da sessão, e o painel mostra esse total na barra lateral.
- **Jev (`/v1/systemone`)**: o Leitor da Caixa classifica cada e-mail ou WhatsApp (troca de conta, cobrança, pagamento não identificado, reajuste, pedido urgente) e mede a "pressão" da mensagem. Com confiança abaixo de 0,7, a mensagem vai para revisão humana. As 246 mensagens custam por volta de US$ 0,003. As chamadas rodam em paralelo com no máximo 6 ao mesmo tempo, e o cliente tenta de novo quando recebe 429 ou 503.
- **Chat (`latest`)**: escreve o resumo de cada caso para quem vai aprovar, e esse resumo vai junto no pedido do Telegram.
- Sem token, tudo continua funcionando com as regras.
- Teste rápido: `python teste_ia.py`.
