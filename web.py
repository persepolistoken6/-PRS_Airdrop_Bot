"""Standalone HTTPS web portal. No Telegram Mini App SDK and no polling here."""
import os
import ipaddress
import secrets
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, Response, g, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from portal.demo import seed_demo
from portal.service import PortalError, build_service, digest
from portal.settings import CAMPAIGN_TIMEZONE, Settings

def create_app(settings=None, service=None):
    settings = settings or Settings.from_env()
    if not settings.demo and (not settings.base_url or not settings.bot_token):
        raise RuntimeError("WEB_BASE_URL (HTTPS) and BOT_TOKEN are required for the production web service")
    if not settings.demo and not settings.enabled:
        raise RuntimeError("Enable PORTAL_ENABLED=1 only after the MongoDB readiness check succeeds")
    service = service or build_service(settings)
    cookie_name = "prs_demo_session" if settings.demo else "__Host-prs_portal_session"
    app = Flask(__name__)
    app.config.update(MAX_CONTENT_LENGTH=24 * 1024, PROPAGATE_EXCEPTIONS=False)
    app.extensions["portal"] = service
    asset_versions = {name: digest((Path(app.static_folder) / name).read_text(encoding="utf-8"))[:12]
                      for name in ("app.js", "app.css")}
    if settings.demo and not service.store.all("users"):
        seed_demo(service)

    def body():
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            raise PortalError("invalid_request")
        return value

    def protected(admin=False):
        def decorate(function):
            @wraps(function)
            def wrapped(*args, **kwargs):
                session = service.session(request.cookies.get(cookie_name, ""))
                g.user_id = session["user_id"]
                if admin:
                    service.require_admin(g.user_id)
                if request.method not in ("GET", "HEAD", "OPTIONS"):
                    csrf = request.headers.get("X-CSRF-Token", "")
                    if not secrets.compare_digest(csrf, session["csrf"]):
                        raise PortalError("csrf_failed", 403)
                    service.limit(f"write:{g.user_id}", 45, 60)
                else:
                    service.limit(f"read:{g.user_id}", 120, 60)
                g.portal_session = session
                return function(*args, **kwargs)
            return wrapped
        return decorate

    @app.before_request
    def check_origin():
        if request.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("Origin", "")
            allowed = settings.base_url or request.host_url.rstrip("/")
            if origin != allowed:
                raise PortalError("origin_failed", 403)

    @app.after_request
    def security_headers(response):
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if not settings.demo:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        if not request.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(PortalError)
    def portal_error(error):
        return jsonify(error=error.code, **error.details), error.status

    @app.errorhandler(Exception)
    def unexpected(error):
        if isinstance(error, HTTPException):
            return jsonify(error="not_found" if error.code == 404 else "invalid_request"), error.code
        app.logger.error("Portal operation failed: %s", type(error).__name__)
        return jsonify(error="service_unavailable"), 503

    @app.get("/")
    @app.get("/login")
    def index():
        return render_template("index.html", asset_versions=asset_versions)

    @app.get("/healthz")
    def health():
        return jsonify(status="ok")

    @app.get("/readyz")
    def ready():
        if not service.store.ready():
            return jsonify(status="unavailable", error="replica_set_required"), 503
        return jsonify(status="ready")

    @app.get("/api/bootstrap")
    def bootstrap():
        return jsonify(demo=settings.demo, bot_url=f"https://t.me/{settings.bot_username}?start=portal",
                       channel_url=f"https://t.me/{settings.channel.lstrip('@')}", timezone=CAMPAIGN_TIMEZONE,
                       server_time=service.now(), phase=2)

    def finish_login(result):
        response = jsonify(csrf=result["csrf"])
        response.set_cookie(cookie_name, result["token"], httponly=True, secure=not settings.demo,
                            samesite="Lax", max_age=settings.session_ttl, path="/")
        return response

    @app.post("/api/auth/exchange")
    def exchange():
        # No raw Telegram user IDs are accepted as authentication.
        address = request.remote_addr or "unknown"
        if os.getenv("RAILWAY_ENVIRONMENT_ID") and not settings.demo:
            # Railway's public HTTP edge supplies X-Real-IP. Never use arbitrary
            # X-Forwarded-For chains or forwarded headers on other deployments.
            try:
                address = str(ipaddress.ip_address(request.headers.get("X-Real-IP", "")))
            except ValueError:
                pass
        service.limit("exchange:" + digest(address), 120, 300)
        return finish_login(service.exchange_login(body().get("token")))

    @app.post("/api/auth/demo")
    def demo_login():
        if not settings.demo:
            raise PortalError("not_found", 404)
        role = body().get("role", "user")
        if role not in ("user", "admin"):
            raise PortalError("invalid_request")
        uid = settings.admins[0] if role == "admin" else 1001
        service.logout(request.cookies.get(cookie_name))
        token = service.new_login_token(uid)
        return finish_login(service.exchange_login(token))

    @app.get("/api/session")
    @protected()
    def current_session():
        return jsonify(csrf=g.portal_session["csrf"], profile=service.profile(g.user_id))

    @app.post("/api/auth/logout")
    @protected()
    def logout():
        service.logout(request.cookies.get(cookie_name))
        response = jsonify(ok=True)
        response.delete_cookie(cookie_name, path="/", secure=not settings.demo, httponly=True, samesite="Lax")
        return response

    @app.get("/api/missions")
    @protected()
    def missions():
        return jsonify(missions=service.missions(g.user_id))

    @app.post("/api/missions/<mission_id>/submit")
    @protected()
    def submit(mission_id):
        return jsonify(service.submit_mission(g.user_id, mission_id, body()))

    @app.post("/api/daily")
    @protected()
    def daily():
        return jsonify(service.claim_daily(g.user_id))

    @app.post("/api/mining/start")
    @protected()
    def start_mining():
        return jsonify(service.start_mining(g.user_id))

    @app.post("/api/mining/claim")
    @protected()
    def claim_mining():
        return jsonify(service.claim_mining(g.user_id, body().get("cycle_id")))

    @app.get("/api/leaderboard")
    @protected()
    def leaderboard():
        return jsonify(rows=service.public_leaderboard(g.user_id))

    @app.post("/api/wallet")
    @protected()
    def wallet():
        service.update_wallet(g.user_id, body().get("wallet"))
        return jsonify(ok=True)

    @app.post("/api/social-links")
    @protected()
    def social_links():
        data = body()
        service.update_social_links(g.user_id, data.get("instagram", ""), data.get("twitter", ""))
        return jsonify(ok=True)

    @app.post("/api/payments")
    @protected()
    def payment():
        return jsonify(payment=service.request_payment(g.user_id, body().get("amount") if request.is_json else None))

    @app.post("/api/tickets")
    @protected()
    def ticket():
        return jsonify(ticket=service.ticket(g.user_id, body().get("message")))

    @app.get("/api/admin/overview")
    @protected(admin=True)
    def admin_overview():
        return jsonify(service.admin_overview(g.user_id))

    @app.post("/api/admin/telegram/check")
    @protected(admin=True)
    def check_telegram():
        service.limit(f"telegram-check:{g.user_id}", 6, 60)
        return jsonify(service.admin_telegram_status(g.user_id))

    @app.post("/api/admin/controls")
    @protected(admin=True)
    def admin_controls():
        return jsonify(controls=service.admin_controls(g.user_id, body()))

    @app.get("/api/admin/users")
    @protected(admin=True)
    def admin_users():
        try:
            page = int(request.args.get("page", "1"))
        except ValueError:
            raise PortalError("invalid_request") from None
        return jsonify(service.admin_users(g.user_id, request.args.get("q", ""), page, eligible_only=request.args.get("eligible") == "1"))

    @app.get("/api/admin/users/<int:user_id>")
    @protected(admin=True)
    def admin_user_detail(user_id):
        return jsonify(service.admin_user_detail(g.user_id, user_id))

    @app.post("/api/admin/users/<int:user_id>/action")
    @protected(admin=True)
    def admin_user_action(user_id):
        return jsonify(service.admin_user_action(g.user_id, user_id, body()))

    @app.post("/api/admin/users/<int:user_id>/wallet")
    @protected(admin=True)
    def admin_wallet(user_id):
        service.admin_update_wallet(g.user_id, user_id, body().get("wallet"))
        return jsonify(ok=True)

    @app.get("/api/admin/export/<kind>")
    @protected(admin=True)
    def admin_export(kind):
        result = service.export_report(g.user_id, kind)
        return Response(result, content_type="text/csv; charset=utf-8", headers={
            "Content-Disposition": f'attachment; filename="prs-{kind}.csv"'})

    @app.get("/api/admin/export-xlsx/<kind>")
    @protected(admin=True)
    def admin_export_xlsx(kind):
        result = service.export_xlsx(g.user_id, kind)
        return Response(result, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={
            "Content-Disposition": f'attachment; filename="prs-{kind}.xlsx"'})

    @app.post("/api/admin/missions")
    @protected(admin=True)
    def create_mission():
        return jsonify(mission=service.create_mission(g.user_id, body())), 201

    @app.post("/api/admin/missions/<mission_id>/active")
    @protected(admin=True)
    def active(mission_id):
        service.set_mission_active(g.user_id, mission_id, body().get("active"))
        return jsonify(ok=True)

    @app.post("/api/admin/missions/<mission_id>/archive")
    @protected(admin=True)
    def archive(mission_id):
        service.archive_mission(g.user_id, mission_id, body().get("archived"))
        return jsonify(ok=True)

    @app.post("/api/admin/submissions/<submission_id>/review")
    @protected(admin=True)
    def review(submission_id):
        data = body()
        service.review_submission(g.user_id, submission_id, data.get("approve"), data.get("reason", ""))
        return jsonify(ok=True)

    @app.post("/api/admin/payments/<payment_id>/review")
    @protected(admin=True)
    def review_payment(payment_id):
        data = body()
        service.review_payment(g.user_id, payment_id, data.get("approve"), data.get("tx_hash", ""), data.get("reason", ""))
        return jsonify(ok=True)

    @app.post("/api/admin/payments/payout")
    @protected(admin=True)
    def payout_payments():
        return jsonify(service.payout_payments(g.user_id, body().get("payment_ids")))

    @app.post("/api/admin/tickets/<ticket_id>/reply")
    @protected(admin=True)
    def reply_ticket(ticket_id):
        service.reply_ticket(g.user_id, ticket_id, body().get("reply"))
        return jsonify(ok=True)

    return app


# The factory keeps imports testable. Gunicorn: gunicorn 'web:create_app()'.
if __name__ == "__main__":
    app = create_app()
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "8000")), debug=False)
