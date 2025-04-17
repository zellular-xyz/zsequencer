# Configuration file for the Sphinx documentation builder.

# -- Project information

project = "Zellular Sequencer"
copyright = "2021, Graziella"
author = "Graziella"

release = "0.1.0"
version = "0.1.0"

# -- General configuration

extensions = [
    "sphinx.ext.duration",
    "sphinx.ext.doctest",
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.intersphinx",
    "sphinx.ext.extlinks",
    "sphinx.ext.viewcode",
]

intersphinx_mapping = {
    "python": ("https://docs.python.org/3/", None),
    "sphinx": ("https://www.sphinx-doc.org/en/master/", None),
}
intersphinx_disabled_domains = ["std"]

templates_path = ["_templates"]

# -- Options for HTML output

html_theme = "sphinx_rtd_theme"

# -- Options for EPUB output
epub_show_urls = "footnote"

extlinks = {
    "src": (
        "https://github.com/zellular-xyz/zsequencer/blob/usecases/examples/%s",
        " %s",
    )
}
