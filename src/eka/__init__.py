"""eka: chat with your documents, with answers that cite document, page and passage."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("eka")
except PackageNotFoundError:  # source tree that was never installed
    __version__ = "0.0.0"
