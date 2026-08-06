"""
scout/api/app.py — The FastAPI application factory.

This file does three things:
  1. Creates the FastAPI app with metadata (title, version, docs URL)
  2. Defines the lifespan — startup and shutdown hooks
  3. Registers all routers (health, scans, graph)

Why a lifespan instead of @app.on_event("startup")?
  The lifespan context manager is the modern FastAPI pattern (v0.93+).
  It runs startup code, then yields (serving requests happens here),
  then runs shutdown code. The on_event decorators are deprecated.

  startup  → initialize Neo4j schema, log config
  shutdown → close any shared resources

How to run:
  poetry run uvicorn scout.api.app:app --reload --port 8000

  --reload means uvicorn watches your files and restarts on every save.
  Critical for development — no need to restart manually.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from neo4j import GraphDatabase

from scout.api.middleware.audit_log import AuditLogMiddleware
from scout.api.middleware.rate_limit import RateLimitMiddleware
from scout.api.middleware.security import SecurityHeadersMiddleware
from scout.api.routes import access, admin, auth, benefits, board_report, communications, compliance, connectors, copilot, dashboard, ddq, design_session, digest, graph, health, health_score, insights, it_access, knowledge_base, mfa, mission_control, notifications, payroll_agent, payment_status, portal_access, portfolio, scans, schedule, sso, support_triage, users, vendor_onboarding, webhooks
from scout.config import settings
from scout.db.database import init_db
from scout.graph.schema import init_schema

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup and shutdown logic.

    Everything BEFORE yield runs at startup.
    Everything AFTER yield runs at shutdown.

    The `yield` is where the app serves requests.
    """
    # ── Startup ──────────────────────────────────────────────
    logger.info(f"Scout API starting — environment: {settings.environment}")
    logger.info(f"Mock connectors: {settings.use_mock_connectors}")
    logger.info(f"Neo4j: {settings.neo4j_uri}")

    # Initialize SQLite schema for user/auth data (Sprint 15).
    # This is idempotent — safe to run on every restart.
    try:
        init_db()
        logger.info("SQLite schema initialized")
    except Exception as exc:
        logger.warning(f"Could not initialize SQLite schema: {exc}")

    # Start insight scheduler daemon thread (Sprint 78).
    # Checks InsightSchedule every 60s and fires due runs.
    try:
        from scout.scheduler import start_scheduler
        start_scheduler(tick_seconds=60)
    except Exception as exc:
        logger.warning(f"Could not start insight scheduler: {exc}")

    # Ensure Neo4j constraints and indexes exist before serving traffic.
    # This is idempotent — safe to run on every restart.
    try:
        driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        init_schema(driver)
        driver.close()
        logger.info("Neo4j schema initialized")
    except Exception as exc:
        # Don't crash on startup if Neo4j is temporarily unreachable.
        # The health endpoint will report it as degraded.
        logger.warning(f"Could not initialize Neo4j schema: {exc}")

    yield  # ← App serves requests between startup and shutdown

    # ── Shutdown ─────────────────────────────────────────────
    logger.info("Scout API shutting down")


# ── Application factory ────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.

    Separating this into a factory function (vs. module-level code) makes
    it easy to create test instances with different settings:
        app = create_app()
        client = TestClient(app)
    """
    app = FastAPI(
        title="Scout API",
        description=(
            "The Scout digital twin REST API. "
            "Trigger ingestion scans, query the org graph, and monitor vendor spend."
        ),
        version="0.2.0",
        lifespan=lifespan,
        # Swagger UI at /docs, ReDoc at /redoc
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ── CORS middleware ────────────────────────────────────────
    # Cross-Origin Resource Sharing: lets a browser-based frontend
    # (on a different domain) call this API. In production, replace
    # allow_origins=["*"] with your specific frontend domain.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Tighten this in production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Sprint 13 security middleware ──────────────────────────
    # Starlette middleware is LIFO: the last one added wraps everything
    # and therefore runs first on every incoming request.
    #
    # Desired execution order (request → response):
    #   SecurityHeaders → AuditLog → RateLimit → CORS → routes
    #
    # So we add them in reverse order:
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(AuditLogMiddleware, log_file=settings.audit_log_file)
    app.add_middleware(SecurityHeadersMiddleware)

    # ── Register routers ───────────────────────────────────────
    # Each router brings a set of related endpoints.
    # The prefix is applied to all routes in that router.
    app.include_router(health.router)           # GET /health
    app.include_router(scans.router)            # POST /scans, GET /scans/{id}
    app.include_router(graph.router)            # GET /graph/*
    app.include_router(insights.router)         # GET /insights
    app.include_router(webhooks.router)         # POST /webhooks/* (Sprint 12)
    app.include_router(auth.router)             # GET /auth/* (Sprint 13)
    app.include_router(users.router)            # POST/GET /users/* (Sprint 15)
    app.include_router(admin.router)            # GET/PUT/DELETE /admin/* (Sprint 21)
    app.include_router(dashboard.router)       # GET /dashboard/* (Sprint 28)
    app.include_router(mfa.router)             # POST/GET /mfa/* (MFA)
    app.include_router(sso.router)             # GET/POST /auth/sso/* (S58: enterprise SSO)
    app.include_router(sso.public_router)     # GET /sso/domain-check (S74: public domain lookup)
    app.include_router(portfolio.router)       # GET /portfolio/* (S56: fund view)
    app.include_router(ddq.router)             # POST/GET /ddq/* (S60: DDQ Agent)
    app.include_router(payroll_agent.router)  # POST/GET /agents/payroll/* (S61: Payroll Agent)
    app.include_router(mission_control.router)  # GET/POST /mission-control/* (Sprint 62: Mission Control)
    app.include_router(portal_access.router)  # POST/GET /agents/portal-access/* (Sprint 63: Portal Access Agent)
    app.include_router(support_triage.router)  # POST/GET /agents/support-triage/* (Sprint 64: Support Triage Agent)
    app.include_router(payment_status.router)  # POST/GET /payment-status/* (Sprint 65: Payment Status Agent)
    app.include_router(benefits.router)         # POST/GET /benefits/* (Sprint 66: Benefits Agent)
    app.include_router(vendor_onboarding.router)  # GET/POST /vendor-onboarding/* (Sprint 67: Vendor Onboarding Agent)
    app.include_router(it_access.router)           # POST/GET /it-access/* (Sprint 68: IT Access Agent)
    app.include_router(compliance.router)          # POST/GET /compliance/* (Sprint 69: Compliance Response Agent)
    app.include_router(board_report.router)        # POST/GET /board-report/* (Sprint 70: Board Report Agent)
    app.include_router(design_session.router)      # POST/GET /design-session/* (Sprint 72: Design Session Mode)
    app.include_router(communications.router)      # GET /communications/* (Sprint 73: Communication Analysis)
    app.include_router(knowledge_base.router)      # GET/POST/DELETE /knowledge-base/* (Sprint 75: KB Manager)
    app.include_router(notifications.router)       # GET/POST /notifications/* (Sprint 76: Notification Center)
    app.include_router(health_score.router)        # GET /health-score/* (Sprint 77: Company Health Score)
    app.include_router(schedule.router)            # GET/POST/DELETE /schedule/* (Sprint 78: Insight Scheduling)
    app.include_router(copilot.router)             # POST /copilot/ask (Sprint 79: Miragent Copilot)
    app.include_router(access.router)              # GET/POST/DELETE /access/* (Sprint 80: Multi-tenant access)
    app.include_router(digest.router)              # GET/POST/DELETE /digest/* (Sprint 81: Email digest)
    app.include_router(connectors.router)          # GET/POST /connectors/* (Sprint 83: Real connectors)

    return app


# Module-level app instance — what uvicorn imports
app = create_app()
