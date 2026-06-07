from collections.abc import Iterable
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, Response


DARK_SWAGGER_CSS = """
      :root {
        color-scheme: dark;
        --sb-bg: #101417;
        --sb-panel: #171d20;
        --sb-panel-2: #20272b;
        --sb-border: #3a454b;
        --sb-text: #f3f7f5;
        --sb-muted: #a8b5b0;
        --sb-accent: #32d296;
        --sb-blue: #62a8ff;
      }
      body { margin: 0; background: var(--sb-bg); }
      .swagger-ui { color: var(--sb-text); font-family: Inter, Segoe UI, Arial, sans-serif; }
      .swagger-ui .topbar { display: none; }
      .swagger-ui .wrapper, .swagger-ui .information-container, .swagger-ui .scheme-container {
        background: var(--sb-bg);
        max-width: none;
        padding-left: 28px;
        padding-right: 28px;
      }
      .swagger-ui .info { margin: 48px 0 36px; }
      .swagger-ui .info .title, .swagger-ui .opblock-tag, .swagger-ui h1, .swagger-ui h2,
      .swagger-ui h3, .swagger-ui h4, .swagger-ui h5, .swagger-ui p, .swagger-ui label,
      .swagger-ui table thead tr td, .swagger-ui table thead tr th,
      .swagger-ui .parameter__name, .swagger-ui .parameter__type,
      .swagger-ui .response-col_status, .swagger-ui .response-col_description,
      .swagger-ui .tab li, .swagger-ui .model-title, .swagger-ui .model,
      .swagger-ui .prop-format, .swagger-ui .servers-title {
        color: var(--sb-text) !important;
      }
      .swagger-ui .info .title small, .swagger-ui .info .base-url, .swagger-ui .markdown p,
      .swagger-ui .opblock-tag small, .swagger-ui .parameter__deprecated,
      .swagger-ui .prop-type { color: var(--sb-muted) !important; }
      .swagger-ui .scheme-container {
        background: var(--sb-panel);
        border: 1px solid var(--sb-border);
        box-shadow: none;
        margin: 0 0 34px;
        padding-top: 24px;
        padding-bottom: 24px;
      }
      .swagger-ui .opblock {
        background: var(--sb-panel);
        border-color: var(--sb-border);
        box-shadow: none;
      }
      .swagger-ui .opblock .opblock-summary {
        border-color: rgba(255,255,255,.08);
      }
      .swagger-ui .opblock .opblock-section-header,
      .swagger-ui .responses-inner, .swagger-ui .opblock-description-wrapper,
      .swagger-ui .parameters-container, .swagger-ui .model-box,
      .swagger-ui section.models {
        background: var(--sb-panel);
        border-color: var(--sb-border);
      }
      .swagger-ui input, .swagger-ui select, .swagger-ui textarea {
        background: #0f1417 !important;
        border-color: #c8d2d8 !important;
        color: var(--sb-text) !important;
      }
      .swagger-ui .btn {
        background: transparent;
        border-color: var(--sb-accent);
        color: var(--sb-accent);
      }
      .swagger-ui .auth-wrapper .authorize {
        border-color: var(--sb-accent);
        color: var(--sb-accent);
      }
      .swagger-ui a, .swagger-ui .info a { color: var(--sb-blue) !important; }
      .swagger-ui .filter .operation-filter-input {
        background: #11171a !important;
        border: 2px solid #c8d2d8 !important;
        color: var(--sb-text) !important;
      }
      .swagger-ui .dialog-ux .modal-ux {
        background: var(--sb-panel);
        border-color: var(--sb-border);
      }
      .swagger-ui .dialog-ux .modal-ux-header,
      .swagger-ui .dialog-ux .modal-ux-content {
        background: var(--sb-panel);
        color: var(--sb-text);
      }
"""


def render_swagger_ui_html(service_name: str, initializer_path: str) -> str:
    return f"""<!doctype html>
<html lang="es">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{service_name} API Docs</title>
    <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css" />
    <style>
{DARK_SWAGGER_CSS}
    </style>
  </head>
  <body>
    <div id="swagger-ui"></div>
    <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
    <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-standalone-preset.js"></script>
    <script src="{initializer_path}"></script>
  </body>
</html>"""


def render_swagger_ui_initializer(openapi_url: str) -> str:
    return f"""
window.addEventListener("load", () => {{
  window.ui = SwaggerUIBundle({{
    url: {openapi_url!r},
    dom_id: "#swagger-ui",
    deepLinking: true,
    displayRequestDuration: true,
    filter: true,
    persistAuthorization: true,
    presets: [
      SwaggerUIBundle.presets.apis,
      SwaggerUIStandalonePreset
    ],
    layout: "StandaloneLayout"
  }});
}});
"""


def register_swagger_docs(
    app: FastAPI,
    *,
    service_name: str,
    docs_url: str,
    openapi_url: str,
) -> None:
    initializer_url = f"{docs_url.rstrip('/')}/swagger-ui.js"

    @app.get(docs_url, include_in_schema=False)
    async def swagger_docs() -> HTMLResponse:
        return HTMLResponse(render_swagger_ui_html(service_name, initializer_url))

    @app.get(initializer_url, include_in_schema=False)
    async def swagger_initializer() -> Response:
        return Response(
            render_swagger_ui_initializer(openapi_url),
            media_type="application/javascript",
        )


def configure_openapi(
    app: FastAPI,
    *,
    title: str,
    version: str,
    description: str,
    public_paths: Iterable[str] = (),
) -> None:
    """Install StreamButed OpenAPI defaults without changing runtime auth."""
    public_path_set = set(public_paths)

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema

        schema = get_openapi(
            title=title,
            version=version,
            description=description,
            routes=app.routes,
        )
        schema["servers"] = [
            {
                "url": "/",
                "description": "Gateway o host actual",
            }
        ]

        components = schema.setdefault("components", {})
        security_schemes = components.setdefault("securitySchemes", {})
        security_schemes["BearerAuth"] = {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Access token emitido por identity-service.",
        }

        for path, methods in schema.get("paths", {}).items():
            if path in public_path_set or path.endswith("/health"):
                continue

            for operation in methods.values():
                if isinstance(operation, dict):
                    operation.setdefault("security", [{"BearerAuth": []}])

        app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = custom_openapi
