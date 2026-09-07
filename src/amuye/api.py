from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from .domain import JobRequest, new_id, utc_now
from .live import run_live_assessment
from .objective import UnsupportedObjectiveError, resolve_objective_intent


def live_acp_configuration() -> dict[str, Any]:
    required = [
        "ACP_BUYER_WALLET_ADDRESS", "ACP_BUYER_WALLET_ID",
        "ACP_BUYER_SIGNER_PRIVATE_KEY", "ACP_RISK_PROVIDER_ADDRESS",
        "ACP_RISK_OFFERING_NAME",
    ]
    missing = [name for name in required if not os.environ.get(name)]
    return {
        "enabled": not missing,
        "provider": os.environ.get("ACP_RISK_PROVIDER_ADDRESS"),
        "offering": os.environ.get("ACP_RISK_OFFERING_NAME", "riskSynthesis"),
        "network": "Base mainnet",
        "chainId": 8453,
        "maxExpectedSpend": float(os.environ.get("ACP_RISK_MAX_EXPECTED_SPEND", "25")),
        "asset": "USDC",
        "notice": "This creates and funds a real paid Virtuals ACP job.",
        "missingConfiguration": missing,
    }


class AssessmentService:
    def __init__(
        self,
        memory_db: str | Path,
        *,
        runner: Callable[..., dict[str, Any]] = run_live_assessment,
        data_source: Any = None,
        acp_client: Any = None,
        settlement_capture: Any = None,
        acp_config: dict[str, Any] | None = None,
    ) -> None:
        self.memory_db = Path(memory_db)
        self.runner = runner
        self.data_source = data_source
        self.acp_client = acp_client
        self.settlement_capture = settlement_capture
        self.acp_config = acp_config or live_acp_configuration()
        self.jobs: dict[str, dict[str, Any]] = {}
        self.lock = threading.Lock()

    def submit(self, request: dict[str, Any], *, memory_enabled: bool,
               provider_mode: str = "local", acp_confirmed: bool = False) -> str:
        resolve_objective_intent(JobRequest.from_dict(request))
        if provider_mode == "live_acp" and not acp_confirmed:
            raise ValueError("live ACP execution requires explicit paid-job confirmation")
        if provider_mode == "live_acp" and not self.acp_config["enabled"]:
            raise ValueError("live ACP execution is not configured")
        api_job_id = new_id("api_job")
        with self.lock:
            self.jobs[api_job_id] = {
                "id": api_job_id,
                "status": "accepted",
                "memoryEnabled": memory_enabled,
                "providerMode": provider_mode,
                "request": request,
                "events": [{"type": "request_accepted", "at": utc_now()}],
                "result": None,
                "error": None,
            }
        threading.Thread(
            target=self._run,
            args=(api_job_id, request, memory_enabled, provider_mode, acp_confirmed),
            daemon=True,
        ).start()
        return api_job_id

    def _run(self, api_job_id: str, request: dict[str, Any], memory_enabled: bool,
             provider_mode: str, acp_confirmed: bool) -> None:
        def progress(event: dict[str, Any]) -> None:
            event.setdefault("at", utc_now())
            with self.lock:
                self.jobs[api_job_id]["events"].append(event)
                self.jobs[api_job_id]["status"] = "executing"

        try:
            result = self.runner(
                request,
                memory_enabled=memory_enabled,
                memory_db=self.memory_db,
                data_source=self.data_source,
                progress=progress,
                provider_mode=provider_mode,
                acp_confirmed=acp_confirmed,
                acp_client=self.acp_client,
                settlement_capture=self.settlement_capture,
                acp_max_cost=(self.acp_config["maxExpectedSpend"]
                              if provider_mode == "live_acp" else None),
            )
            with self.lock:
                self.jobs[api_job_id]["status"] = result["status"]
                self.jobs[api_job_id]["result"] = result
        except Exception as exc:
            with self.lock:
                self.jobs[api_job_id]["status"] = "failed"
                self.jobs[api_job_id]["error"] = str(exc)
                self.jobs[api_job_id]["events"].append({
                    "type": "execution_failed", "at": utc_now(), "error": str(exc),
                })

    def get(self, api_job_id: str) -> dict[str, Any] | None:
        with self.lock:
            value = self.jobs.get(api_job_id)
            return json.loads(json.dumps(value)) if value is not None else None


def make_handler(service: AssessmentService, dist: Path) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != "/api/assessments":
                self._json(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("request body must be a JSON object")
                JobRequest.from_dict(payload)
                memory = parse_qs(parsed.query).get("memory", ["on"])[0].lower()
                if memory not in {"on", "off"}:
                    raise ValueError("memory query parameter must be on or off")
                query = parse_qs(parsed.query)
                provider_mode = query.get("provider", ["local"])[0].lower()
                if provider_mode not in {"local", "live_acp"}:
                    raise ValueError("provider query parameter must be local or live_acp")
                acp_confirmed = query.get("confirmAcp", ["false"])[0].lower() == "true"
                api_job_id = service.submit(
                    payload,
                    memory_enabled=memory == "on",
                    provider_mode=provider_mode,
                    acp_confirmed=acp_confirmed,
                )
                self._json(202, {
                    "jobId": api_job_id,
                    "status": "accepted",
                    "statusUrl": f"/api/assessments/{api_job_id}",
                    "providerMode": (
                        "live Virtuals ACP risk purchase on Base mainnet"
                        if provider_mode == "live_acp" else "local specialists, no ACP payment"
                    ),
                })
            except UnsupportedObjectiveError as exc:
                self._json(422, {"error": str(exc), **exc.result.to_dict()})
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self._json(400, {"error": str(exc)})

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/acp/config":
                config = service.acp_config
                self._json(200, {
                    "enabled": config["enabled"],
                    "offering": config["offering"],
                    "network": config["network"],
                    "chainId": config["chainId"],
                    "maxExpectedSpend": config["maxExpectedSpend"],
                    "asset": config["asset"],
                    "status": "Live ACP is configured" if config["enabled"] else "Live ACP is not configured",
                })
                return
            if parsed.path.startswith("/api/assessments/"):
                api_job_id = parsed.path.rsplit("/", 1)[-1]
                job = service.get(api_job_id)
                self._json(200, job) if job else self._json(404, {"error": "assessment not found"})
                return
            relative = "index.html" if parsed.path == "/" else parsed.path.lstrip("/")
            target = (dist / relative).resolve()
            try:
                target.relative_to(dist.resolve())
                body = target.read_bytes()
            except (ValueError, OSError):
                self.send_error(404)
                return
            content_type = {
                ".html": "text/html; charset=utf-8",
                ".js": "text/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".json": "application/json; charset=utf-8",
                ".png": "image/png",
            }.get(target.suffix, "application/octet-stream")
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            if os.environ.get("AMUYE_HTTP_LOG") == "1":
                super().log_message(format, *args)

    return Handler


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    dist = root / "dist"
    if not (dist / "index.html").exists():
        raise SystemExit("Frontend is not built. Run npm run build first.")
    port = int(os.environ.get("PORT", "4173"))
    memory_db = Path(os.environ.get("AMUYE_MEMORY_DB", root / "artifacts" / "live" / "sibyl.db"))
    memory_db.parent.mkdir(parents=True, exist_ok=True)
    service = AssessmentService(memory_db)
    server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(service, dist))
    print(f"Amúyẹ live console: http://localhost:{port}")
    state = "enabled with explicit confirmation" if service.acp_config["enabled"] else "not configured"
    print(f"Live ACP risk purchasing is {state}.")
    server.serve_forever()


if __name__ == "__main__":
    main()
