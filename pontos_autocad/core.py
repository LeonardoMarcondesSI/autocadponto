"""Regras de leitura, comparação e exportação, independentes da interface."""
from __future__ import annotations

import csv
import io
import math
import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path


ID_PATTERN = r"[A-Za-z0-9]+(?:\s*[-–—]\s*[A-Za-z0-9]+)+"
NUMBER_PATTERN = r"[-+]?\d[\d.,]*"


def normal_id(value: str) -> str:
    return re.sub(r"\s+", "", value.replace("–", "-").replace("—", "-")).upper()


def number(value: str | float | int) -> float:
    """Aceita decimal brasileiro e decimal de máquina; não corrige dígitos OCR."""
    s = str(value).strip().replace("\u00a0", "").replace(" ", "")
    if not re.fullmatch(r"[-+]?\d+(?:[.,]\d+)*", s):
        raise ValueError(f"Número inválido: {value!r}")
    if "," in s and "." in s:
        decimal, grouping = (",", ".") if s.rfind(",") > s.rfind(".") else (".", ",")
        left, right = s.rsplit(decimal, 1)
        if decimal in left or not re.fullmatch(r"[-+]?\d{1,3}(?:" + re.escape(grouping) + r"\d{3})+", left):
            raise ValueError(f"Separadores inconsistentes: {value!r}")
        s = left.replace(grouping, "") + "." + right
    elif "," in s:
        if s.count(",") != 1:
            raise ValueError(f"Separadores inconsistentes: {value!r}")
        s = s.replace(",", ".")
    elif s.count(".") > 1:
        if not re.fullmatch(r"[-+]?\d{1,3}(?:\.\d{3})+", s):
            raise ValueError(f"Separadores inconsistentes: {value!r}")
        s = s.replace(".", "")
    elif re.fullmatch(r"[-+]?\d{1,3}\.\d{3}", s):
        # 123.456 pode ser 123456 ou 123,456: exigir uma escolha explícita.
        raise ValueError(f"Número ambíguo: {value!r}. Use vírgula decimal ou retire o ponto de milhar.")
    result = float(s)
    if not math.isfinite(result):
        raise ValueError("O número precisa ser finito.")
    return result


def azimuth(value: str) -> float:
    s = value.strip().replace("º", "°").replace("′", "'").replace("’", "'").replace("″", '"')
    match = re.fullmatch(r"(\d{1,3})\s*°\s*(\d{1,2})?\s*'?\s*(\d{1,2}(?:[.,]\d+)?)?\s*\"?", s)
    if match:
        degrees = int(match[1])
        minutes = int(match[2] or 0)
        seconds = float((match[3] or "0").replace(",", "."))
        if minutes >= 60 or seconds >= 60:
            raise ValueError("Minutos e segundos devem ser menores que 60.")
        result = degrees + minutes / 60 + seconds / 3600
    else:
        result = number(s)
    if not 0 <= result < 360:
        raise ValueError("Azimute deve estar entre 0 e menos de 360 graus.")
    return result


@dataclass
class Point:
    code: str
    x: float | None
    y: float | None
    destination: str = ""
    distance: float | None = None
    bearing: float | None = None
    confidence: float | None = None
    source: str = ""
    raw: str = ""
    notes: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> Point:
        p = cls(**{key: val for key, val in data.items() if key in cls.__dataclass_fields__})
        p.code, p.destination = normal_id(p.code), normal_id(p.destination)
        for name in ("x", "y", "distance", "bearing", "confidence"):
            value = getattr(p, name)
            if value is not None and (not isinstance(value, (int, float)) or not math.isfinite(value)):
                raise ValueError(f"Campo {name} inválido no projeto.")
        if not isinstance(p.notes, list) or not all(isinstance(n, str) for n in p.notes):
            raise ValueError("Observações inválidas no projeto.")
        return p


@dataclass
class ParseResult:
    points: list[Point] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    text: str = ""


def optional_number(text: str, notes: list[str], label: str) -> float | None:
    try:
        return number(text)
    except ValueError:
        notes.append(f"Conferir {label}: {text or '(vazio)'}")
        return None


def parse_cells(cells: list[str], source: str = "", confidence: float | None = None, row: int = 0) -> Point:
    """Tabela da referência: código, E, N, altitude, destino, azimute, distância."""
    cells = [c.strip() for c in cells]
    cells += [""] * max(0, 7 - len(cells))
    notes: list[str] = []
    code = normal_id(cells[0])
    if not re.fullmatch(ID_PATTERN, code):
        notes.append("Conferir identificação do ponto")
        code = code or f"REVISAR-LINHA-{row}"
    x = optional_number(cells[1], notes, "E/X")
    y = optional_number(cells[2], notes, "N/Y")
    destination = normal_id(cells[4])
    bearing, distance = None, None
    if cells[5]:
        try:
            bearing = azimuth(cells[5])
        except ValueError:
            notes.append(f"Conferir azimute: {cells[5]}")
    if cells[6]:
        distance = optional_number(cells[6], notes, "distância")
    if confidence is not None and confidence < .95:
        notes.append("Leitura OCR com confiança baixa; conferir na foto")
    return Point(code, x, y, destination, distance, bearing, confidence, source, " | ".join(cells), notes)


def parse_table_text(text: str, source: str = "texto") -> ParseResult:
    result = ParseResult(text=text)
    for line_no, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s:
            continue
        # CSV com separador explícito; coordenadas decimais com vírgula exigem ; ou aspas.
        cells = None
        if ";" in s:
            cells = next(csv.reader([s], delimiter=";"))
        elif "\t" in s:
            cells = s.split("\t")
        elif re.match(r"[^,]+,[-+]?\d+\.\d+,[-+]?\d+\.\d+", s):
            cells = next(csv.reader([s]))
        if cells and len(cells) >= 3:
            if normal_id(cells[0]) in {"CODIGO", "CÓDIGO", "ID", "PONTO", "CODE"}:
                continue
            # CSV exportado: código;E;N;destino;distância;azimute.
            if len(cells) == 6:
                p = parse_cells([cells[0], cells[1], cells[2], "", cells[3], cells[5], cells[4]], source, row=line_no)
            else:
                p = parse_cells(cells, source, row=line_no)
            result.points.append(p)
            continue
        matches = [m for m in re.finditer(ID_PATTERN, s) if any(c.isdigit() for c in m[0])]
        if not matches:
            if re.search(r"\d{5,}", s):
                result.warnings.append(f"Linha {line_no} não interpretada: {s[:120]}")
            continue
        first = matches[0]
        stop = matches[1].start() if len(matches) > 1 else len(s)
        # Conservar os tokens inteiros: "456.2O2,76" deve falhar, nunca virar 456.2 e 2,76.
        nums = re.split(r"\s+|\s*\|\s*", s[first.end():stop].strip())
        nums = [token for token in nums if token]
        if len(nums) < 2:
            result.points.append(Point(normal_id(first[0]), None, None, source=source, raw=s, notes=["Linha sem duas coordenadas legíveis"]))
            continue
        cells = [first[0], nums[0], nums[1], nums[2] if len(nums) > 2 else "", "", "", ""]
        if len(matches) > 1:
            cells[4] = matches[1][0]
            tail = s[matches[1].end():].strip()
            parts = re.split(r"\s{2,}", tail)
            a = re.match(r"\d{1,3}\s*[°º]\s*\d{1,2}\s*['′’]?(?:\s*\d{1,2}\s*[\"″])?", tail)
            if len(parts) >= 2:
                cells[5], cells[6] = parts[0], parts[1]
            elif a:
                cells[5] = a[0]
                rest = tail[a.end():].strip().split()
                if rest:
                    cells[6] = rest[0]
        point = parse_cells(cells, source, row=line_no)
        point.raw = s
        if point.destination and (point.bearing is None or point.distance is None):
            point.notes.append("Trecho com azimute ou distância não interpretado; conferir na fonte")
        result.points.append(point)
    return result


def parse_memorial(text: str) -> ParseResult:
    """Lê vértices identificados e E/N explícitos. Nunca deduz coordenadas sem rótulos."""
    result = ParseResult(text=text)
    normalized = unicodedata.normalize("NFKD", text)
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))
    anchor = re.compile(r"\b(?:vertice|ponto|marco)\s+(?:denominado\s+)?[\"']?(" + ID_PATTERN + r"|[A-Za-z]*\d+)\b", re.I)
    matches = list(anchor.finditer(normalized))
    coordinate_token = r"([-+]?\d[\w.,]*)(?=\s|[;)]|$)"
    axis_e = re.compile(r"\b(?:E|X|(?i:Este|Leste))\s*(?:=|:)?\s*" + coordinate_token)
    axis_n = re.compile(r"\b(?:N|Y|(?i:Norte))\s*(?:=|:)?\s*" + coordinate_token)
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
        chunk = normalized[match.end():end]
        notes: list[str] = []
        me, mn = axis_e.search(chunk), axis_n.search(chunk)
        x = optional_number(me[1].rstrip(",."), notes, "E/X") if me else None
        y = optional_number(mn[1].rstrip(",."), notes, "N/Y") if mn else None
        md = re.search(r"distancia\s*(?:de|:|=)?\s*(" + NUMBER_PATTERN + r")\s*(?:m\b|metros\b)", chunk, re.I)
        ma = re.search(r"azimute\s*(?:de|:|=)?\s*(\d{1,3}\s*[°º]\s*\d{1,2}\s*['′’]?(?:\s*\d{1,2}(?:[.,]\d+)?\s*[\"″])?|\d+(?:[.,]\d+)?)(?![\w.,°º])", chunk, re.I)
        destination = normal_id(matches[index + 1][1]) if (md or ma) and index + 1 < len(matches) else ""
        distance = optional_number(md[1], notes, "distância") if md else None
        bearing = None
        if not md and re.search(r"\bdistancia\b", chunk, re.I):
            notes.append("Distância mencionada mas não interpretada; conferir no texto")
        if not ma and re.search(r"\bazimute\b", chunk, re.I):
            notes.append("Azimute mencionado mas não interpretado; conferir no texto")
        if ma:
            try:
                bearing = azimuth(ma[1])
            except ValueError:
                notes.append(f"Azimute não interpretado: {ma[1]}")
        if x is not None or y is not None or md or ma or notes:
            result.points.append(Point(normal_id(match[1]), x, y, destination, distance, bearing, source="memorial", raw=normalized[match.start():end], notes=notes))
        elif normal_id(match[1]) not in {p.code for p in result.points}:
            result.warnings.append(f"Menção a {match[1]} sem coordenadas ou trecho interpretável.")
    if not matches:
        result = parse_table_text(text, "memorial")
        if not result.points:
            result.warnings.append("Nenhum vértice interpretado. Use a tabela editável ou texto com 'vértice ID, E ..., N ...'.")
    return result


def validate(points: list[Point]) -> list[str]:
    problems = []
    if not points:
        return ["A tabela está vazia."]
    duplicates = {c for c, n in Counter(p.code for p in points).items() if n > 1}
    for p in points:
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{0,79}", p.code) or p.code.startswith("REVISAR-LINHA-"):
            problems.append(f"Identificação inválida: {p.code!r}")
        if p.code in duplicates:
            problems.append(f"Identificação repetida: {p.code}")
        if p.x is None or p.y is None or not all(math.isfinite(v) for v in (p.x, p.y) if v is not None):
            problems.append(f"{p.code}: coordenadas incompletas ou inválidas.")
        if p.distance is not None and (not math.isfinite(p.distance) or p.distance < 0):
            problems.append(f"{p.code}: distância inválida.")
        if p.bearing is not None and (not math.isfinite(p.bearing) or not 0 <= p.bearing < 360):
            problems.append(f"{p.code}: azimute inválido.")
    return list(dict.fromkeys(problems))


def segment(a: Point, b: Point) -> tuple[float, float | None]:
    if None in (a.x, a.y, b.x, b.y):
        raise ValueError("Coordenadas incompletas.")
    dx, dy = b.x - a.x, b.y - a.y
    length = math.hypot(dx, dy)
    return length, math.degrees(math.atan2(dx, dy)) % 360 if length > 0 else None


@dataclass
class Check:
    origin: str
    item: str
    field: str
    reference: str
    calculated: str
    difference: str
    status: str
    note: str = ""


def compare(table: list[Point], memorial: list[Point], coord_tol: float = .02, dist_tol: float = .05, az_tol_minutes: float = 1.0) -> list[Check]:
    if any(not math.isfinite(t) or t < 0 for t in (coord_tol, dist_tol, az_tol_minutes)):
        raise ValueError("Tolerâncias devem ser números finitos e não negativos.")
    checks: list[Check] = []
    duplicates = {c for c, n in Counter(p.code for p in table).items() if n > 1}
    index = {p.code: p for p in table if p.code not in duplicates}
    for c in sorted(duplicates):
        checks.append(Check("Tabela", c, "Identificação", "única", "repetida", "", "PENDENTE", "Resolva as duplicatas antes de comparar."))
    for origin, rows in (("Tabela", table), ("Memorial", memorial)):
        for p in rows:
            if p.notes:
                checks.append(Check(origin, p.code, "Leitura", "", "revisão necessária", "", "PENDENTE", "; ".join(p.notes)))
            elif p.destination and (p.distance is None or p.bearing is None):
                missing = " e ".join(label for label, value in (("distância", p.distance), ("azimute", p.bearing)) if value is None)
                checks.append(Check(origin, p.code, "Trecho incompleto", missing, "não informado", "", "PENDENTE", "O destino está definido, mas faltam valores para a conferência completa."))
            a = index.get(p.code)
            if a is None or a.x is None or a.y is None:
                checks.append(Check(origin, p.code, "Coordenadas", "ponto válido", "ausente ou incompleto", "", "PENDENTE"))
                continue
            if origin == "Memorial":
                if p.x is not None and p.y is not None:
                    delta = math.hypot(a.x - p.x, a.y - p.y)
                    checks.append(Check(origin, p.code, "Posição E/N (m)", f"{p.x:.3f}; {p.y:.3f}", f"{a.x:.3f}; {a.y:.3f}", f"{delta:.4f}", "CONFERE" if delta <= coord_tol + 1e-9 else "DIVERGE"))
                else:
                    checks.append(Check(origin, p.code, "Posição E/N (m)", "duas coordenadas", "incompleto no memorial", "", "PENDENTE"))
            if p.distance is None and p.bearing is None:
                continue
            b = index.get(p.destination)
            item = f"{p.code} → {p.destination or '?'}"
            if b is None or b.x is None or b.y is None:
                checks.append(Check(origin, item, "Trecho", "destino válido", "ausente ou incompleto", "", "PENDENTE"))
                continue
            length, bearing = segment(a, b)
            if p.distance is not None:
                delta = abs(length - p.distance)
                checks.append(Check(origin, item, "Distância (m)", f"{p.distance:.4f}", f"{length:.4f}", f"{delta:.4f}", "CONFERE" if delta <= dist_tol + 1e-9 else "DIVERGE"))
            if p.bearing is not None:
                if bearing is None:
                    checks.append(Check(origin, item, "Azimute (°)", f"{p.bearing:.6f}", "indefinido", "", "PENDENTE", "Pontos coincidentes."))
                else:
                    delta = abs((bearing - p.bearing + 180) % 360 - 180) * 60
                    checks.append(Check(origin, item, "Azimute (°)", f"{p.bearing:.6f}", f"{bearing:.6f}", f"{delta:.4f} min", "CONFERE" if delta <= az_tol_minutes + 1e-9 else "DIVERGE"))
    if memorial:
        present = {p.code for p in memorial}
        for p in table:
            if p.code not in present:
                checks.append(Check("Memorial", p.code, "Cobertura", "ponto da tabela", "não identificado no memorial", "", "PENDENTE"))
    return checks


def make_script(points: list[Point], contour: bool = False, close: bool = True) -> str:
    errors = validate(points)
    if errors:
        raise ValueError("\n".join(errors))
    if contour and len(points) < (3 if close else 2):
        raise ValueError("Contorno fechado exige ao menos 3 pontos; linha aberta exige 2.")
    commands = ["_.UNDO", "_Begin", "_.UCS", "_World", "_.SETVAR", "ELEVATION", "0", "_.SETVAR", "THICKNESS", "0"]
    if contour:
        commands += ["_.SETVAR", "PLINEWID", "0", "_.PLINE"]
        for p in points:
            commands += ["_non", f"{p.x:.6f},{p.y:.6f}"]
        commands += ["_Close" if close else ""]
    else:
        commands += ["_.PDMODE", "35", "_.PDSIZE", "-2"]
        for p in points:
            commands += ["_.POINT", "_non", f"{p.x:.6f},{p.y:.6f},0"]
    commands += ["_.UNDO", "_End", "_.REGEN", "_.ZOOM", "_Extents", ""]
    return "\n".join(commands) + "\n"


def points_csv(points: list[Point]) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";", lineterminator="\n")
    writer.writerow(["Codigo", "E", "N", "Destino", "Distancia_m", "Azimute_graus"])
    for p in points:
        writer.writerow([p.code, *[(f"{v:.6f}".replace(".", ",") if v is not None else "") for v in (p.x, p.y)], p.destination, *[(f"{v:.6f}".replace(".", ",") if v is not None else "") for v in (p.distance, p.bearing)]])
    return output.getvalue()


def checks_csv(checks: list[Check], settings: str = "") -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";", lineterminator="\n")
    writer.writerow(["Origem", "Ponto/Trecho", "Campo", "Documento", "Calculado/Tabela", "Diferenca", "Situacao", "Observacao", "Criterios"])
    for c in checks:
        writer.writerow([*asdict(c).values(), settings])
    return output.getvalue()


def export_files(directory: Path, points: list[Point], contour: bool = True, close: bool = True) -> list[Path]:
    # Validar todo o conjunto antes de escrever qualquer arquivo.
    scripts = {"pontos_pontos.scr": make_script(points)}
    if contour:
        scripts["pontos_contorno.scr"] = make_script(points, True, close)
    directory.mkdir(parents=True, exist_ok=True)
    for name, text in scripts.items():
        (directory / name).write_text(text, encoding="ascii", newline="\r\n")
    (directory / "pontos.csv").write_text(points_csv(points), encoding="utf-8-sig")
    return [directory / name for name in [*scripts, "pontos.csv"]]
