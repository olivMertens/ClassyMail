from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/docs/redoc-custom", include_in_schema=False)
async def custom_redoc(theme: str = "light"):
    """
    Serve a custom Redoc page with dark/light theme support.
    """
    redoc_js_url = "https://cdn.redoc.ly/redoc/latest/bundles/redoc.standalone.js"

    # Theme configuration for dark mode (Tailwind-ish colors)
    theme_config = "{}"
    if theme == "dark":
        # Values match typical tailwind gray-800/900 palette
        bg_color = "#1f2937"  # gray-800
        theme_config = """{
            "theme": {
                "colors": {
                    "primary": {
                        "main": "#3b82f6"
                    },
                    "text": {
                        "primary": "#f3f4f6",
                        "secondary": "#9ca3af"
                    },
                    "http": {
                        "get": "#22c55e",
                        "post": "#eab308",
                        "put": "#a855f7",
                        "delete": "#ef4444"
                    }
                },
                "typography": {
                    "fontFamily": "Inter, system-ui, sans-serif",
                    "headings": {
                        "fontFamily": "Inter, system-ui, sans-serif"
                    }
                },
                "sidebar": {
                    "backgroundColor": "#1f2937",
                    "textColor": "#f3f4f6",
                    "arrow": {
                        "color": "#9ca3af"
                    }
                },
                "rightPanel": {
                    "backgroundColor": "#111827",
                    "textColor": "#f3f4f6",
                    "servers": {
                        "overlay": {
                            "backgroundColor": "#1f2937",
                            "textColor": "#f3f4f6"
                        },
                        "url": {
                            "backgroundColor": "#374151"
                        }
                    }
                },
                "codeBlock": {
                    "backgroundColor": "#111827"
                }

            }
        }"""
    else:
        bg_color = "#ffffff"
        # Default light theme is fine, but we can explicit some defaults if needed
        # Leaving {} uses Redoc defaults

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <title>ClassificationG2S API</title>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://fonts.googleapis.com/css?family=Inter:300,400,600,700" rel="stylesheet">
    <style>
      body {{
        margin: 0;
        padding: 0;
        background-color: {bg_color};
      }}
    </style>
    </head>
    <body>
    <redoc spec-url="/openapi.json" theme='{theme_config}'></redoc>
    <script src="{redoc_js_url}"> </script>
    </body>
    </html>
    """
    return HTMLResponse(html)
