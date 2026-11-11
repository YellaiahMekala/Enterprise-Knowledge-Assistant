"""Web page to Markdown (ADR-030): the text that reaches the normal Markdown loader."""

from eka.domain.models import WebPage
from eka.ingestion.html_text import page_to_markdown
from eka.ingestion.loaders.text_file import load_text

PAGE = """<!doctype html><html><head><title> Classes &amp; Objects </title>
<style>body { color: red }</style><script>alert("x")</script></head>
<body><nav><a href="/">Home</a> | <a href="/next">Next</a></nav>
<header><h1>Classes</h1></header>
<main><p>A class bundles <b>data</b> and   behaviour.</p>
<h2>Defining a class</h2><p>Use the <code>class</code> keyword:</p>
<pre><span>class</span> Dog:
    pass</pre>
<ul><li>attributes</li><li>methods</li></ul>
<table><tr><th>Name</th><th>Kind</th></tr><tr><td>self</td><td>parameter</td></tr></table>
<form><input name="q"><button>Search</button></form></main>
<footer>Copyright</footer></body></html>"""


def test_html_becomes_markdown_without_scripts_or_navigation() -> None:
    title, text = page_to_markdown(WebPage("https://d.example/c", "text/html", PAGE))
    assert title == "Classes & Objects"
    assert text.splitlines() == [
        "# Classes",
        "",
        "A class bundles data and behaviour.",
        "",
        "## Defining a class",
        "",
        "Use the class keyword:",
        "",
        "```",
        "class Dog:",
        "    pass",
        "```",
        "",
        "- attributes",
        "- methods",
        "| Name | Kind",
        "| self | parameter",
    ]
    for dropped in ("alert", "color", "Home", "Search", "Copyright"):
        assert dropped not in text


def test_plain_text_passes_through() -> None:
    assert page_to_markdown(WebPage("https://d.example/t", "text/plain", " a\nb \n")) == (
        "",
        "a\nb",
    )


def test_the_markdown_loader_reads_the_page_with_line_locators() -> None:
    _, text = page_to_markdown(WebPage("https://d.example/c", "text/html", PAGE))
    segments = load_text(text.encode(), "d.example_c.md")
    assert "".join(s.text for s in segments).count("## Defining a class") == 1
    assert all(s.locator["type"] == "lines" for s in segments)
