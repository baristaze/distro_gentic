"""The platform assistant's corpus: the documents the knowledge map lists
for the tenant's users, and the passages a search answers with, each
naming the document it came from so an answer can cite it."""

from pydantic import Field

from acme.om.base import Platform


class Listing(Platform):
    """One line of the knowledge map: a document's title and its path from
    the map's folder."""

    title: str = Field(min_length=1)
    path: str = Field(min_length=1)


class Document(Platform):
    title: str = Field(min_length=1)
    path: str = Field(min_length=1)
    text: str


class Corpus(Platform):
    """What the assistant may quote, and nothing else: the documents one
    audience of the knowledge map is served."""

    audience: str = Field(min_length=1)
    documents: tuple[Document, ...] = ()


class Passage(Platform):
    """One section of a document: its citation (the document's path and the
    heading the section sits under) and its text."""

    path: str
    title: str
    heading: str
    text: str
