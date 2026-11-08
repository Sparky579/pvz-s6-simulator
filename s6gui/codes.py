"""Single-character formation text <-> numeric S6 configuration."""
from __future__ import annotations
import json
import re
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EMPTY = {'空', '.', '_', '-', '　', '无'}


@cache
def plants():
    entries = json.loads((ROOT/'plant_codes.json').read_text(encoding='utf-8'))
    codes = {e['code']: e for e in entries}
    if len(codes) != len(entries) or len({e['id'] for e in entries}) != len(entries):
        raise ValueError('plant_codes.json: codes and IDs must be unique')
    return codes


@cache
def by_id():
    return {e['id']: e for e in plants().values()}


def parse(text):
    """Parse five rows; each cell is one code, optionally followed by digits (initial XP).

    Rows are separated by new lines or '/'. Whitespace, commas and '|' are ignored.
    Returns a 5x5 formation list for s6.config.Config.
    """
    rows = [r for r in re.split(r'[\n/／]+', text) if r.strip()]
    if len(rows) != 5:
        raise ValueError(f'需要正好 5 行，当前 {len(rows)} 行')
    codes = plants()
    formation = []
    for number, row in enumerate(rows, 1):
        cells = []
        for code, xp in re.findall(r'(\D)(\d*)', re.sub(r'[\s,，|｜]', '', row)):
            if code in EMPTY:
                if xp:
                    raise ValueError(f'第 {number} 行：空位不能带经验')
                cells.append(None)
            elif code in codes:
                cells.append({'id': codes[code]['id'], 'xp': int(xp)} if xp else codes[code]['id'])
            else:
                raise ValueError(f'第 {number} 行：未知简称「{code}」')
        if len(cells) != 5:
            raise ValueError(f'第 {number} 行需要 5 格，当前 {len(cells)} 格')
        formation.append(cells)
    return formation


def format_formation(formation):
    """Inverse of parse for normalized configurations (first layer of each cell)."""
    lines = []
    for row in formation:
        line = ''
        for cell in row:
            layers = cell if isinstance(cell, list) else [cell]
            layers = [p for p in layers if p is not None]
            if not layers:
                line += '空'
                continue
            p = layers[0] if isinstance(layers[0], dict) else {'id': layers[0], 'xp': 0}
            entry = by_id().get(p['id'])
            line += (entry['code'] if entry else '?') + (str(p['xp']) if p.get('xp') else '')
        lines.append(line)
    return '\n'.join(lines)
