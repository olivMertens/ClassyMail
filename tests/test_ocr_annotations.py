from classymail.services.llm_pipeline import _combine_ocr_pages

def test_combine_ocr_pages_normalizes_bboxes():
    ocr_pages = [
        {
            "markdown": "Page 1 content",
            "images": [
                {
                    "id": "img1",
                    "top_left_x": 0.1,
                    "top_left_y": 0.2,
                    "bottom_right_x": 0.3,
                    "bottom_right_y": 0.4,
                    "summary": "A chart"
                },
                {
                    "id": "img2",
                    "bbox": {"x_min": 0.5, "y_min": 0.6, "x_max": 0.7, "y_max": 0.8},
                    "summary": "A photo"
                }
            ]
        }
    ]

    content, annotated_images = _combine_ocr_pages(ocr_pages, enable_vision_enrichment=True)

    assert len(annotated_images) == 2

    # Check normalization
    assert annotated_images[0]["bbox"] == {
        "x_min": 0.1, "y_min": 0.2, "x_max": 0.3, "y_max": 0.4
    }

    # Check pass-through
    assert annotated_images[1]["bbox"] == {
        "x_min": 0.5, "y_min": 0.6, "x_max": 0.7, "y_max": 0.8
    }

    # Check markdown enrichment
    assert "Visual Elements Detected" in content
    assert "A chart" in content
    assert "A photo" in content

def test_combine_ocr_pages_handles_empty_bbox_fields():
    ocr_pages = [
        {
            "markdown": "Page 1",
            "images": [
                {
                    "id": "img1",
                    "summary": "Just a summary"
                }
            ]
        }
    ]

    _, annotated_images = _combine_ocr_pages(ocr_pages, enable_vision_enrichment=True)
    assert annotated_images[0]["bbox"] is None
