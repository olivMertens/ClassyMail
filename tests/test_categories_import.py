"""
Tests for Excel category import API endpoint.

Tests cover Excel file parsing, category creation/update, slug generation,
replace vs. merge modes, and error handling.
"""

import io
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from openpyxl import Workbook
from fastapi import UploadFile

from classymail.api.categories_import import (
    import_categories_from_excel,
    parse_excel_categories,
    slugify_category_name
)


def create_test_excel(rows: list[tuple]) -> bytes:
    """Helper to create test Excel file with given rows."""
    wb = Workbook()
    ws = wb.active

    # Add header
    ws.append(["Nom de l'Intention", "Définition", "Exclusion"])

    # Add data rows
    for row in rows:
        ws.append(row)

    # Save to bytes
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.read()


@pytest.mark.asyncio
async def test_slugify_category_name():
    """Test slug generation from category names."""
    assert slugify_category_name("Documents Logement") == "documents_logement"
    assert slugify_category_name("Bail et Quittances") == "bail_et_quittances"
    assert slugify_category_name("Déclaration d'Impôts") == "declaration_dimpots"
    assert slugify_category_name("Test   Multiple   Spaces") == "test_multiple_spaces"
    assert slugify_category_name("Test-Dash_Under") == "test_dash_under"
    assert slugify_category_name("  Trim Spaces  ") == "trim_spaces"
    assert slugify_category_name("Ça c'est l'été") == "ca_cest_lete"


@pytest.mark.asyncio
async def test_parse_excel_basic():
    """Test parsing basic Excel file."""
    rows = [
        ("Bail", "Contrat de location", "Pas de facture"),
        ("Quittance", "Preuve de paiement", "Pas de reçu"),
    ]
    excel_bytes = create_test_excel(rows)

    categories = parse_excel_categories(excel_bytes)

    assert len(categories) == 2
    assert categories[0]["name"] == "Bail"
    assert categories[0]["definition"] == "Contrat de location"
    assert categories[0]["exclusion"] == "Pas de facture"
    assert categories[1]["name"] == "Quittance"


@pytest.mark.asyncio
async def test_parse_excel_empty_cells():
    """Test parsing Excel with empty definition/exclusion cells."""
    rows = [
        ("Bail", "", ""),
        ("Quittance", "Definition only", ""),
        ("Facture", "", "Exclusion only"),
    ]
    excel_bytes = create_test_excel(rows)

    categories = parse_excel_categories(excel_bytes)

    assert len(categories) == 3
    assert categories[0]["name"] == "Bail"
    assert categories[0]["definition"] == ""
    assert categories[0]["exclusion"] == ""
    assert categories[1]["definition"] == "Definition only"
    assert categories[2]["exclusion"] == "Exclusion only"


@pytest.mark.asyncio
async def test_parse_excel_skip_empty_rows():
    """Test that empty rows are skipped."""
    rows = [
        ("Bail", "Contrat", "Pas facture"),
        ("", "", ""),  # Empty row
        (None, None, None),  # Null row
        ("Quittance", "Preuve", "Pas reçu"),
    ]
    excel_bytes = create_test_excel(rows)

    categories = parse_excel_categories(excel_bytes)

    assert len(categories) == 2
    assert categories[0]["name"] == "Bail"
    assert categories[1]["name"] == "Quittance"


@pytest.mark.asyncio
async def test_parse_excel_skip_header_rows():
    """Test that header-like rows are skipped."""
    rows = [
        ("Nom", "Definition", "Exclusion"),  # Header-like
        ("nom de l'intention", "Définition", "Exclusion"),  # Another header
        ("Bail", "Contrat", "Pas facture"),
    ]
    excel_bytes = create_test_excel(rows)

    categories = parse_excel_categories(excel_bytes)

    assert len(categories) == 1
    assert categories[0]["name"] == "Bail"


@pytest.mark.asyncio
async def test_import_categories_success_merge_mode():
    """Test successful category import in merge mode."""
    rows = [
        ("Bail", "Contrat de location", "Pas de facture"),
        ("Quittance", "Preuve de paiement", "Pas de reçu"),
    ]
    excel_bytes = create_test_excel(rows)

    # Mock UploadFile
    mock_file = MagicMock(spec=UploadFile)
    mock_file.filename = "categories.xlsx"
    mock_file.read = AsyncMock(return_value=excel_bytes)

    # Mock settings
    with patch("classymail.api.categories_import.load_settings") as mock_load, \
         patch("classymail.api.categories_import.save_settings"), \
         patch("classymail.services.settings_store.save_settings_async") as mock_save_async:

        mock_load.return_value = {"categories": []}
        mock_save_async.return_value = None

        mock_clients = AsyncMock()

        result = await import_categories_from_excel(
            file=mock_file,
            replace_mode=False,
            clients=mock_clients
        )

        assert result.total_rows == 2
        assert result.created == 2
        assert result.updated == 0
        assert result.skipped == 0
        assert len(result.errors) == 0
        assert len(result.categories) == 2


@pytest.mark.asyncio
async def test_import_categories_success_replace_mode():
    """Test successful category import in replace mode."""
    rows = [
        ("Bail", "Contrat de location", "Pas de facture"),
    ]
    excel_bytes = create_test_excel(rows)

    mock_file = MagicMock(spec=UploadFile)
    mock_file.filename = "categories.xlsx"
    mock_file.read = AsyncMock(return_value=excel_bytes)

    existing_categories = [
        {"name": "Old Category", "slug": "old_category", "description": "Old", "exclusions": ""}
    ]

    with patch("classymail.api.categories_import.load_settings") as mock_load, \
         patch("classymail.api.categories_import.save_settings") as mock_save, \
         patch("classymail.services.settings_store.save_settings_async") as mock_save_async:

        mock_load.return_value = {"categories": existing_categories}
        mock_save_async.return_value = None

        mock_clients = AsyncMock()

        result = await import_categories_from_excel(
            file=mock_file,
            replace_mode=True,
            clients=mock_clients
        )

        assert result.total_rows == 1
        assert result.created == 1

        # Verify that save_settings was called with only new categories
        call_args = mock_save.call_args
        saved_settings = call_args[0][0]
        assert len(saved_settings["categories"]) == 1
        assert saved_settings["categories"][0]["name"] == "Bail"


@pytest.mark.asyncio
async def test_import_categories_update_existing():
    """Test updating existing categories in merge mode."""
    rows = [
        ("Bail", "New definition", "New exclusions"),
    ]
    excel_bytes = create_test_excel(rows)

    mock_file = MagicMock(spec=UploadFile)
    mock_file.filename = "categories.xlsx"
    mock_file.read = AsyncMock(return_value=excel_bytes)

    existing_categories = [
        {"name": "Bail", "slug": "bail", "description": "Old definition", "exclusions": "Old exclusions"}
    ]

    with patch("classymail.api.categories_import.load_settings") as mock_load, \
         patch("classymail.api.categories_import.save_settings"), \
         patch("classymail.services.settings_store.save_settings_async") as mock_save_async:

        mock_load.return_value = {"categories": existing_categories}
        mock_save_async.return_value = None

        mock_clients = AsyncMock()

        result = await import_categories_from_excel(
            file=mock_file,
            replace_mode=False,
            clients=mock_clients
        )

        assert result.total_rows == 1
        assert result.created == 0
        assert result.updated == 1
        assert result.categories[0]["action"] == "updated"


@pytest.mark.asyncio
async def test_import_categories_merge_keeps_existing():
    """Test that merge mode keeps existing categories not in import."""
    rows = [
        ("New Category", "New definition", ""),
    ]
    excel_bytes = create_test_excel(rows)

    mock_file = MagicMock(spec=UploadFile)
    mock_file.filename = "categories.xlsx"
    mock_file.read = AsyncMock(return_value=excel_bytes)

    existing_categories = [
        {"name": "Existing Category", "slug": "existing_category", "description": "Keep me", "exclusions": ""}
    ]

    with patch("classymail.api.categories_import.load_settings") as mock_load, \
         patch("classymail.api.categories_import.save_settings") as mock_save, \
         patch("classymail.services.settings_store.save_settings_async") as mock_save_async:

        mock_load.return_value = {"categories": existing_categories}
        mock_save_async.return_value = None

        mock_clients = AsyncMock()

        await import_categories_from_excel(
            file=mock_file,
            replace_mode=False,
            clients=mock_clients
        )

        # Verify that existing category was kept
        call_args = mock_save.call_args
        saved_settings = call_args[0][0]
        assert len(saved_settings["categories"]) == 2
        slugs = [cat["slug"] for cat in saved_settings["categories"]]
        assert "existing_category" in slugs
        assert "new_category" in slugs


@pytest.mark.asyncio
async def test_import_categories_invalid_file_type():
    """Test error when file is not Excel."""
    from fastapi import HTTPException

    mock_file = MagicMock(spec=UploadFile)
    mock_file.filename = "categories.csv"

    mock_clients = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await import_categories_from_excel(
            file=mock_file,
            replace_mode=False,
            clients=mock_clients
        )

    assert exc_info.value.status_code == 400
    assert "Excel" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_import_categories_no_filename():
    """Test error when filename is None."""
    from fastapi import HTTPException

    mock_file = MagicMock(spec=UploadFile)
    mock_file.filename = None

    mock_clients = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await import_categories_from_excel(
            file=mock_file,
            replace_mode=False,
            clients=mock_clients
        )

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_import_categories_file_read_error():
    """Test error when file cannot be read."""
    from fastapi import HTTPException

    mock_file = MagicMock(spec=UploadFile)
    mock_file.filename = "categories.xlsx"
    mock_file.read = AsyncMock(side_effect=Exception("Cannot read file"))

    mock_clients = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await import_categories_from_excel(
            file=mock_file,
            replace_mode=False,
            clients=mock_clients
        )

    assert exc_info.value.status_code == 400
    assert "reading file" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_import_categories_empty_excel():
    """Test error when Excel file is empty."""
    from fastapi import HTTPException

    # Create empty workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["Nom de l'Intention", "Définition", "Exclusion"])  # Only header
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    excel_bytes = buffer.read()

    mock_file = MagicMock(spec=UploadFile)
    mock_file.filename = "categories.xlsx"
    mock_file.read = AsyncMock(return_value=excel_bytes)

    mock_clients = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await import_categories_from_excel(
            file=mock_file,
            replace_mode=False,
            clients=mock_clients
        )

    assert exc_info.value.status_code == 400
    assert "No valid categories" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_import_categories_invalid_excel_data():
    """Test error when Excel contains invalid data."""
    from fastapi import HTTPException

    # Create corrupt data
    excel_bytes = b"This is not a valid Excel file"

    mock_file = MagicMock(spec=UploadFile)
    mock_file.filename = "categories.xlsx"
    mock_file.read = AsyncMock(return_value=excel_bytes)

    mock_clients = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await import_categories_from_excel(
            file=mock_file,
            replace_mode=False,
            clients=mock_clients
        )

    assert exc_info.value.status_code == 400
    assert "parsing" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_import_categories_cannot_generate_slug():
    """Test handling of categories where slug cannot be generated."""
    rows = [
        ("Valid Name", "Definition", ""),
        ("!!!###", "", ""),  # Invalid name
        ("Another Valid", "Definition", ""),
    ]
    excel_bytes = create_test_excel(rows)

    mock_file = MagicMock(spec=UploadFile)
    mock_file.filename = "categories.xlsx"
    mock_file.read = AsyncMock(return_value=excel_bytes)

    with patch("classymail.api.categories_import.load_settings") as mock_load, \
         patch("classymail.api.categories_import.save_settings"), \
         patch("classymail.services.settings_store.save_settings_async") as mock_save_async:

        mock_load.return_value = {"categories": []}
        mock_save_async.return_value = None

        mock_clients = AsyncMock()

        result = await import_categories_from_excel(
            file=mock_file,
            replace_mode=False,
            clients=mock_clients
        )

        assert result.total_rows == 3
        assert result.created == 2  # Only valid ones
        assert result.skipped == 1
        assert len(result.errors) >= 1
        assert any("slug" in error.lower() for error in result.errors)


@pytest.mark.asyncio
async def test_import_categories_cosmos_sync_error():
    """Test that Cosmos DB sync errors are non-critical."""
    rows = [
        ("Bail", "Contrat", ""),
    ]
    excel_bytes = create_test_excel(rows)

    mock_file = MagicMock(spec=UploadFile)
    mock_file.filename = "categories.xlsx"
    mock_file.read = AsyncMock(return_value=excel_bytes)

    with patch("classymail.api.categories_import.load_settings") as mock_load, \
         patch("classymail.api.categories_import.save_settings"), \
         patch("classymail.services.settings_store.save_settings_async") as mock_save_async:

        mock_load.return_value = {"categories": []}
        mock_save_async.side_effect = Exception("Cosmos DB unavailable")

        mock_clients = AsyncMock()

        result = await import_categories_from_excel(
            file=mock_file,
            replace_mode=False,
            clients=mock_clients
        )

        # Import should succeed despite Cosmos error
        assert result.created == 1
        # But error should be recorded
        assert len(result.errors) >= 1
        assert any("Cosmos" in error for error in result.errors)


@pytest.mark.asyncio
async def test_import_categories_special_characters():
    """Test importing categories with special characters."""
    rows = [
        ("Déclaration d'Impôts", "Définition avec accents", "Exclusion spéciale"),
        ("Test & Special < >", "Definition", ""),
    ]
    excel_bytes = create_test_excel(rows)

    mock_file = MagicMock(spec=UploadFile)
    mock_file.filename = "categories.xlsx"
    mock_file.read = AsyncMock(return_value=excel_bytes)

    with patch("classymail.api.categories_import.load_settings") as mock_load, \
         patch("classymail.api.categories_import.save_settings") as mock_save, \
         patch("classymail.services.settings_store.save_settings_async") as mock_save_async:

        mock_load.return_value = {"categories": []}
        mock_save_async.return_value = None

        mock_clients = AsyncMock()

        result = await import_categories_from_excel(
            file=mock_file,
            replace_mode=False,
            clients=mock_clients
        )

        assert result.total_rows == 2
        assert result.created == 2

        # Verify slugs are properly sanitized
        call_args = mock_save.call_args
        saved_settings = call_args[0][0]
        slugs = [cat["slug"] for cat in saved_settings["categories"]]
        assert "declaration_dimpots" in slugs
        assert "test_special" in slugs


@pytest.mark.asyncio
async def test_import_categories_large_batch():
    """Test importing large number of categories."""
    # Create 100 categories
    rows = [(f"Category {i}", f"Definition {i}", f"Exclusion {i}") for i in range(100)]
    excel_bytes = create_test_excel(rows)

    mock_file = MagicMock(spec=UploadFile)
    mock_file.filename = "categories.xlsx"
    mock_file.read = AsyncMock(return_value=excel_bytes)

    with patch("classymail.api.categories_import.load_settings") as mock_load, \
         patch("classymail.api.categories_import.save_settings"), \
         patch("classymail.services.settings_store.save_settings_async") as mock_save_async:

        mock_load.return_value = {"categories": []}
        mock_save_async.return_value = None

        mock_clients = AsyncMock()

        result = await import_categories_from_excel(
            file=mock_file,
            replace_mode=False,
            clients=mock_clients
        )

        assert result.total_rows == 100
        assert result.created == 100
        assert result.skipped == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
