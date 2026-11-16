"""
Генерирует assets/jarvis.ico — иконку в стиле Iron Man HUD.
Запускать один раз: python create_icon.py
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter


def _draw_jarvis_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (3, 8, 16, 255))
    d = ImageDraw.Draw(img)

    cx = cy = size / 2
    r = size / 2 - max(1, size / 24)

    # ── Внешнее свечение (серия концентрических колец) ──────────────────────
    glow_steps = min(6, size // 8)
    for i in range(glow_steps, 0, -1):
        alpha = int(40 + i * 20)
        pad = i * max(1, size // 48)
        d.ellipse(
            [cx - r - pad, cy - r - pad, cx + r + pad, cy + r + pad],
            outline=(0, 180, 220, alpha),
            width=max(1, size // 64),
        )

    # ── Основной круг ────────────────────────────────────────────────────────
    d.ellipse(
        [cx - r, cy - r, cx + r, cy + r],
        fill=(4, 9, 15, 255),
        outline=(0, 212, 255, 255),
        width=max(1, size // 20),
    )

    # Внутреннее кольцо
    ir = r * 0.88
    d.ellipse(
        [cx - ir, cy - ir, cx + ir, cy + ir],
        outline=(0, 56, 80, 180),
        width=max(1, size // 48),
    )

    if size >= 48:
        # ── Маска: лоб, щёки, глаза ─────────────────────────────────────────

        def pt(dx, dy):
            return (cx + r * dx, cy + r * dy)

        # Щёки — тонкие линии панелей
        d.line([pt(-0.44, -0.22), pt(-0.70, 0.06)], fill=(0, 60, 80, 200),
               width=max(1, size // 64))
        d.line([pt(0.44, -0.22), pt(0.70, 0.06)],  fill=(0, 60, 80, 200),
               width=max(1, size // 64))

        # Линия лба
        d.line([pt(0, -0.85), pt(0, -0.38)], fill=(0, 60, 80, 180),
               width=max(1, size // 64))

        # ── Глаза ─────────────────────────────────────────────────────────
        ey  = cy + r * (-0.20)
        ew  = r * 0.27
        eh  = r * 0.10

        def eye_poly(ex):
            return [
                (ex - ew,       ey + eh * 0.4),
                (ex - ew * 0.5, ey - eh),
                (ex + ew * 0.5, ey - eh),
                (ex + ew,       ey + eh * 0.4),
                (ex + ew * 0.5, ey + eh),
                (ex - ew * 0.5, ey + eh),
            ]

        # Свечение глаз
        for expand in [size // 12, size // 18]:
            glow_col = (0, 150, 200, 80)
            for ex in [cx - r * 0.30, cx + r * 0.30]:
                pts = eye_poly(ex)
                exp_pts = [(px + (1 if px > cx else -1) * expand * 0.3,
                            py + (expand * 0.2 if py < ey else -expand * 0.2))
                           for px, py in pts]
                d.polygon(exp_pts, fill=glow_col)

        # Основа глаз
        for ex in [cx - r * 0.30, cx + r * 0.30]:
            d.polygon(eye_poly(ex), fill=(0, 200, 240, 255))

        # Яркое ядро глаз
        for ex in [cx - r * 0.30, cx + r * 0.30]:
            hw = ew * 0.28
            hh = eh * 0.40
            d.ellipse([ex - hw, ey - hh, ex + hw, ey + hh], fill=(220, 248, 255, 255))

        # ── Рот — горизонтальные планки ───────────────────────────────────
        for y_frac, w_frac, alpha in [(0.32, 0.36, 160), (0.40, 0.30, 120), (0.46, 0.24, 80)]:
            d.line(
                [pt(-w_frac, y_frac), pt(w_frac, y_frac)],
                fill=(0, 80, 110, alpha),
                width=max(1, size // 48),
            )

    else:
        # Упрощённые глаза для маленьких размеров (16, 32)
        ew = r * 0.30
        eh = r * 0.14
        ey = cy - r * 0.18
        for ex in [cx - r * 0.28, cx + r * 0.28]:
            d.ellipse([ex - ew, ey - eh, ex + ew, ey + eh],
                      fill=(0, 200, 240, 255))

    # Размытие для эффекта свечения (только для больших размеров)
    if size >= 64:
        glow = img.copy().filter(ImageFilter.GaussianBlur(radius=size // 32))
        img = Image.alpha_composite(glow, img)

    return img


def main():
    out = Path("assets/jarvis.ico")
    out.parent.mkdir(exist_ok=True)

    sizes = [16, 24, 32, 48, 64, 128, 256]
    frames = [_draw_jarvis_icon(s) for s in sizes]

    frames[0].save(
        out,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=frames[1:],
    )
    print(f"Иконка сохранена: {out.resolve()}")


if __name__ == "__main__":
    main()
