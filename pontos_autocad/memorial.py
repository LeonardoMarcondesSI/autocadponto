"""Interpretação de memorial em E/N ou latitude/longitude, sem deduzir datum."""
from __future__ import annotations

import re
import unicodedata

from .core import ID_PATTERN, ParseResult, Point, azimuth, normal_id, number, optional_number, parse_table_text

DMS = r"(\d{1,3})\s*[°º]\s*(\d{1,2})\s*['′’]\s*(\d{1,2}(?:[.,]\d+)?)\s*[\"″”]?\s*([NSEWOL])"
BEARING = r"\d{1,3}\s*[°º]\s*\d{1,2}\s*['′’]?(?:\s*\d{1,2}(?:[.,]\d+)?\s*[\"″])?"
TOKEN = r"[-+]?\d[\w.,]*"


def geographic(value: str, latitude: bool = False) -> float:
    m = re.fullmatch(DMS, value.strip(), re.I)
    if not m:
        raise ValueError("Use graus, minutos, segundos e hemisfério, como 22°15'04,272\" S.")
    d, minute, second = int(m[1]), int(m[2]), float(m[3].replace(',', '.'))
    hemi = m[4].upper()
    limit = 90 if latitude else 180
    if minute >= 60 or second >= 60 or d > limit or (d == limit and (minute or second)) or hemi not in ("NS" if latitude else "EWOL"):
        raise ValueError("Latitude/longitude ou hemisfério inválido.")
    return (d + minute / 60 + second / 3600) * (-1 if hemi in "SWO" else 1)


def parse_document(text: str) -> ParseResult:
    normalized = ''.join(c for c in unicodedata.normalize('NFKD', text.replace('²', '2')) if not unicodedata.combining(c))
    normalized = normalized.replace('–', '-').replace('—', '-')
    # Remove apenas espaços junto ao hífen, inclusive quebra de página no código.
    normalized = re.sub(r'(?<=[A-Za-z0-9])-\s+(?=[A-Za-z0-9])', '-', normalized)
    normalized = re.sub(r'(?<=[A-Za-z0-9])\s+-', '-', normalized)
    anchor = re.compile(r'\b(?:vertice|ponto|marco)\s+(?:denominado\s+)?[\"\']?(' + ID_PATTERN + r'|[A-Za-z]*\d+)\b', re.I)
    matches = list(anchor.finditer(normalized))
    if not matches:
        result = parse_table_text(text, 'memorial')
        result.warnings.append('Não foram reconhecidos vértices no texto; confira a interpretação.')
        return result
    result = ParseResult(text=text)
    header = normalized[:matches[0].start()]
    for attr, pattern in [('area_m2', r'\barea\s*[:=]?\s*(' + TOKEN + r')\s*(ha|m2)\b'), ('perimeter_m', r'\bperimetro\s*[:=]?\s*(' + TOKEN + r')\s*(m|metros)\b')]:
        m = re.search(pattern, header, re.I)
        if m:
            try:
                value = number(m[1]) * (10000 if m[2].lower() == 'ha' else 1)
                if value <= 0:
                    raise ValueError('Total deve ser positivo.')
                setattr(result, attr, value)
            except ValueError:
                result.warnings.append(f"Total do memorial não interpretado: {m[0]}")
    for i, match in enumerate(matches):
        chunk = normalized[match.end():matches[i+1].start() if i+1 < len(matches) else len(normalized)]
        p = Point(normal_id(match[1]), None, None, source='memorial', raw=normalized[match.start():match.end()] + chunk)
        for axis, pattern in [('x', r'\b(?:E|X|(?i:Este|Leste))'), ('y', r'\b(?:N|Y|(?i:Norte))')]:
            m = re.search(pattern + r'\s*(?:=|:)?\s*(' + TOKEN + r')(?=\s|[;)]|$)', chunk)
            if m:
                setattr(p, axis, optional_number(m[1].rstrip(',.'), p.notes, axis.upper()))
        for field, label in [('longitude', r'Lon(?:g(?:itude)?)?'), ('latitude', r'Lat(?:itude)?')]:
            prefix = re.search(r'\b' + label + r'\s*[:;=]?\s*', chunk, re.I)
            if prefix:
                m = re.match(DMS, chunk[prefix.end():], re.I)
                try:
                    if not m:
                        raise ValueError()
                    setattr(p, field, geographic(m[0], field == 'latitude'))
                except ValueError:
                    p.notes.append(f"Conferir {'latitude' if field == 'latitude' else 'longitude'} no texto original")
        m = re.search(r'\bAltitude\s*[:=]?\s*(' + TOKEN + r')\s*m\b', chunk, re.I)
        if m:
            p.altitude = optional_number(m[1], p.notes, 'altitude')
        pair = re.search('(' + BEARING + r')\s*e\s*(?:de\s*)?(' + TOKEN + r')\s*m\b', chunk, re.I)
        ma = re.search(r'\bazimute\s*(?:de|:|=)?\s*(' + BEARING + r'|\d+(?:[.,]\d+)?)(?![\w.,°º])', chunk, re.I)
        md = re.search(r'\bdistancia\s*(?:de|:|=)?\s*(' + TOKEN + r')\s*(?:m\b|metros\b)', chunk, re.I)
        bearing = pair[1] if pair else ma[1] if ma else None
        distance = pair[2] if pair else md[1] if md else None
        if bearing:
            try:
                p.bearing = azimuth(bearing)
            except ValueError:
                p.notes.append(f'Conferir azimute: {bearing}')
        if distance:
            p.distance = optional_number(distance, p.notes, 'distância')
        if i+1 < len(matches):
            p.destination = normal_id(matches[i+1][1])
            if p.distance is None or p.bearing is None:
                p.notes.append('Trecho sem distância ou azimute interpretado; conferir o texto')
        if p.x is None or p.y is None:
            if p.latitude is None or p.longitude is None:
                p.notes.append('Coordenadas incompletas no memorial')
        if re.search(r'(?:0[A-Z]|[A-Z]0)', p.code):
            p.notes.append('Identificador com letra junto de zero: conferir O/0 na fonte')
        result.points.append(p)
    # Repetição final descreve o fechamento, não um vértice adicional.
    if len(result.points) > 1 and result.points[-1].code == result.points[0].code and not result.points[-1].destination:
        last, first = result.points[-1], result.points[0]
        for field in ('x', 'y', 'longitude', 'latitude', 'altitude'):
            a, b = getattr(first, field), getattr(last, field)
            if a is not None and b is not None and abs(a-b) > 1e-8:
                result.warnings.append(f'{first.code}: valor de {field} no fechamento difere do início.')
        if (last.x is not None or last.y is not None or last.latitude is not None or last.longitude is not None) and last.notes:
            result.warnings.extend(f'Fechamento: {n}' for n in last.notes)
        result.points.pop()
    return result
