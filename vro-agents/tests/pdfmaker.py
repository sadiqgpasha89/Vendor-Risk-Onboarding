"""Builds small PDFs for tests (reportlab for text PDFs, Pillow for scans, pypdf for JavaScript/attachments/encryption)."""
from __future__ import annotations

import io
import random


def text_pdf(pages: list[str], *, title: str | None = None, hidden: list[tuple] | None = None, font_size: float = 10, width: float = 1800) -> bytes:
    """One PDF page per entry. Very wide pages so reportlab never needs to wrap (extraction then returns the original lines).
    hidden: list of (page_index, kind, text) with kind in white|tiny|offpage|white_on_box."""
    from reportlab.lib.colors import Color, black, white
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(width, 900), pageCompression=0)
    if title:
        c.setTitle(title)
    for i, text in enumerate(pages):
        c.setFont("Helvetica", font_size)
        c.setFillColor(black)
        y = 860
        for line in text.split("\n"):
            c.drawString(40, y, line)
            y -= font_size + 4
        for (pi, kind, t) in hidden or []:
            if pi != i:
                continue
            if kind == "white":
                c.setFillColor(white); c.setFont("Helvetica", 10); c.drawString(40, 200, t)
            elif kind == "tiny":
                c.setFillColor(black); c.setFont("Helvetica", 1); c.drawString(40, 150, t)
            elif kind == "offpage":
                c.setFillColor(black); c.setFont("Helvetica", 10); c.drawString(width + 100, 100, t)
            elif kind == "white_on_box":
                c.setFillColor(Color(0.1, 0.2, 0.5)); c.rect(30, 400, 600, 30, fill=1, stroke=0)
                c.setFillColor(white); c.setFont("Helvetica-Bold", 14); c.drawString(40, 410, t)
        c.showPage()
    c.save()
    return buf.getvalue()


def scanned_pdf(pages: list[str], *, noise: float = 0.0, blur: float = 0.0, dpi: int = 200) -> bytes:
    """Image-only PDF (no text layer), like a scanner produces."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 34)
    imgs = []
    rng = random.Random(3)
    for text in pages:
        im = Image.new("L", (1700, 2200), 255)
        d = ImageDraw.Draw(im)
        y = 120
        for line in text.split("\n"):
            d.text((100, y), line, fill=0, font=font)
            y += 56
        if blur:
            im = im.filter(ImageFilter.GaussianBlur(blur))
        if noise:
            px = im.load()
            for _ in range(int(1700 * 2200 * noise)):
                px[rng.randrange(1700), rng.randrange(2200)] = rng.choice((0, 255))
        imgs.append(im)
    buf = io.BytesIO()
    imgs[0].save(buf, format="PDF", save_all=True, append_images=imgs[1:], resolution=dpi)
    return buf.getvalue()


def with_js(pdf: bytes, js: str = "app.alert('hi');") -> bytes:
    from pypdf import PdfReader, PdfWriter
    w = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf)))
    w.add_js(js)
    out = io.BytesIO(); w.write(out)
    return out.getvalue()


def with_attachment(pdf: bytes) -> bytes:
    from pypdf import PdfReader, PdfWriter
    w = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf)))
    w.add_attachment("evil.exe", b"MZ....")
    out = io.BytesIO(); w.write(out)
    return out.getvalue()


def encrypted(pdf: bytes, user: str = "secret", owner: str = "owner") -> bytes:
    from pypdf import PdfReader, PdfWriter
    w = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf)))
    w.encrypt(user_password=user, owner_password=owner)
    out = io.BytesIO(); w.write(out)
    return out.getvalue()
