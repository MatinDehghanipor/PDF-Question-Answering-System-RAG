"""Pydantic request/response schemas for the PDF QA system.

Each file mirrors a corresponding ORM model under ``app/models/`` and defines
the request/response shapes exposed by the API.  These schemas are used by
the stub routes in Phase 0 so that Swagger/OpenAPI accurately reflects the
final API surface.
"""