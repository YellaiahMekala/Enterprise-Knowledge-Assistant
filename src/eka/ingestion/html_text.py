"""Turn a fetched web page into Markdown text for the normal text loader (ADR-030).

Navigation, scripts, styles and forms are dropped; headings become ``#`` lines so the Markdown
loader splits the page into sections, list items become ``-`` lines and ``pre`` blocks become
fenced code. Standard library only: the page is untrusted and nothing in it is executed.
"""

from html.parser import HTMLParser

from eka.domain.models import WebPage

_SKIP = {
    "script",
    "style",
    "noscript",
    "svg",
    "nav",
    "footer",
    "form",
    "template",
    "iframe",
    "button",
    "select",
}
_BLOCK = {
    "p",
    "div",
    "section",
    "article",
    "main",
    "table",
    "tr",
    "ul",
    "ol",
    "dl",
    "dt",
    "dd",
    "blockquote",
    "br",
    "hr",
    "figure",
    "figcaption",
}
_HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 4, "h6": 4}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self.title = ""
        self._line: list[str] = []
        self._skip = 0
        self._pre = 0
        self._pre_text: list[str] = []
        self._in_title = False

    def _flush(self) -> None:
        line = " ".join("".join(self._line).split())
        if line:
            self.lines.append(line)
        self._line = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif self._skip:
            return
        elif tag in _HEADINGS:
            self._flush()
            self.lines.append("")
            self._line.append("#" * _HEADINGS[tag] + " ")
        elif tag == "pre":
            if not self._pre:
                self._flush()
                self.lines.append("```")
            self._pre += 1
        elif tag == "li":
            self._flush()
            self._line.append("- ")
        elif tag in ("td", "th"):
            self._line.append(" | ")
        elif tag in _BLOCK:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag == "title":
            self._in_title = False
        elif self._skip:
            return
        elif tag == "pre" and self._pre:
            self._pre -= 1
            if not self._pre:
                self.lines.extend("".join(self._pre_text).strip("\n").splitlines())
                self.lines.extend(("```", ""))
                self._pre_text = []
        elif tag in _HEADINGS or tag in _BLOCK or tag == "li":
            self._flush()
            if tag in _HEADINGS or tag == "p":
                self.lines.append("")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif self._skip:
            return
        elif self._pre:
            self._pre_text.append(data)
        else:
            self._line.append(data)

    def close(self) -> None:
        super().close()
        self._flush()


def page_to_markdown(page: WebPage) -> tuple[str, str]:
    """``(title, markdown)`` for a fetched page; plain text passes through unchanged."""
    if page.content_type == "text/plain":
        return "", page.text.strip()
    extractor = _TextExtractor()
    extractor.feed(page.text)
    extractor.close()
    text = "\n".join(extractor.lines)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return " ".join(extractor.title.split()), text.strip()
