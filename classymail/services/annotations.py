from pydantic import BaseModel, Field

class ImageDescription(BaseModel):
    """
    Structured description of visual content extracted from document images/bboxes.
    Used by Mistral Document AI bbox_annotation_format for rich image analysis.
    """
    image_type: str = Field(..., description="The type of the image: photo, bar chart, pie chart, line graph, logo, handwritten text, signature, stamp, form, table, diagram, map, ID document, invoice, etc.")
    summary: str = Field(..., description="Detailed description of the image content for accessibility. Include: what is shown, visible text/numbers/dates, colors, layout, and any annotations. Describe as if for someone who cannot see the image.")
    details: str = Field(..., description="Key business-relevant details: data points, amounts, dates, reference numbers, names, or text visible in the image that could help classify or understand the document.")
    is_relevant: bool = Field(..., description="True if this image contains content relevant to understanding a business email, claim, invoice, or transaction. False for decorative images, logos, or headers.")
