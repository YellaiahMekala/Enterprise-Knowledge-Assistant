# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Builders for test files, so no binary fixture has to be committed (Test Strategy section 5)."""

import io
import zipfile

from docx import Document
from pypdf import PdfReader, PdfWriter


def make_pdf(pages: list[str]) -> bytes:
    """A minimal valid PDF with one line-wrapped text page per entry (Helvetica, no images).
    An empty string produces a page with no text."""

    def escape(line: str) -> str:
        return line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    objects: list[bytes] = []

    def add(body: str | bytes) -> int:
        objects.append(body.encode("latin-1") if isinstance(body, str) else body)
        return len(objects)

    catalog = add("<< /Type /Catalog /Pages 2 0 R >>")
    pages_id = add("")  # filled in below once the page ids are known
    font = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    assert (catalog, pages_id, font) == (1, 2, 3)

    page_ids: list[int] = []
    for text in pages:
        lines = [escape(line) for line in text.split("\n")] if text else []
        stream = "BT /F1 12 Tf 14 TL 72 720 Td " + " T* ".join(f"({line}) Tj" for line in lines)
        stream += " ET" if lines else " ET"
        content = add(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        page_ids.append(
            add(
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 {font} 0 R >> >> /Contents {content} 0 R >>"
            )
        )
    kids = " ".join(f"{i} 0 R" for i in page_ids)
    objects[pages_id - 1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode()

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return out.getvalue()


def make_encrypted_pdf(password: str = "secret") -> bytes:
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(make_pdf(["Hidden text"]))))
    writer.encrypt(
        password, algorithm="RC4-128"
    )  # AES would need the cryptography package to write
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def make_docx(blocks: list[tuple[str, str]], table: list[list[str]] | None = None) -> bytes:
    """``blocks`` are ``(style, text)`` pairs such as ``("Heading 1", "Leave")`` or
    ``("Normal", "Five days...")``. An optional table is appended at the end."""
    document = Document()
    for style, text in blocks:
        if style.startswith("Heading") or style == "Title":
            level = 0 if style == "Title" else int(style.split()[-1])
            document.add_heading(text, level=level)
        else:
            document.add_paragraph(text, style=style)
    if table:
        grid = document.add_table(rows=len(table), cols=len(table[0]))
        for r, row in enumerate(table):
            for c, value in enumerate(row):
                grid.cell(r, c).text = value
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def make_zip_bomb_docx() -> bytes:
    """Tiny when compressed, huge when expanded, and shaped like a DOCX."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", b"0" * (60 * 1024 * 1024))
    return out.getvalue()


def make_many_entries_docx(entries: int = 2_500) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<w/>")
        for i in range(entries):
            archive.writestr(f"extra/{i}.txt", "x")
    return out.getvalue()


JAVA_SAMPLE = """package demo;

import java.util.List;

/** A small example. */
public class Greeter {
    private final String name;

    public Greeter(String name) {
        this.name = name;
    }

    /** Says hello. The string below has a brace: "}" and a comment { */
    public String greet() {
        String brace = "}";
        // an unbalanced { in a comment
        return "Hello, " + name + brace;
    }

    public List<String> names() {
        return List.of(name);
    }
}
"""
