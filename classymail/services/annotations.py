from pydantic import BaseModel, Field

class ImageDescription(BaseModel):
    """
    Structured description of visual content extracted from document images/bboxes.
    """
    image_type: str = Field(..., description="The type of the image (e.g., 'bar chart', 'photo', 'logo', 'handwritten text').")
    summary: str = Field(..., description="Brief summary of the image content.")
    details: str = Field(..., description="Key details, data points, or text visible in the image that are relevant for business context.")
    is_relevant: bool = Field(..., description="True if this image contains content likely relevant to an insurance request or business transaction.")
