def test_import_app():
    from classymail.app import app  # noqa: F401


def test_import_worker():
    from classymail.worker_main import run  # noqa: F401
