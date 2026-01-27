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
        bg_color = "#0f172a"  # slate-900
        options["theme"] = {
            "colors": {
                "primary": {
                    "main": "#38bdf8"  # sky-400 (brighter blue for dark mode)
                },
                "text": {
                    "primary": "#f8fafc",  # slate-50 (high contrast)
                    "secondary": "#cbd5e1" # slate-300
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
                    "color": "#f1f5f9" # slate-100
                },
                "code": {
                    "fontFamily": "Menlo, Monaco, Consolas, monospace",
                    "color": "#e2e8f0", # slate-200
                    "backgroundColor": "#1e293b" # slate-800
                }
            },
            "sidebar": {
                "backgroundColor": "#1e293b", # slate-800 (slightly lighter than body)
                "textColor": "#f1f5f9",       # slate-100
                "arrow": {
                    "color": "#94a3b8"        # slate-400
                },
                "activeAnchor": {
                    "backgroundColor": "#0f172a", # slate-900
                    "textColor": "#38bdf8"        # sky-400
                }
            },
            "rightPanel": {
                "backgroundColor": "#020617", # slate-950 (darkest for code)
                "textColor": "#f1f5f9",
                "servers": {
                    "overlay": {
                        "backgroundColor": "#1e293b",
                        "textColor": "#f1f5f9"
                    },
                    "url": {
                        "backgroundColor": "#334155"
                    }
                }
            },
            "codeBlock": {
                "backgroundColor": "#020617" # slate-950
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
