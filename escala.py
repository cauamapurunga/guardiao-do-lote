"""Teste de volume: multiplica a agenda de remessa e mede o tempo da conferência.

Uso: py escala.py        (1×, 5×, 10× e 20× os títulos)
"""
import copy
import time

import pandas as pd

from guardiao import env  # noqa: F401
from guardiao.dados import carregar
from guardiao.deteccao import varrer


def multiplicar(b, k: int):
    b = copy.deepcopy(b)
    ag, tit = [b.agenda], [b.titulos]
    for i in range(1, k):
        a = b.agenda.copy()
        a["titulo_id"] = a.titulo_id + f"-{i}"
        t = b.titulos[b.titulos.titulo_id.isin(b.agenda.titulo_id)].copy()
        t["titulo_id"] = t.titulo_id + f"-{i}"
        ag.append(a)
        tit.append(t)
    b.agenda = pd.concat(ag, ignore_index=True)
    b.titulos = pd.concat(tit, ignore_index=True)
    return b


if __name__ == "__main__":
    base = carregar()
    print(f"{'títulos':>8} | {'tempo':>7} | por título")
    for k in (1, 5, 10, 20):
        b = multiplicar(base, k)
        t0 = time.time()
        varrer(b)
        dt = time.time() - t0
        print(f"{len(b.agenda):>8} | {dt:6.1f}s | {1000 * dt / len(b.agenda):.1f} ms")
