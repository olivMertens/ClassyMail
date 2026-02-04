
from classificationg2s.services.pipeline import chunk_markdown


def test_chunk_markdown_basic():
    """Test basic chunking functionality"""
    text = "a" * 1000
    chunks = chunk_markdown(text, chunk_size=500, overlap=50)
    assert len(chunks) >= 2
    assert all(isinstance(c, dict) for c in chunks)
    assert  all("content" in c and "index" in c for c in chunks)


def test_chunk_markdown_empty():
    assert chunk_markdown("") == []
    assert chunk_markdown(None) == []
