import json
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/docs/redoc-custom", include_in_schema=False)
async def custom_redoc(theme: str = "light"):
    """
    Serve a custom Redoc page with dark/light theme support.
    """
    redoc_js_url = "https://cdn.redoc.ly/redoc/latest/bundles/redoc.standalone.js"

    # Theme configuration
    # See Redoc theme docs: https://redocly.com/docs/api-reference-docs/configuration/theme/
    options = {
        "scrollYOffset": 50,
        "hideDownloadButton": True
    }

    bg_color = "#ffffff"

    if theme == "dark":
        bg_color = "#1f2937"  # tailwind gray-800
        options["theme"] = {
            "colors": {
                "primary": {
                    "main": "#60a5fa"  # blue-400 (lighter for dark mode)
                },
                "text": {
                    "primary": "#f3f4f6",  # gray-100
                    "secondary": "#d1d5db" # gray-300
                },
                "http": {
                    "get": "#4ade80",    # green-400
                    "post": "#facc15",   # yellow-400
                    "put": "#c084fc",    # purple-400
                    "delete": "#f87171"  # red-400
                }
            },
            "typography": {
                "fontFamily": "Inter, system-ui, sans-serif",
                "headings": {
                    "fontFamily": "Inter, system-ui, sans-serif",
                    "fontWeight": "600",
                    "color": "#f9fafb" # gray-50
                },
                "code": {
                    "fontFamily": "Menlo, Monaco, Consolas, monospace",
                    "color": "#e5e7eb", # gray-200
                    "backgroundColor": "#111827" # gray-900
                }
            },
            "sidebar": {
                "backgroundColor": "#1f2937", # gray-800
                "textColor": "#f3f4f6",       # gray-100
                "arrow": {
                    "color": "#9ca3af"        # gray-400
                },
                "activeAnchor": {
                    "backgroundColor": "#111827", # gray-900
                    "textColor": "#60a5fa"        # blue-400
                }
            },
            "rightPanel": {
                "backgroundColor": "#111827", # gray-900
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
                "backgroundColor": "#030712" # gray-950 (deeper black)
            }
        }

    json_options = json.dumps(options)

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
    <div id="redoc-container"></div>
    <script src="{redoc_js_url}"> </script>
    <script>
        Redoc.init(
            "/openapi.json",
            {json_options},
            document.getElementById("redoc-container")
        );
    </script>
    </body>
    </html>
    """
    return HTMLResponse(html)
