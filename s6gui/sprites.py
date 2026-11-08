"""Formation pictures composed from the original game files, without starting the game.

Each plant is the first frame of its idle animation, drawn from the original reanim
definition (compiled/reanim/*.reanim.compiled): every visible part image placed with the
definition's transform. Which reanim a plant uses is read from the S6 executable itself,
including its extensions (lily pad, explode-o-nut, 飘飘 and 76-79 use ZZZ*.reanim).
"""
from __future__ import annotations
from functools import cache
import math
from pathlib import Path
import struct
import threading
import zlib
from PIL import Image, ImageDraw, ImageFont

# Pillow 9.0 (requirements: >=9) has the module constants, newer versions the enums.
AFFINE = getattr(Image, 'Transform', Image).AFFINE
BICUBIC = getattr(Image, 'Resampling', Image).BICUBIC
FLIP_LEFT_RIGHT = getattr(Image, 'Transpose', Image).FLIP_LEFT_RIGHT

ROOT = Path(__file__).resolve().parent.parent
GAME = ROOT/'original/麦版S6本体+ct+修改器'  # same as s6.table.GAME (not imported: it needs keystone)

# Executable tables (image base 0x400000).
PLANT_DEFS = 0x69f2b0           # PlantDefinition[0..52], 36 bytes each
PLANT_DEFS_S6 = 0x794de0        # S6 PlantDefinition[76..79]
# ReanimatorDefinition params as relocated by S6 (type, file name, flags). The game indexes it by
# position; S6's own type fields skip 149-150, so they are not used.
REANIM_DEFS = 0x794b28-143*12
COMPILED_MAGIC = 0xdeadfed4
PLACEHOLDER = -10000.0          # field not given in the reanim file: inherit the previous frame

# Board geometry with the camera at x = 0: the background is drawn 220 px to the left.
BACKGROUND_X = 220
ROOF_MODES = {5, 10}
NIGHT_MODES = {2, 7}
MODE_BACKGROUND = {'day': 'images/background1.jpg', 'night': 'images/background2.jpg',
                   'roof': 'images/background5.jpg'}
SCENE_BACKGROUND = {'原版白天背景': 'images/background1.jpg', '原版黑夜背景': 'images/background2.jpg',
                    '原版屋顶背景': 'images/background5.jpg'}
# Track prefixes the CT hides when a plant is created (call 473A40 with group -1): awakened and
# easter-egg skins only appear later in a match. Blinks are hidden until the plant blinks.
HIDDEN_PREFIXES = ('awake', 'easter', 'special')
FIRST_FRAME_ANIMS = {4: ('anim_armed',)}  # potato mine waits armed
IDLE_ANIMS = ('anim_full_idle', 'anim_idle')
# Shooters without anim_full_idle carry their heads as separate animations of the same
# definition (attached reanims in game); at the first idle frame they line up unshifted.
HEAD_ANIMS = ('anim_head_idle', 'anim_head_idle1', 'anim_head_idle2', 'anim_head_idle3', 'anim_splitpea_idle')
MIRRORED = {52}                           # 反双 faces left
TINTS = {49: (255, 64, 64)}               # explode-o-nut: the game draws it red
MOWER = ('LawnMower', 'anim_normal')
ROOF_MOWER = ('RoofCleaner', None)
MOWER_OFFSET = (-34, 34)  # from the row's first cell; fitted to an exported video frame

_lock = threading.Lock()


def _executable():
    data = (GAME/'PlantsVsZombies.exe').read_bytes()
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    sections, optional = struct.unpack_from('<H', data, pe+6)[0], struct.unpack_from('<H', data, pe+20)[0]
    base = struct.unpack_from('<I', data, pe+52)[0]
    table = []
    for i in range(sections):
        _, size, va, raw_size, raw = struct.unpack_from('<8sIIII', data, pe+24+optional+40*i)
        table.append((base+va, base+va+min(size or raw_size, raw_size), raw))

    def offset(address):
        for start, end, raw in table:
            if start <= address < end:
                return raw+address-start
        raise ValueError(f'address 0x{address:x} not in PlantsVsZombies.exe')
    return data, offset


@cache
def plant_reanims():
    """Seed type -> reanim file stem, from the executable's plant and reanim tables."""
    data, offset = _executable()

    def text(address):
        start = offset(address)
        return data[start:data.index(b'\0', start)].decode('latin1')
    files = {}
    for i in range(256):
        _, name, _ = struct.unpack_from('<3I', data, offset(REANIM_DEFS)+12*i)
        try:
            files[i] = Path(text(name).replace('\\', '/')).stem
        except ValueError:
            break
    plants = {}
    for table, first, count in ((PLANT_DEFS, 0, 53), (PLANT_DEFS_S6, 76, 4)):
        for i in range(count):
            seed, _, kind = struct.unpack_from('<3I', data, offset(table)+36*i)
            if seed != first+i:
                raise ValueError(f'unexpected plant table entry {seed} at 0x{table+36*i:x}')
            if kind in files:
                plants[seed] = files[kind]
    return plants


@cache
def _index(folder, prefix):
    return {prefix+p.stem.upper(): p for p in (GAME/folder).iterdir() if p.suffix.lower() in ('.png', '.jpg')}


@cache
def part(resource):
    path = _index('reanim', 'IMAGE_REANIM_').get(resource) or _index('images', 'IMAGE_').get(resource)
    return Image.open(path).convert('RGBA') if path else None


def _string(raw, pos):
    length = struct.unpack_from('<I', raw, pos)[0]
    return raw[pos+4:pos+4+length].decode('latin1'), pos+4+length


@cache
def definition(stem):
    """[(track name, [[x, y, kx, ky, sx, sy, f, a], ...], [image, ...]), ...] with missing fields filled."""
    files = {p.name.lower(): p for p in (GAME/'compiled/reanim').iterdir()}
    path = files.get(f'{stem}.reanim.compiled'.lower())
    if path is None:
        return None
    data = path.read_bytes()
    if struct.unpack_from('<I', data)[0] != COMPILED_MAGIC:
        raise ValueError(f'{path.name}: not a compiled reanim')
    raw = zlib.decompress(data[8:])
    count = struct.unpack_from('<I', raw, 8)[0]
    size = struct.unpack_from('<I', raw, 20)[0]
    lengths = [struct.unpack_from('<I', raw, 24+i*size+8)[0] for i in range(count)]
    pos = 24+count*size
    tracks = []
    for length in lengths:
        name, pos = _string(raw, pos)
        size = struct.unpack_from('<I', raw, pos)[0]
        frames = [list(struct.unpack_from('<8f', raw, pos+4+i*size)) for i in range(length)]
        pos += 4+length*size
        images = []
        for _ in range(length):
            image, pos = _string(raw, pos)
            _, pos = _string(raw, pos)  # font
            _, pos = _string(raw, pos)  # text
            images.append(image)
        # Same defaults and inheritance as the game's ReanimationFillInMissingData.
        previous, image = [0, 0, 0, 0, 1, 1, 0, 1], ''
        for i, frame in enumerate(frames):
            frame[:] = [p if v == PLACEHOLDER else v for v, p in zip(frame, previous)]
            image = images[i] = images[i] or image
            previous = frame
        tracks.append((name, frames, images))
    return tracks


def _first_frame(tracks, anim):
    """First frame of the named animation, or None when the definition has no such animation."""
    for name, frames, _ in tracks:
        if name == anim:
            return next((i for i, f in enumerate(frames) if f[6] >= 0), None)
    return None


def _draw(tracks, passes, size, origin):
    """Draw the visible parts of each frame in `passes`; a track is drawn at most once."""
    canvas = Image.new('RGBA', size)
    drawn = set()
    for k in passes:
        for name, frames, images in tracks:
            x, y, kx, ky, sx, sy, f, alpha = frames[k]
            if name in drawn or f < 0 or alpha <= 0 or not images[k] or 'blink' in name.lower() or \
                    name.lower().startswith(HIDDEN_PREFIXES):
                continue
            image = part(images[k])
            if image is None:
                continue
            drawn.add(name)
            # Part pixel (u, v) -> (a*u + c*v + x, b*u + d*v + y), as Reanimation::MatrixFromTransform.
            a, b = sx*math.cos(math.radians(kx)), sx*math.sin(math.radians(kx))
            c, d = -sy*math.sin(math.radians(ky)), sy*math.cos(math.radians(ky))
            det = a*d-b*c
            if abs(det) < 1e-6:
                continue
            ox, oy = x+origin[0], y+origin[1]
            ia, ib, ic, id_ = d/det, -c/det, -b/det, a/det
            layer = image.transform(size, AFFINE, (ia, ib, -ia*ox-ib*oy, ic, id_, -ic*ox-id_*oy), resample=BICUBIC)
            if alpha < 1:
                layer.putalpha(layer.getchannel('A').point(lambda v: round(v*alpha)))
            canvas.alpha_composite(layer)
    return canvas


@cache
def _sprite(seed):
    """(RGBA image, (x, y) of the plant origin inside it) or None when no art is available."""
    stem = plant_reanims().get(seed)
    tracks = definition(stem) if stem else None
    if not tracks:
        return None
    anim = next((a for a in FIRST_FRAME_ANIMS.get(seed, ())+IDLE_ANIMS if _first_frame(tracks, a) is not None), None)
    passes = [_first_frame(tracks, anim) if anim else 0]
    if anim != 'anim_full_idle':
        passes += [k for k in (_first_frame(tracks, a) for a in HEAD_ANIMS) if k is not None]
    size, origin = (240, 240), (80, 100)
    canvas = _draw(tracks, passes, size, origin)
    if seed in TINTS:
        *rgb, alpha = canvas.split()
        canvas = Image.merge('RGBA', [ch.point(lambda v, t=t: v*t//255) for ch, t in zip(rgb, TINTS[seed])]+[alpha])
    if seed in MIRRORED:
        canvas = canvas.transpose(FLIP_LEFT_RIGHT)
        origin = (size[0]-origin[0]-80, origin[1])
    return canvas, origin


@cache
def _mower(stem, anim):
    tracks = definition(stem)
    if not tracks:
        return None
    k = (_first_frame(tracks, anim) if anim else None) or 0
    size, origin = (200, 160), (60, 60)
    return _draw(tracks, [k], size, origin), origin


def sprite(seed):
    with _lock:
        return _sprite(seed)


def mower(mode):
    with _lock:
        return _mower(*(ROOF_MOWER if mode in ROOF_MODES else MOWER))


def _background(mode, scene):
    if scene in SCENE_BACKGROUND:
        path = GAME/SCENE_BACKGROUND[scene]
    elif scene.startswith('斗蛐蛐地图'):
        path = next((GAME/'newimages').glob(f'61-{scene}.*'))
    else:
        path = GAME/MODE_BACKGROUND['roof' if mode in ROOF_MODES else 'night' if mode in NIGHT_MODES else 'day']
    return Image.open(path).convert('RGBA').crop((BACKGROUND_X, 0, BACKGROUND_X+800, 600))


def cell_origin(mode, row, col):
    """Board::GridToPixelX/Y for the plant at (row, col)."""
    if mode in ROOF_MODES:
        return 40+80*col, 70+85*row+20*max(0, 5-col)
    return 40+80*col, 80+100*row


def _layers(cell):
    for p in cell if isinstance(cell, list) else [cell]:
        if p is not None:
            yield p if isinstance(p, dict) else {'id': p, 'xp': 0}


@cache
def _font(size):
    for name in ('msyhbd.ttc', 'arialbd.ttf', 'DejaVuSans-Bold.ttf', 'NotoSansCJK-Bold.ttc'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size)
    except TypeError:  # Pillow < 10.1: fixed-size bitmap font
        return ImageFont.load_default()


def board(formation, mode, scene, label=None):
    """800x600 picture of the formation; label(seed) -> short text for plants without art."""
    image = _background(mode, scene)
    draw = ImageDraw.Draw(image)
    cart = mower(mode)
    for row in range(len(formation)) if cart else ():
        picture, (ox, oy) = cart
        image.paste(picture, (MOWER_OFFSET[0]-ox, cell_origin(mode, row, 0)[1]+MOWER_OFFSET[1]-oy), picture)
    for row, cells in enumerate(formation):
        for col, cell in enumerate(cells):
            x, y = cell_origin(mode, row, col)
            for plant in _layers(cell):
                art = sprite(plant['id'])
                if art:
                    picture, (ox, oy) = art
                    image.paste(picture, (x-ox, y-oy), picture)  # background is opaque
                else:
                    draw.rounded_rectangle((x+8, y+20, x+72, y+84), 10, fill=(40, 60, 40, 200), outline='white')
                    draw.text((x+40, y+52), label(plant['id']) if label else str(plant['id']),
                              font=_font(30), fill='white', anchor='mm')
                if plant.get('xp'):
                    draw.text((x+40, y+92), str(plant['xp']), font=_font(16), fill='white', anchor='ms',
                              stroke_width=2, stroke_fill='black')
    return image
