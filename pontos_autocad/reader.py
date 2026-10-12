"""OCR local, preparação da foto e extração de documentos."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Callable

from .core import ID_PATTERN, ParseResult, parse_table_text


@dataclass
class ReadResult:
    parsed: ParseResult
    preview: object = None
    rotation: int = 0


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
        items.append((sum(xs)/4, sum(ys)/4, max(ys)-min(ys), text, float(score)))
    tolerance = max(4, median(i[2] for i in items) * .65)
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
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((4000, 4000))
        rotations = [rotation] if rotation is not None else ([90, 0, 270, 180] if image.height > image.width else [0, 90, 180, 270])
        best, best_score = None, -1
        for degrees in rotations:
            progress(f"Preparando a tabela · orientação {degrees}°…")
            prepared = rectify(image.rotate(degrees, expand=True))
            lines = self.ocr(prepared, progress)
            text = "\n".join(line for line, _ in lines)
            parsed = parse_table_text(text, source)
            for p in parsed.points:
                for line, score in lines:
                    if p.raw == line:
                        p.confidence = score
                        if score < .95:
                            p.notes.append("Confiança OCR baixa: conferir os valores na imagem")
                        break
            score = sum(p.x is not None and p.y is not None for p in parsed.points)
            if score > best_score:
                best, best_score = ReadResult(parsed, prepared, degrees), score
            if score >= 3:
                break
        if not best.parsed.points:
            best.parsed.warnings.append("Não foi possível organizar a tabela. Tente outra orientação ou uma foto mais próxima.")
        best.parsed.warnings.append("Revise a quantidade de linhas, as identificações e os dígitos. Confiança OCR não garante exatidão.")
        return best

    def read_table(self, path: Path, rotation: int | None = None, progress=lambda _: None) -> ReadResult:
        from PIL import Image
        suffix = path.suffix.lower()
        if suffix in {".csv", ".txt", ""}:
            return ReadResult(parse_table_text(read_text(path), path.name))
        if suffix == ".pdf":
            import pymupdf
            combined = ParseResult()
            preview = None
            with pymupdf.open(path) as document:
                if document.is_encrypted:
                    raise ValueError("PDF protegido. Salve uma cópia desbloqueada para leitura.")
                for idx, page in enumerate(document):
                    progress(f"Lendo tabela · página {idx+1}/{len(document)}…")
                    pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
                    im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    result = self.table_image(im, f"{path.name}, pág. {idx+1}", rotation, progress)
                    preview = preview or result.preview
                    combined.points += result.parsed.points
                    combined.warnings += [f"Página {idx+1}: {w}" for w in result.parsed.warnings]
                    combined.text += f"\n--- Página {idx+1} ---\n{result.parsed.text}"
            return ReadResult(combined, preview)
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
        rotations = [rotation] if rotation is not None else [0, 90, 180, 270]
        best, best_score = "", -1
        for angle in rotations:
            lines = self.ocr(image.rotate(angle, expand=True), progress)
            text = "\n".join(t for t, _ in lines)
            score = len(re.findall(r"(?:v[eé]rtice|coordenada|dist[aâ]ncia|azimute|norte)", text, re.I))
            if score > best_score:
                best, best_score = text, score
            if score >= 2:
                break
        return best


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return path.read_text(encoding="cp1252")
