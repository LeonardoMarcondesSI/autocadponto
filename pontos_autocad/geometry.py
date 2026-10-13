"""Medidas planas da sequência exibida na prévia, com E/N em metros."""
from __future__ import annotations

import math
from dataclasses import dataclass

from .core import Point


@dataclass(frozen=True)
class ContourMeasures:
    area_m2: float | None = None
    perimeter_m: float | None = None
    length_m: float | None = None
    note: str = ""


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a, b, c):
    return min(a[0], b[0]) <= c[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= c[1] <= max(a[1], b[1])


def _intersects(a, b, c, d):
    ab_c, ab_d, cd_a, cd_b = _cross(a, b, c), _cross(a, b, d), _cross(c, d, a), _cross(c, d, b)
    if ((ab_c > 0 > ab_d) or (ab_d > 0 > ab_c)) and ((cd_a > 0 > cd_b) or (cd_b > 0 > cd_a)):
        return True
    return any((cross == 0 and _on_segment(start, end, point)) for cross, start, end, point in (
        (ab_c, a, b, c), (ab_d, a, b, d), (cd_a, c, d, a), (cd_b, c, d, b)
    ))


def contour_measures(points: list[Point], close: bool = True) -> ContourMeasures:
    """Não completa coordenadas nem muda a ordem dos vértices."""
    if not points:
        return ContourMeasures(note="Importe os pontos para calcular as medidas.")
    if any(p.x is None or p.y is None or not math.isfinite(p.x) or not math.isfinite(p.y) for p in points):
        return ContourMeasures(note="Complete ou corrija todas as coordenadas E/N.")
    # Origem local reduz a perda de precisão com coordenadas UTM grandes.
    x0, y0 = points[0].x, points[0].y
    xy = [(p.x - x0, p.y - y0) for p in points]
    if close and len(xy) > 1 and xy[-1] == xy[0]:
        xy.pop()  # Aceita a repetição explícita do primeiro vértice no final.
    if len(xy) < (3 if close else 2):
        return ContourMeasures(note="Use pelo menos 3 pontos para a área e o perímetro." if close else "Use pelo menos 2 pontos para o comprimento.")
    path = xy + [xy[0]] if close else xy
    length = math.fsum(math.dist(a, b) for a, b in zip(path, path[1:]))
    if not math.isfinite(length):
        return ContourMeasures(note="As coordenadas excedem o limite de cálculo; confira os valores.")
    if not close:
        return ContourMeasures(length_m=length, note="Contorno aberto: feche o contorno para calcular área e perímetro.")
    if len(set(xy)) != len(xy):
        return ContourMeasures(length_m=length, note="Há posições repetidas no contorno; confira os pontos.")
    n = len(xy)
    for i, b in enumerate(xy):
        a, c = xy[i - 1], xy[(i + 1) % n]
        if _cross(a, b, c) == 0 and (a[0] - b[0]) * (c[0] - b[0]) + (a[1] - b[1]) * (c[1] - b[1]) > 0:
            return ContourMeasures(length_m=length, note="Há trechos sobrepostos; confira a ordem dos pontos.")
    edges = list(zip(path, path[1:]))
    for i, (a, b) in enumerate(edges):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue  # Primeiro e último segmentos são adjacentes.
            if _intersects(a, b, *edges[j]):
                return ContourMeasures(length_m=length, note="Contorno cruzado ou com trechos sobrepostos; confira a ordem dos pontos.")
    area = abs(math.fsum(a[0] * b[1] - b[0] * a[1] for a, b in edges)) / 2
    if not math.isfinite(area) or area == 0:
        return ContourMeasures(length_m=length, note="Os pontos não formam uma área válida; confira o contorno.")
    return ContourMeasures(area_m2=area, perimeter_m=length)
