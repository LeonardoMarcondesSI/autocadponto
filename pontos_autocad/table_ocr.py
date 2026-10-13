"""Leitura de tabelas pautadas por células; nunca desloca uma coluna vazia."""
from __future__ import annotations

import re
from dataclasses import dataclass
from statistics import median

from .core import ParseResult, azimuth, column_map, normal_id, number, parse_cells

FIELDS = ('code', 'x', 'y', 'altitude', 'destination', 'bearing', 'distance')


def normalize_cell(field, text):
    value = text.strip()
    if field in ('code','destination'):
        # Pontuação entre grupos, sem trocar letras por números.
        value = re.sub(r'(?<=[A-Za-z0-9])[·.](?=[A-Za-z0-9])', '-', value)
        value = re.sub(r'(?<=[A-Za-z])\s+(?=[A-Za-z]-\d)', '-', value)
        return normal_id(value)
    if field in ('x','y'):
        compact = value.replace(' ', '')
        # Grupos de milhar completos + exatamente 2 casas: separadores inequívocos.
        if re.fullmatch(r'[-+]?\d{1,3}(?:[.,]\d{3})+[.,]\d{2}', compact):
            pieces = re.split('[.,]',compact)
            return ''.join(pieces[:-1])+','+pieces[-1]
    return value


@dataclass
class Grid:
    image: object
    xs: list
    ys: list
    local_ys: list
    estimated: bool = False

    def box(self, row, col):
        return [self.xs[col], self.local_ys[col][row], self.xs[col+1], self.local_ys[col][row+1]]


def peaks(values, threshold):
    import numpy as np
    indices = np.flatnonzero(values > threshold)
    chunks = np.split(indices, np.where(np.diff(indices) > 2)[0] + 1)
    return [round(float(np.mean(c))) for c in chunks if len(c)]


def detect_grid(image):
    import cv2
    import numpy as np
    rgb = np.asarray(image.convert('RGB'))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    bw = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 12)
    horizontal = cv2.morphologyEx(bw, cv2.MORPH_OPEN, np.ones((1, max(20, image.width//15)), np.uint8))
    vertical = cv2.morphologyEx(bw, cv2.MORPH_OPEN, np.ones((max(20, image.height//15), 1), np.uint8))
    xs = peaks((vertical > 0).sum(0), image.height * .28)
    if not 3 <= len(xs) <= 14:
        return None
    typical = median(b-a for a,b in zip(xs,xs[1:]))
    if 3 < xs[0] < typical * 1.3:
        xs.insert(0, 0)
    if 3 < image.width-1-xs[-1] < typical * 1.3:
        xs.append(image.width-1)
    candidates = []
    for start, end in ((.10,.25),(.20,.35),(.35,.45)):
        a,b = round(image.width*start), round(image.width*end)
        candidates.append(peaks((horizontal[:,a:b] > 0).sum(1), (b-a)*.35))
    ys = max(candidates, key=len)
    if len(ys) < 4:
        return None
    gap = median(b-a for a,b in zip(ys,ys[1:]))
    if gap < 7:
        return None
    if 4 < ys[0] < 1.5*gap:
        ys.insert(0, 0)
    if 4 < image.height-1-ys[-1] < 1.5*gap:
        ys.append(image.height-1)
    filled = [ys[0]]
    estimated = False
    for a,b in zip(ys,ys[1:]):
        count = round((b-a)/gap)
        if 2 <= count <= 3 and abs((b-a)/count-gap) < gap*.18:
            filled.extend(round(a+(b-a)*i/count) for i in range(1,count))
            estimated = True
        filled.append(b)
    ys = filled
    local = []
    for xa,xb in zip(xs,xs[1:]):
        found = peaks((horizontal[:,xa+3:xb-3] > 0).sum(1), (xb-xa-6)*.3)
        local.append([min(found, key=lambda v:abs(v-y)) if found and min(abs(v-y) for v in found) < gap*.38 else y for y in ys])
    if any(b-a < 5 for values in local for a,b in zip(values, values[1:])):
        return None
    return Grid(image, xs, ys, local, estimated)


def recognize(reader, grid, positions, variant=0):
    import cv2
    import numpy as np
    from PIL import Image, ImageOps
    from rapidocr.ch_ppocr_rec.typings import TextRecInput
    cells = []
    for row,col in positions:
        xa,ya,xb,yb = grid.box(row,col)
        crop = grid.image.crop((xa+3,ya+2,xb-2,yb-1))
        crop = crop.resize((crop.width*4,crop.height*4), Image.Resampling.LANCZOS)
        if variant:
            gray = np.asarray(crop.convert('L'))
            gray = cv2.createCLAHE(clipLimit=2, tileGridSize=(4,4)).apply(gray)
            crop = Image.fromarray(gray).convert('RGB')
        cells.append(np.asarray(ImageOps.expand(crop, border=8, fill='white')))
    if not cells:
        return []
    reader.engine()(cells[0], use_det=False, use_cls=False, use_rec=True)
    out = reader.engine().text_rec(TextRecInput(img=cells))
    return list(zip(out.txts, map(float, out.scores)))


def find_header(reader, grid):
    width = len(grid.xs)-1
    positions = [(r,c) for r in range(min(3,len(grid.ys)-1)) for c in range(width)]
    results = recognize(reader, grid, positions)
    best = None
    for r in range(min(3,len(grid.ys)-1)):
        texts = [t for t,_ in results[r*width:(r+1)*width]]
        # Variações ortográficas do OCR de rótulos; nenhum dígito dos dados é corrigido.
        texts = [re.sub(r'(?i)^azimuto$', 'Azimute', t) for t in texts]
        texts = [re.sub(r'(?i)^dint\.', 'Dist.', t) for t in texts]
        texts = [re.sub(r'(?i)^(aititude|atitude)', 'Altitude', t) for t in texts]
        mapping = column_map(texts)
        score = len(mapping)
        if all(k in mapping for k in ('code','x','y')) and (best is None or score > best[0]):
            best = (score, r, mapping)
    return best


def valid_value(field, text):
    text = normalize_cell(field,text)
    try:
        if field in ('code', 'destination'):
            return bool(re.fullmatch(r'[A-Z]+(?:-[A-Z]+)?-\d+', normal_id(text)))
        if field == 'bearing':
            return '°' in text or 'º' in text if 0 <= azimuth(text) < 360 else False
        return number(text) >= 0 if field == 'distance' else bool(text) and number(text) is not None
    except ValueError:
        return False


def page_cells(reader, grid, mapping, full=False):
    import numpy as np
    from PIL import Image
    xmax = grid.image.width if full else grid.xs[max(mapping.values())+1]
    scale = min(2, 2600/max(xmax,grid.image.height)) if full else min(3, 3000/max(xmax,grid.image.height))
    crop = grid.image.crop((0,0,xmax,grid.image.height))
    result = reader.engine()(np.asarray(crop.resize((round(crop.width*scale),round(crop.height*scale)),Image.Resampling.LANCZOS)),use_det=True,use_cls=True,use_rec=True)
    values = {}
    if result.boxes is None:
        return values
    for box,text,score in zip(result.boxes,result.txts,result.scores):
        xs,ys = [float(p[0])/scale for p in box],[float(p[1])/scale for p in box]
        cx,cy = sum(xs)/4,sum(ys)/4
        for col in mapping.values():
            if not grid.xs[col] < cx < grid.xs[col+1]:
                continue
            for row in range(len(grid.ys)-1):
                a,b = grid.local_ys[col][row:row+2]
                if a < cy < b and max(ys)-min(ys) < (b-a)*1.6 and max(xs)-min(xs) < (grid.xs[col+1]-grid.xs[col])*1.25:
                    old = values.get((row,col))
                    if old is None or score > old[1]:
                        values[(row,col)] = (text,float(score))
                    break
            break
    return values


def read_grid(reader, grid, header, source, progress):
    _, header_row, mapping = header
    fields = [f for f in FIELDS if f in mapping]
    rows = range(header_row+1,len(grid.ys)-1)
    positions = [(r,mapping[f]) for r in rows for f in fields]
    progress('Lendo cada célula da tabela…')
    values = recognize(reader, grid, positions)
    progress('Conferindo as células com uma leitura das colunas…')
    page_values = page_cells(reader,grid,mapping)
    full_values = page_cells(reader,grid,mapping,full=True)
    retry = [i for i, (text,score) in enumerate(values) if score < .97 or not valid_value(fields[i%len(fields)],text)]
    if retry:
        progress(f'Relendo {len(retry)} células com baixa legibilidade…')
    alternatives = dict(zip(retry, recognize(reader, grid, [positions[i] for i in retry], variant=1)))
    parsed = ParseResult()
    if grid.estimated:
        parsed.warnings.append('Algumas divisões de linha foram estimadas pela grade; confira a quantidade de vértices.')
    for row_index, r in enumerate(rows):
        cells = {f:'' for f in FIELDS}
        notes, confidence, ambiguous = [], {}, set()
        for k,f in enumerate(fields):
            idx = row_index*len(fields)+k
            text, score = values[idx]
            candidates = [(text,score)] + ([alternatives[idx]] if idx in alternatives else []) + ([page_values[positions[idx]]] if positions[idx] in page_values else []) + ([full_values[positions[idx]]] if positions[idx] in full_values else [])
            valid = [(t,s) for t,s in candidates if valid_value(f,t)]
            text,score = max(valid or candidates,key=lambda item:item[1])
            distinct = set(normalize_cell(f,t) for t,_ in candidates if t.strip())
            if len(distinct)>1:
                notes.append(f"Releituras de {f}: {' / '.join(repr(v) for v in sorted(distinct))}; confira na foto")
            if f in ('x','y','distance','bearing'):
                convert = azimuth if f=='bearing' else number
                numbers = {round(convert(normalize_cell(f,t)),8) for t,s in valid if s>=.85}
                if len(numbers)>1:
                    ambiguous.add(f)
            normalized = normalize_cell(f,text)
            if normalized != text and f in ('x','y'):
                notes.append(f'Separadores de {f} interpretados: {text} → {normalized}; confira na foto')
            cells[f],confidence[f] = normalized,score
        p = parse_cells([cells[f] for f in FIELDS], source, min(confidence.values()), r)
        p.raw += '\nOCR original: ' + ' | '.join(values[row_index*len(fields)+k][0] for k in range(len(fields)))
        for f in ambiguous:
            setattr(p,f,None)
            notes.append(f'Campo {f} pendente: as leituras produziram números diferentes; selecione a linha para conferir.')
        p.notes += notes
        p.field_confidence = confidence
        p.field_boxes = {f:grid.box(r,mapping[f]) for f in fields}
        p.box = [grid.xs[0],min(grid.local_ys[c][r] for c in mapping.values()), grid.xs[-1],max(grid.local_ys[c][r+1] for c in mapping.values())]
        if not cells['code'] or not valid_value('code',cells['code']):
            p.notes.append('Identificação não reconhecida com segurança; conferir esta linha')
        if 'destination' in mapping and (not p.destination or p.distance is None or p.bearing is None):
            p.notes.append('Trecho incompleto: conferir destino, distância e azimute')
        parsed.points.append(p)
    for p in parsed.points:
        if p.destination and p.destination not in {q.code for q in parsed.points}:
            key=re.sub(r'[^A-Z0-9]','',p.destination)
            matches=[q.code for q in parsed.points if re.sub(r'[^A-Z0-9]','',q.code)==key]
            if len(matches)==1:
                p.notes.append(f'Destino associado pela pontuação: {p.destination} → {matches[0]}; confira na foto')
                p.destination=matches[0]
    parsed.text = '\n'.join(p.raw for p in parsed.points)
    parsed.warnings.append(f'Grade: {len(parsed.points)} linhas de dados. Confira se corresponde à tabela original.')
    return parsed
