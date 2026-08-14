"""Image work Pillow does because Tk can't.

Anneal wants three things Tk has no way to draw — gradient fills, drop shadows,
and one widget compositing over another. This module supplies all three as
pre-rendered images, which is the only way to have them here.

The trick, and its limit, is the same throughout. CustomTkinter has no
transparency: `fg_color="transparent"` paints the *parent's colour*, so a widget
sitting over an image shows up as a flat rectangle. An image backdrop therefore
only works where either nothing sits on top of it, or whatever does sit on top
can be given the exact colour the image holds underneath it. Every surface below
is built so one of those two is true.

`card_surface` is where the money is: a card's lift in the mockup is a drop
shadow, and a shadow has to be drawn outside the card, on the page behind it —
so the card widget is made bigger than the card and the shadow lives in the
margin. Surfaces are cached by size, so a grid of identical cards pays for one.

One Anneal effect has no route through here at all. A convex gradient button
was built and thrown away: CTkButton accepts compound="center" and reports it
back, but never draws the image behind its label — the button comes out with no
fill whatsoever. Primary buttons use a flat accent with a 1px lit edge instead.
"""

from PIL import Image, ImageDraw, ImageFilter, ImageTk

# Surfaces are keyed by every argument that shapes them, so a grid of cards all
# the same size shares one image. The cache holds the PhotoImages too — Tk drops
# an image the moment nothing references it.
_CACHE = {}
_CACHE_LIMIT = 24

# How far down the top strip its ramp runs, as a fraction of the strip's height.
# It has to finish above the tallest widget packed on the strip (the cog, which
# starts about a fifth of the way down): below that point the image must be one
# flat colour, or every widget on the strip outlines itself. See TopBar.
STRIP_RAMP = 0.18


def _cached(key, build, wrap=None):
    """Build a surface once and hand out the same object thereafter.

    `wrap` is what the caller needs it as — a PhotoImage for a plain Tk label,
    or nothing at all when the caller wraps it itself (CTkButton insists on a
    CTkImage, which has to be made after a root exists).
    """
    image = _CACHE.get(key)
    if image is None:
        if len(_CACHE) >= _CACHE_LIMIT:
            _CACHE.clear()      # a resize invalidated the lot; start over
        built = build()
        image = _CACHE[key] = wrap(built) if wrap else built
    return image


def cache_size():
    """How many surfaces are being held. Read by the benchmark."""
    return len(_CACHE)


def _rgb(colour):
    """'#rrggbb' -> (r, g, b)."""
    value = colour.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _ramp(width, height, top, bottom, flat_from=0.0):
    """A vertical two-stop gradient, going flat below `flat_from` of the height.

    The flat tail matters: a card's info strip sits at the bottom and carries
    real widgets, and those widgets have to be given a single colour that
    matches the image behind them. Ending the ramp above them means there is
    one such colour to give.
    """
    top, bottom = _rgb(top), _rgb(bottom)
    stop = max(1, round(height * (flat_from or 1.0)))
    column = Image.new("RGB", (1, height))
    for y in range(height):
        t = min(1.0, y / stop)
        column.putpixel((0, y), tuple(
            round(a + (b - a) * t) for a, b in zip(top, bottom)))
    return column.resize((width, height), Image.NEAREST)


def glow_surface(width, height, *, top, bottom, plateau=0.0):
    """A band of light across the top of a page, let down into it.

    `top` is held flat for the first `plateau` fraction of the height and then
    falls to `bottom` at the foot. The plateau is what makes this usable at
    all: the header row's widgets sit on this band, they cannot be transparent,
    and a widget can only be given one colour — so the ramp is arranged to have
    a single colour everywhere a widget sits, and to do its falling in the gap
    below them where nothing does.

    Returns a PhotoImage, cached by size and stops.
    """
    key = ("glow", width, height, top, bottom, plateau)

    def build():
        top_rgb, bottom_rgb = _rgb(top), _rgb(bottom)
        held = round(height * plateau)
        column = Image.new("RGB", (1, height))
        for y in range(height):
            t = 0.0 if y < held else min(1.0, (y - held) / max(1, height - held))
            column.putpixel((0, y), tuple(
                round(a + (b - a) * t) for a, b in zip(top_rgb, bottom_rgb)))
        return column.resize((max(1, width), height), Image.NEAREST)

    return _cached(key, build, ImageTk.PhotoImage)


def card_surface(width, height, *, fill_top, fill_bottom, base, radius, pad,
                 shadow=0.55, blur=7, drop=3, border=None, glow=None):
    """A card: page-coloured ground, drop shadow, rounded gradient face.

    The face is inset by `pad` on every side and the shadow is drawn into that
    margin, which is the whole reason the widget is bigger than the card it
    shows. `border` outlines the face; `glow` bleeds a colour outwards from it,
    for the hovered state.

    Returns a PhotoImage, cached — call it per card and a full grid still only
    renders one image per distinct size and state.
    """
    key = ("card", width, height, fill_top, fill_bottom, base, radius, pad,
           shadow, blur, drop, border, glow)

    def build():
        canvas = Image.new("RGB", (width, height), _rgb(base))
        box = (pad, pad, width - pad - 1, height - pad - 1)

        if glow:
            # Drawn before the shadow so the shadow sits over it, the way a lit
            # card still casts one.
            halo = Image.new("L", (width, height), 0)
            ImageDraw.Draw(halo).rounded_rectangle(
                (box[0] - 2, box[1] - 2, box[2] + 2, box[3] + 2),
                radius=radius + 2, fill=255)
            halo = halo.filter(ImageFilter.GaussianBlur(blur + 4))
            halo = halo.point(lambda v: round(v * 0.55))
            canvas = Image.composite(
                Image.new("RGB", (width, height), _rgb(glow)), canvas, halo)

        if shadow:
            cast = Image.new("L", (width, height), 0)
            ImageDraw.Draw(cast).rounded_rectangle(
                (box[0], box[1] + drop, box[2], box[3] + drop),
                radius=radius, fill=255)
            cast = cast.filter(ImageFilter.GaussianBlur(blur))
            cast = cast.point(lambda v: round(v * shadow))
            canvas = Image.composite(Image.new("RGB", (width, height), (0, 0, 0)),
                                     canvas, cast)

        face = Image.new("L", (width, height), 0)
        ImageDraw.Draw(face).rounded_rectangle(box, radius=radius, fill=255)
        # The ramp goes flat over the bottom third, where the info strip's own
        # widgets have to match it exactly (see _ramp).
        canvas = Image.composite(
            _ramp(width, height, fill_top, fill_bottom, flat_from=0.62),
            canvas, face)

        if border:
            ImageDraw.Draw(canvas).rounded_rectangle(
                box, radius=radius, outline=_rgb(border), width=2)
        return canvas

    return _cached(key, build, ImageTk.PhotoImage)


def strip_surface(width, height, *, top, bottom, seam=None):
    """The top strip: a ramp along its top edge, a 1px seam along its bottom.

    Everything packed on the strip keeps `bottom` as its own colour, and the
    ramp is arranged to have arrived there above the row those widgets sit on.
    That is the whole shape of this surface: a widget here cannot be
    transparent, so the gradient has to live where no widget does.

    There is deliberately no glow. One was tried, blurred across the full
    height, and it tinted the flat region too — at which point every widget on
    the strip painted its own flat rectangle and framed itself.
    """
    key = ("strip", width, height, top, bottom, seam)

    def build():
        canvas = _ramp(width, height, top, bottom, flat_from=STRIP_RAMP)
        if seam and height >= 2:
            ImageDraw.Draw(canvas).line(
                (0, height - 1, width, height - 1), fill=_rgb(seam))
        return canvas

    return _cached(key, build, ImageTk.PhotoImage)


def round_corners(image, radius, base, corners=("tl", "tr")):
    """Round an image's corners against `base`, since Tk labels are square.

    The thumbnail is a picture in a rectangular label sitting inside a rounded
    card, so without this its top corners overhang the card's own curve.
    """
    width, height = image.size
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=radius, fill=255)
    # Square off whichever corners the card does not round at this edge.
    if "tl" not in corners:
        draw.rectangle((0, 0, radius, radius), fill=255)
    if "tr" not in corners:
        draw.rectangle((width - radius - 1, 0, width - 1, radius), fill=255)
    if "bl" not in corners:
        draw.rectangle((0, height - radius - 1, radius, height - 1), fill=255)
    if "br" not in corners:
        draw.rectangle((width - radius - 1, height - radius - 1,
                        width - 1, height - 1), fill=255)
    return Image.composite(image.convert("RGB"),
                           Image.new("RGB", (width, height), _rgb(base)), mask)


def scrim(image, top=0.34, bottom=0.55):
    """Darken a thumbnail's top and bottom edges, leaving its middle alone.

    The duration badge sits over the top edge of a frame and the favourite star
    over the bottom, and a bright frame leaves both illegible. Blending the
    darkening into the picture beats putting a box behind each one: it costs no
    widget, it survives the card being resized, and it reads as part of the
    image rather than as furniture on top of it.

    `top` and `bottom` are how dark each edge goes, 0-1. Returns a new image;
    the caller's original is untouched.
    """
    width, height = image.size
    if width < 2 or height < 8:
        return image

    picture = image.convert("RGB")
    # The darkening is uniform across each row, so it is computed one pixel wide
    # and stretched — the mask costs `height` operations, not width × height.
    column = Image.new("L", (1, height))
    fade_top = max(1, round(height * 0.30))
    fade_bottom = max(1, round(height * 0.38))
    for y in range(height):
        if y < fade_top:
            value = top * (1 - y / fade_top)
        elif y > height - fade_bottom:
            value = bottom * (y - (height - fade_bottom)) / fade_bottom
        else:
            value = 0.0
        column.putpixel((0, y), round(value * 255))
    mask = column.resize((width, height), Image.NEAREST)

    return Image.composite(Image.new("RGB", (width, height), (0, 0, 0)),
                           picture, mask)
