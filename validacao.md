# Validação do Guardião do Lote

## 1. Base do desafio
- ✅ 54 títulos com problema em 876 da agenda: possível golpe 25, nota lançada duas vezes 13, valor digitado errado 8, pagamento em dobro 3, empresa errada 2, compra não aprovada 2, boleto de outra empresa 1

## 2. Base limpa: tem que dar zero alertas
- ✅ 860 títulos conferidos, 0 alertas (nenhum falso positivo)

## 3. Problemas novos, em fornecedores e valores diferentes dos originais

| sorteio | injetados | achados certos | tipo errado | perdidos | alertas a mais |
|---|---|---|---|---|---|
| 1 | 44 | 44 | 0 | 0 | 0 |
| 2 | 9 | 9 | 0 | 0 | 0 |
| 3 | 8 | 8 | 0 | 0 | 0 |
| 4 | 8 | 8 | 0 | 0 | 0 |
| 5 | 9 | 9 | 0 | 0 | 0 |
| 6 | 15 | 15 | 0 | 0 | 0 |
| 7 | 34 | 34 | 0 | 0 | 0 |
| 8 | 8 | 8 | 0 | 0 | 0 |
| 9 | 34 | 34 | 0 | 0 | 0 |
| 10 | 34 | 34 | 0 | 0 | 0 |

- ✅ Possível golpe: 143/143 detectados com o tipo certo
- ✅ Nota lançada duas vezes: 10/10 detectados com o tipo certo
- ✅ Valor digitado errado: 10/10 detectados com o tipo certo
- ✅ Pagamento em dobro: 10/10 detectados com o tipo certo
- ✅ Empresa errada: 10/10 detectados com o tipo certo
- ✅ Compra não aprovada: 10/10 detectados com o tipo certo
- ✅ Boleto de outra empresa: 10/10 detectados com o tipo certo
- ✅ alertas que não deviam existir: 0

## 4. IDs trocados e linhas embaralhadas: resultado tem que ser igual
- ✅ 54 títulos com problema, mesmos tipos e mesmos títulos (traduzidos) que a base original

## 5. Trava anti-alucinação: texto da IA com dado inventado é descartado
- ✅ texto fiel às evidências é aceito
- ✅ valor inventado (R$ 11.808,60 no lugar de R$ 1.180,86) é barrado
- ✅ número de título inventado é barrado
- ✅ a IA nunca decide pagamento: quem retira, cancela ou bloqueia são as regras das políticas

Tempo total: 34s

**Resultado: tudo certo.**