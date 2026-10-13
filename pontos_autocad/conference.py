"""Conferência documental: totais, vértices, sequência e medições por trecho."""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import replace

from .core import Check, Point, compare, validate
from .geometry import contour_measures
from .georef import GeoReference


def id_signature(code):
    return re.sub(r'[^A-Z0-9]','',code.upper()).replace('O','0')


def code_suggestions(table: list[Point], memorial: list[Point]) -> dict[str,str]:
    known={p.code for p in table}
    used={p.code for p in memorial}
    suggestions={}
    for code in used | {p.destination for p in memorial if p.destination}:
        if code in known: continue
        matches=[target for target in known if id_signature(code)==id_signature(target)]
        if len(matches)==1 and matches[0] not in used:
            suggestions[code]=matches[0]
    counts=Counter(suggestions.values())
    return {old:new for old,new in suggestions.items() if counts[new]==1}


def contour_issues(points: list[Point], close=True) -> list[str]:
    issues = validate(points)
    if issues:
        return issues
    measure = contour_measures(points, close)
    if close and measure.area_m2 is None or not close and measure.length_m is None:
        issues.append(measure.note)
    rows = points[:-1] if close and len(points)>1 and points[0].code == points[-1].code else points
    for i,p in enumerate(rows):
        expected = rows[(i+1)%len(rows)].code if close or i+1 < len(rows) else ''
        if p.destination and p.destination != expected:
            issues.append(f'{p.code}: destino {p.destination}; próximo ponto na ordem do desenho: {expected or "fim da linha"}.')
    return list(dict.fromkeys(issues))


def order_by_destinations(points: list[Point]) -> list[Point]:
    if not points or len({p.code for p in points}) != len(points):
        raise ValueError('A lista precisa ter identificações únicas.')
    lookup = {p.code:p for p in points}
    ordered, seen, current = [],set(),points[0]
    while current.code not in seen:
        ordered.append(current)
        seen.add(current.code)
        if current.destination not in lookup:
            raise ValueError(f'{current.code}: destino ausente na tabela.')
        current = lookup[current.destination]
    if current.code != points[0].code or len(ordered) != len(points):
        raise ValueError('Os destinos não formam um único contorno fechado com todos os pontos.')
    if contour_issues(ordered):
        raise ValueError('A sequência pelos destinos ainda forma um contorno inválido; confira os pontos.')
    return ordered


def verify_documents(table: list[Point], memorial: list[Point], *, coord_tol=.02, dist_tol=.05, az_tol_minutes=1.,
                     area_m2=None, perimeter_m=None, area_tol=1., perimeter_tol=.1,
                     georef: GeoReference | None = None, measurement_mode='Não informado', close=True,
                     totals_same_basis=True) -> list[Check]:
    if any(not math.isfinite(v) or v < 0 for v in (coord_tol,dist_tol,az_tol_minutes,area_tol,perimeter_tol)):
        raise ValueError('As tolerâncias precisam ser finitas e não negativas.')
    checks = compare(table, [], coord_tol, dist_tol, az_tol_minutes)
    for c in checks:
        c.origin = 'Planta × cálculo'
    issues = contour_issues(table,close)
    checks.append(Check('Contorno','Ordem e fechamento','Geometria','contorno válido', 'pendências' if issues else 'válido','', 'PENDENTE' if issues else 'CONFERE','; '.join(issues)))
    measures = contour_measures(table,close)
    total_note = 'Comparação numérica de totais; confirme que ambos representam medidas planas no mesmo sistema.'
    for field,declared,computed,tol in [('Área (m²)',area_m2,measures.area_m2,area_tol),('Perímetro (m)',perimeter_m,measures.perimeter_m,perimeter_tol)]:
        delta = abs(declared-computed) if declared is not None and computed is not None else None
        state = ('CONFERE' if delta <= tol+1e-9 else 'DIVERGE') if delta is not None and totals_same_basis and not issues else 'PENDENTE'
        reason = 'Informe o total declarado no memorial.' if declared is None else measures.note if computed is None else '; '.join(issues) if issues else total_note
        checks.append(Check('Memorial × planta','Total',field,'' if declared is None else f'{declared:.4f}', '' if computed is None else f'{computed:.4f}', '' if delta is None else f'{delta:.4f}',state,reason))
    if not memorial:
        checks.append(Check('Memorial','Documento','Cobertura','vértices interpretados','nenhum','','PENDENTE','Carregue e interprete o memorial para conferir o contorno.'))
        return checks
    transformed = memorial
    transform_note, accuracy = '',0
    if any(p.longitude is not None or p.latitude is not None for p in memorial):
        try:
            transformed, accuracy = (georef or GeoReference()).project(memorial)
            if accuracy < 0 or accuracy > coord_tol:
                transform_note = f'Precisão declarada da transformação: {accuracy} m; insuficiente ou desconhecida para a tolerância de {coord_tol} m.'
        except Exception as exc:
            transformed = [replace(p,x=None,y=None) if p.longitude is not None or p.latitude is not None else p for p in memorial]
            transform_note = str(exc)
        checks.append(Check('Coordenadas','Referência','Conversão',f'{(georef or GeoReference()).source_crs or "não informado"}',f'{(georef or GeoReference()).target_crs or "não informado"}','','PENDENTE' if transform_note else 'CONFERE',transform_note))
    tc,mc = Counter(p.code for p in table), Counter(p.code for p in transformed)
    ti,mi = {p.code:p for p in table if tc[p.code]==1},{p.code:p for p in transformed if mc[p.code]==1}
    for origin, counts in [('Planta',tc),('Memorial',mc)]:
        for code,count in counts.items():
            if count>1:
                checks.append(Check(origin,code,'Identificação','única',f'{count} ocorrências','','PENDENTE','Resolva a identificação repetida.'))
    for code in sorted(set(tc)|set(mc)):
        a,b = ti.get(code),mi.get(code)
        if a is None or b is None:
            checks.append(Check('Memorial × planta',code,'Cobertura','presente nos dois documentos','ausente ou repetido','','PENDENTE','Confira também possíveis trocas de O/0 nos códigos.'))
            continue
        if b.notes:
            checks.append(Check('Memorial',code,'Leitura','','revisar','','PENDENTE','; '.join(b.notes)))
        if None in (a.x,a.y,b.x,b.y):
            checks.append(Check('Memorial × planta',code,'Posição E/N (m)','coordenadas completas','incompleto ou sem conversão','','PENDENTE',transform_note))
        else:
            d = math.hypot(a.x-b.x,a.y-b.y)
            checks.append(Check('Memorial × planta',code,'Posição E/N (m)',f'{b.x:.4f}; {b.y:.4f}',f'{a.x:.4f}; {a.y:.4f}',f'{d:.4f}','PENDENTE' if transform_note else 'CONFERE' if d <= coord_tol+1e-9 else 'DIVERGE',transform_note))
        destinations_ok = bool(a.destination and b.destination and a.destination == b.destination)
        uncertain_id=bool(a.destination and b.destination and id_signature(a.destination)==id_signature(b.destination) and a.destination!=b.destination)
        checks.append(Check('Memorial × planta',code,'Próximo vértice',b.destination or 'não lido',a.destination or 'não informado','','CONFERE' if destinations_ok else 'DIVERGE' if a.destination and b.destination and not uncertain_id else 'PENDENTE','Possível diferença de pontuação ou O/0; confira os códigos na fonte.' if uncertain_id else ''))
        for field,attr,tol in [('Distância (m)','distance',dist_tol),('Azimute (min)','bearing',az_tol_minutes)]:
            va,vb = getattr(a,attr),getattr(b,attr)
            d = None if va is None or vb is None else abs((va-vb+180)%360-180)*60 if attr=='bearing' else abs(va-vb)
            reason = 'Campo ausente em um dos documentos.' if d is None else 'Trechos com destinos diferentes.' if not destinations_ok else 'Tipos de medida não equivalentes ou não informados.' if measurement_mode != 'Grade da planta' else ''
            checks.append(Check('Memorial × planta',f'{code} → {b.destination or "?"}',field,'' if vb is None else f'{vb:.6f}','' if va is None else f'{va:.6f}','' if d is None else f'{d:.4f}','PENDENTE' if reason else 'CONFERE' if d <= tol+1e-9 else 'DIVERGE',reason))
    if measurement_mode == 'Grade da planta':
        geometry_checks = compare(table, transformed, coord_tol,dist_tol,az_tol_minutes)
        for c in geometry_checks:
            if c.origin == 'Memorial' and c.field in ('Distância (m)','Azimute (°)'):
                c.origin = 'Memorial × cálculo'
                checks.append(c)
    return checks
