"""
Minimal chromadb stub for local unit testing.

Provides just enough of the API surface for source modules to import
without error. All actual ChromaDB calls are replaced by MagicMock in
the unit tests themselves.
"""


class _MagicClass:
    """Generic stand-in for any chromadb class."""
    def __init__(self, *args, **kwargs):
        pass

    def __class_getitem__(cls, item):
        return cls


# Types referenced in type annotations / isinstance checks
HttpClient = _MagicClass
Collection = _MagicClass
EmbeddingFunction = _MagicClass


def HttpClient(*args, **kwargs):  # noqa: F811 – intentionally shadows class
    return _MagicClass()
