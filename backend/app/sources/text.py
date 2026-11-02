"""Turn listing HTML into plain text, keeping paragraph breaks."""

import re
from html.parser import HTMLParser

_BLOCK_TAGS = {
    "p", "div", "ul", "ol", "table", "tr", "section", "article",
    "h1", "h2", "h3", "h4", "h5", "h6",
}  # fmt: skip
_HIDDEN_TAGS = {"script", "style"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _HIDDEN_TAGS:
            self._hidden += 1
        elif tag == "br":
            self.parts.append("\n")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _HIDDEN_TAGS:
            self._hidden = max(0, self._hidden - 1)
        elif tag == "li":
            self.parts.append("\n")
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if not self._hidden:
            self.parts.append(re.sub(r"\s+", " ", data))


def html_to_text(html: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(html)
    extractor.close()
    lines = (re.sub(r" +", " ", line).strip() for line in "".join(extractor.parts).split("\n"))
    text = "\n".join(lines)
    text = re.sub(r"^-\n+", "- ", text, flags=re.MULTILINE)  # <li><p>…</p></li>
    text = re.sub(r"^(- .*)\n\n+(?=- )", r"\1\n", text, flags=re.MULTILINE)  # same, between items
    return re.sub(r"\n{3,}", "\n\n", text).strip()
