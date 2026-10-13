"""OCR local, preparação da foto e extração de documentos."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Callable

from .core import ID_PATTERN, ParseResult, parse_table_text


@dataclass
class ReadResult:
    parsed: ParseResult
    preview: object = None
    rotation: int = 0
    pages: dict = field(default_factory=dict)


def rectify(image):
    """Corrige perspectiva quando há uma borda quadrilateral grande (tabela)."""
    import cv2
    import numpy as np
    from PIL import Image

    rgb = np.asarray(image.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    bw = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 12)
    lines = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(lines, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    area = image.width * image.height
    for contour in sorted(contours, key=cv2.contourArea, reverse=True):
        if not .25 * area < cv2.contourArea(contour) < .98 * area:
            continue
        quad = cv2.approxPolyDP(contour, .015 * cv2.arcLength(contour, True), True)
        if len(quad) != 4 or not cv2.isContourConvex(quad):
            continue
        q = quad.reshape(4, 2).astype(np.float32)
        ordered = np.array([q[np.argmin(q.sum(1))], q[np.argmin(np.diff(q, axis=1))], q[np.argmax(q.sum(1))], q[np.argmax(np.diff(q, axis=1))]], np.float32)
        if len({tuple(p) for p in ordered}) != 4:
            continue
        tl, tr, br, bl = ordered
        w = round(max(np.linalg.norm(tr-tl), np.linalg.norm(br-bl)))
        h = round(max(np.linalg.norm(bl-tl), np.linalg.norm(br-tr)))
        if min(w, h) < 150:
            continue
        matrix = cv2.getPerspectiveTransform(ordered, np.float32([[0, 0], [w-1, 0], [w-1, h-1], [0, h-1]]))
        warped = cv2.warpPerspective(rgb, matrix, (w, h), borderValue=(255, 255, 255))
        return Image.fromarray(warped)
    return image


def group_lines(boxes, texts, scores) -> list[tuple[str, float]]:
    if not texts:
        return []
    items = []
    for box, text, score in zip(boxes, texts, scores):
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        width = max(xs)-min(xs)
        slope = ((ys[1]+ys[2])-(ys[0]+ys[3])) / max(1, (xs[1]+xs[2])-(xs[0]+xs[3]))
        height = ((ys[3]-ys[0])+(ys[2]-ys[1]))/2
        items.append((sum(xs)/4, sum(ys)/4, max(5,height), text, float(score), slope, width))
    reference_x = median(i[0] for i in items)
    adjusted = []
    for item in items:
        nearby = [i[5] for i in items if i[6] > 120 and abs(i[1]-item[1]) < 140 and abs(i[5]) < .2]
        slope = median(nearby) if nearby else 0
        adjusted.append((item[0], item[1]-slope*(item[0]-reference_x), *item[2:]))
    items = adjusted
    tolerance = max(3, median(i[2] for i in items) * .45)
    groups: list[list[tuple]] = []
    for item in sorted(items, key=lambda i: i[1]):
        if groups and abs(item[1] - median(i[1] for i in groups[-1])) < tolerance:
            groups[-1].append(item)
        else:
            groups.append([item])
    return [("  ".join(i[3] for i in sorted(row)), min(i[4] for i in row)) for row in groups]


class Reader:
    def __init__(self):
        self._engine = None

    def engine(self):
        if self._engine is None:
            from rapidocr import RapidOCR
            self._engine = RapidOCR(params={
                "EngineConfig.onnxruntime.intra_op_num_threads": 2,
                "Det.limit_side_len": 2200,
                "Det.limit_type": "max",
                "Global.max_side_len": 4000,
                "Global.text_score": .35,
                "Global.log_level": "error",
            })
        return self._engine

    def ocr(self, image, progress: Callable[[str], None]) -> list[tuple[str, float]]:
        import numpy as np
        from PIL import Image
        progress("Reconhecendo os textos da imagem…")
        image = image.convert("RGB")
        scale = min(2.0, 2600 / max(image.size))
        if scale != 1:
            image = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
        result = self.engine()(np.asarray(image), use_det=True, use_cls=True, use_rec=True)
        return group_lines(result.boxes, result.txts or [], result.scores or [])

    def table_image(self, image, source: str, rotation: int | None = None, progress=lambda _: None) -> ReadResult:
        from PIL import ImageOps
        from .table_ocr import detect_grid, find_header, read_grid
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((4000, 4000))
        rotations = [rotation] if rotation is not None else ([90, 0, 270, 180] if image.height > image.width else [0, 90, 180, 270])
        candidates = []
        for degrees in rotations:
            progress(f"Conferindo cabeçalhos e grade · orientação {degrees}°…")
            prepared = rectify(image.rotate(degrees, expand=True))
            grid = detect_grid(prepared)
            header = find_header(self, grid) if grid else None
            if header:
                candidates.append((header[0], degrees, grid, header))
        if candidates:
            _, degrees, grid, header = max(candidates, key=lambda item:item[0])
            parsed = read_grid(self, grid, header, source, progress)
            if len(candidates)>1 and candidates[0][0] == candidates[1][0]:
                parsed.warnings.append('Mais de uma orientação parece possível; confira os cabeçalhos e a ordem.')
            return ReadResult(parsed, grid.image, degrees, {source:grid.image})
        # Sem grade/cabeçalhos seguros, preservar o texto sem atribuir números a eixos.
        prepared = rectify(image.rotate(rotation or 0, expand=True))
        text = '\n'.join(t for t,_ in self.ocr(prepared,progress))
        parsed = parse_table_text(text, source)
        for p in parsed.points:
            p.x = p.y = None
            p.notes.append('Colunas não identificadas: coordenadas precisam de revisão manual.')
        parsed.warnings.append('Não foi possível identificar E/N e a grade. Tente outra orientação, um recorte da tabela ou uma lista CSV.')
        return ReadResult(parsed, prepared, rotation or 0, {source:prepared})

    def read_table(self, path: Path, rotation: int | None = None, progress=lambda _: None) -> ReadResult:
        from PIL import Image
        suffix = path.suffix.lower()
        if suffix in {".csv", ".txt", ""}:
            return ReadResult(parse_table_text(read_text(path), path.name))
        if suffix == ".pdf":
            import pymupdf
            combined = ParseResult()
            preview = None
            pages = {}
            with pymupdf.open(path) as document:
                if document.is_encrypted:
                    raise ValueError("PDF protegido. Salve uma cópia desbloqueada para leitura.")
                for idx, page in enumerate(document):
                    progress(f"Lendo tabela · página {idx+1}/{len(document)}…")
                    pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
                    im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    result = self.table_image(im, f"{path.name}, pág. {idx+1}", rotation, progress)
                    preview = preview or result.preview
                    pages.update(result.pages)
                    combined.points += result.parsed.points
                    combined.warnings += [f"Página {idx+1}: {w}" for w in result.parsed.warnings]
                    combined.text += f"\n--- Página {idx+1} ---\n{result.parsed.text}"
            return ReadResult(combined, preview, pages=pages)
        with Image.open(path) as im:
            return self.table_image(im, path.name, rotation, progress)

    def read_document(self, path: Path, rotation: int | None = None, progress=lambda _: None) -> str:
        from PIL import Image, ImageOps
        if path.suffix.lower() in {".txt", ".csv", ""}:
            return read_text(path)
        pages = []
        if path.suffix.lower() == ".pdf":
            import pymupdf
            with pymupdf.open(path) as doc:
                if doc.is_encrypted:
                    raise ValueError("PDF protegido. Salve uma cópia desbloqueada.")
                for i, page in enumerate(doc):
                    progress(f"Lendo memorial · página {i+1}/{len(doc)}…")
                    native = page.get_text(sort=True).strip()
                    if len(re.sub(r"\s", "", native)) > 40:
                        pages.append(native)
                    else:
                        pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
                        im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                        pages.append(self.document_image(im, rotation, progress))
        else:
            with Image.open(path) as im:
                pages.append(self.document_image(ImageOps.exif_transpose(im), rotation, progress))
        return "\n\n".join(pages)

    def document_image(self, image, rotation, progress):
        from .core import parse_memorial
        rotations = [rotation] if rotation is not None else [0, 90, 180, 270]
        best, best_score = "", -1
        for angle in rotations:
            progress(f'Lendo memorial · orientação {angle}°…')
            lines = self.ocr(image.rotate(angle, expand=True), progress)
            text = "\n".join(t for t, _ in lines)
            parsed = parse_memorial(text)
            score = sum(3*(p.latitude is not None and p.longitude is not None or p.x is not None and p.y is not None) + (p.distance is not None) for p in parsed.points)
            if score > best_score:
                best, best_score = text, score
        return best


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return path.read_text(encoding="cp1252")
