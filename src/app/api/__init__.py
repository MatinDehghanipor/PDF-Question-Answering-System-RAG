"""HTTP API layer for the PDF QA system backend.

Contains the FastAPI routers that expose every endpoint of the finished
system.  Phase 0 implements each endpoint as a clearly-marked stub; later
phases replace the stub bodies with real logic while keeping the route
shapes stable so the client UI can be built against the final API surface.
"""