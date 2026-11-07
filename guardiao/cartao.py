"""Card em imagem (PNG) de cada caso, para o Telegram: legível no celular, com a marca."""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import linguagem as L
from .dados import brl2

ASSETS = Path(__file__).resolve().parent.parent / "assets"
W, PAD = 1080, 64
INK, MUTED, SOFT, BG, LINE = "#111111", "#5C5F66", "#8A8D93", "#FAFAF7", "#E6E6E1"


def _f(peso: str, tam: int):
    return ImageFont.truetype(str(ASSETS / "fonts" / f"Inter-{peso}.otf"), tam)


def _quebrar(d: ImageDraw.ImageDraw, texto: str, fonte, largura: int) -> list[str]:
    linhas, atual = [], ""
    for p in str(texto).split():
        teste = (atual + " " + p).strip()
        if d.textlength(teste, font=fonte) <= largura:
            atual = teste
        else:
            if atual:
                linhas.append(atual)
            atual = p
    if atual:
        linhas.append(atual)
    return linhas


def _hex(c: str, alpha: float, fundo: str = BG):
    c, f = c.lstrip("#"), fundo.lstrip("#")
    rgb = [int(c[i:i + 2], 16) for i in (0, 2, 4)]
    bg = [int(f[i:i + 2], 16) for i in (0, 2, 4)]
    return tuple(round(a * alpha + b * (1 - alpha)) for a, b in zip(rgb, bg))


def gerar(caso: dict, modo: str = "aprovacao", para: str = "", motivo: str = "") -> bytes:
    """modo: 'aprovacao' (pede decisão) ou 'aviso' (acionamento)."""
    t = L.tipo(caso["tipo"])
    img = Image.new("RGB", (W, 2400), BG)
    d = ImageDraw.Draw(img)
    larg = W - 2 * PAD

    # cabeçalho preto com a marca
    d.rectangle([0, 0, W, 120], fill=INK)
    logo = Image.open(ASSETS / "gocase-branco.png").convert("RGBA")
    logo = logo.resize((int(logo.width * 44 / logo.height), 44))
    img.paste(logo, (PAD, 38), logo)
    rot = "Guardião do Lote"
    d.text((W - PAD - d.textlength(rot, font=_f("Medium", 26)), 46), rot, font=_f("Medium", 26), fill="#B8BAB4")
    y = 120 + 56

    # etiqueta do tipo
    et = t["titulo"].upper()
    fe = _f("Bold", 24)
    w_et = d.textlength(et, font=fe) + 40
    d.rounded_rectangle([PAD, y, PAD + w_et, y + 48], radius=24, fill=_hex(t["cor"], 0.14))
    d.text((PAD + 20, y + 10), et, font=fe, fill=t["cor"])
    y += 48 + 28

    # frase principal
    for ln in _quebrar(d, t["frase"], _f("Bold", 46), larg):
        d.text((PAD, y), ln, font=_f("Bold", 46), fill=INK)
        y += 58
    y += 20

    # valor e lote
    d.text((PAD, y), brl2(caso["valor"]), font=_f("Bold", 76), fill=INK)
    y += 96
    d.text((PAD, y), f"{caso['fornecedor']}", font=_f("Medium", 30), fill=INK)
    y += 44
    d.text((PAD, y), f"Lote {caso['lote']} · sai do banco em {caso['fechamento']}", font=_f("Regular", 28), fill=MUTED)
    y += 64
    d.line([PAD, y, W - PAD, y], fill=LINE, width=2)
    y += 36

    # evidências
    d.text((PAD, y), "O QUE EU ENCONTREI", font=_f("Bold", 22), fill=SOFT)
    y += 44
    for ev in caso["evidencias"][:3]:
        linhas = _quebrar(d, ev, _f("Regular", 28), larg - 36)
        d.ellipse([PAD + 2, y + 13, PAD + 14, y + 25], fill=t["cor"])
        for ln in linhas:
            d.text((PAD + 36, y), ln, font=_f("Regular", 28), fill="#2A2C30")
            y += 40
        y += 14
    y += 16

    # o que já fez
    feitos = []
    for a in caso.get("acoes", []):
        if a["modo"] == "auto" and a["ferramenta"] not in ("listar_agenda_remessa",):
            txt = L.feito(a["ferramenta"])
            if txt not in feitos:
                feitos.append(txt)
    if feitos:
        d.text((PAD, y), "O QUE EU JÁ FIZ", font=_f("Bold", 22), fill=SOFT)
        y += 44
        for txt in feitos[:4]:
            d.text((PAD, y), "✓", font=_f("Bold", 30), fill="#2E8B57")
            d.text((PAD + 40, y), txt, font=_f("Medium", 30), fill=INK)
            y += 46
        y += 24

    # pedido para a pessoa
    if modo == "aprovacao" and caso.get("aprovacao"):
        nome = L.primeiro_nome(caso["aprovacao"]["nome"])
        titulo = f"{nome}, preciso da sua aprovação"
        corpo = L.pedido(caso["aprovacao"]["acao"]) + "."
        rodape = "Responda nos botões abaixo."
    else:
        nome = L.primeiro_nome(para) if para else "Equipe"
        titulo = f"{nome}, preciso que você veja isso"
        corpo = motivo or caso["resumo"]
        rodape = "Nada sai do lote até alguém resolver."
    lt = _quebrar(d, titulo, _f("Bold", 34), larg - 64)
    lc = _quebrar(d, corpo, _f("Regular", 30), larg - 64)
    h = 40 + len(lt) * 46 + 12 + len(lc) * 42 + 20 + 36 + 36
    d.rounded_rectangle([PAD, y, W - PAD, y + h], radius=24, fill=INK)
    yy = y + 40
    for ln in lt:
        d.text((PAD + 32, yy), ln, font=_f("Bold", 34), fill="#FFFFFF")
        yy += 46
    yy += 12
    for ln in lc:
        d.text((PAD + 32, yy), ln, font=_f("Regular", 30), fill="#E4E4DF")
        yy += 42
    yy += 20
    d.text((PAD + 32, yy), rodape, font=_f("Medium", 24), fill="#9C9E98")
    y += h + 36

    d.text((PAD, y), f"Título {caso['titulo_id']} · caso {caso['id']}", font=_f("Regular", 22), fill=SOFT)
    y += 56
    img = img.crop((0, 0, W, y))
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()
