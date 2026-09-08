from __future__ import annotations

import hmac
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib import request as urllib_request
from urllib.parse import parse_qs, urlparse

from .assessment_history import AssessmentHistoryStore
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


def env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


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
        history_db: str | Path | None = None,
        allow_live_acp: bool = True,
        proof_publish_url: str | None = None,
        proof_publish_token: str | None = None,
    ) -> None:
        self.memory_db = Path(memory_db)
        self.partner_proof_path = self.memory_db.parent / "latest-partner-proof.json"
        self.history = AssessmentHistoryStore(
            history_db or self.memory_db.parent / "assessment-history.db"
        )
        self.runner = runner
        self.data_source = data_source
        self.acp_client = acp_client
        self.settlement_capture = settlement_capture
        self.acp_config = acp_config or live_acp_configuration()
        self.allow_live_acp = allow_live_acp
        self.proof_publish_url = proof_publish_url
        self.proof_publish_token = proof_publish_token
        self.jobs: dict[str, dict[str, Any]] = {}
        self.lock = threading.Lock()

    def _persist_job_locked(self, api_job_id: str) -> None:
        job = self.jobs[api_job_id]
        job["updatedAt"] = utc_now()
        self.history.upsert(job)

    def submit(self, request: dict[str, Any], *, memory_enabled: bool,
               provider_mode: str = "local", acp_confirmed: bool = False) -> str:
        resolve_objective_intent(JobRequest.from_dict(request))
        if provider_mode == "live_acp" and not self.allow_live_acp:
            raise ValueError("live ACP execution is disabled on this deployment")
        if provider_mode == "live_acp" and not acp_confirmed:
            raise ValueError("live ACP execution requires explicit paid-job confirmation")
        if provider_mode == "live_acp" and not self.acp_config["enabled"]:
            raise ValueError("live ACP execution is not configured")
        api_job_id = new_id("api_job")
        created_at = utc_now()
        with self.lock:
            self.jobs[api_job_id] = {
                "id": api_job_id,
                "createdAt": created_at,
                "updatedAt": created_at,
                "status": "accepted",
                "memoryEnabled": memory_enabled,
                "providerMode": provider_mode,
                "request": request,
                "events": [{"type": "request_accepted", "at": created_at}],
                "result": None,
                "error": None,
            }
            self.history.upsert(self.jobs[api_job_id])
        threading.Thread(
            target=self._run,
            args=(api_job_id, request, memory_enabled, provider_mode, acp_confirmed),
            daemon=True,
        ).start()
        return api_job_id

    def _validate_partner_proof(self, payload: dict[str, Any]) -> None:
        job = payload.get("job")
        proof = payload.get("proof")
        if not isinstance(job, dict) or not isinstance(proof, dict):
            raise ValueError("partner proof requires job and proof objects")
        acp_job_id = job.get("acpJobId")
        if not acp_job_id or str(proof.get("jobId")) != str(acp_job_id):
            raise ValueError("partner proof job IDs do not match")
        if proof.get("chainId") != 8453:
            raise ValueError("partner proof must be for Base mainnet chain 8453")
        for stage in ("funding", "completion"):
            record = proof.get(stage)
            if not isinstance(record, dict) or not record.get("transactionHash"):
                raise ValueError(f"partner proof requires {stage} transaction evidence")

    def _write_partner_proof(self, payload: dict[str, Any]) -> None:
        self._validate_partner_proof(payload)
        self.partner_proof_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.partner_proof_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(self.partner_proof_path)

    def publish_partner_proof(self, payload: dict[str, Any]) -> None:
        self._write_partner_proof(payload)

    def _push_partner_proof(self, payload: dict[str, Any]) -> None:
        if not self.proof_publish_url or not self.proof_publish_token:
            return
        body = json.dumps(payload).encode("utf-8")
        publish_request = urllib_request.Request(
            self.proof_publish_url,
            data=body,
            headers={
                "Authorization": f"Bearer {self.proof_publish_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib_request.urlopen(publish_request, timeout=10) as response:
                if response.status >= 300:
                    raise OSError(f"proof publish returned HTTP {response.status}")
        except Exception as exc:
            print(f"Partner proof publish failed: {exc}")

    def _persist_partner_proof(self, result: dict[str, Any]) -> None:
        if result.get("providerMode") != "live Virtuals ACP risk purchase on Base mainnet":
            return
        jobs = result.get("execution", {}).get("providerJobs", [])
        proofs = result.get("settlementProofs", [])
        for job in reversed(jobs):
            acp_job_id = job.get("acpJobId")
            if not acp_job_id:
                continue
            proof = next(
                (item for item in proofs if str(item.get("jobId")) == str(acp_job_id)),
                None,
            )
            if proof is None:
                continue
            payload = {
                "job": job,
                "proof": proof,
                "capturedAt": utc_now(),
            }
            self._write_partner_proof(payload)
            self._push_partner_proof(payload)
            return

    def latest_partner_proof(self) -> dict[str, Any] | None:
        try:
            value = json.loads(self.partner_proof_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def _run(self, api_job_id: str, request: dict[str, Any], memory_enabled: bool,
             provider_mode: str, acp_confirmed: bool) -> None:
        def progress(event: dict[str, Any]) -> None:
            event.setdefault("at", utc_now())
            with self.lock:
                self.jobs[api_job_id]["events"].append(event)
                self.jobs[api_job_id]["status"] = "executing"
                self._persist_job_locked(api_job_id)

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
            self._persist_partner_proof(result)
            with self.lock:
                self.jobs[api_job_id]["status"] = result["status"]
                self.jobs[api_job_id]["result"] = result
                self._persist_job_locked(api_job_id)
        except Exception as exc:
            with self.lock:
                self.jobs[api_job_id]["status"] = "failed"
                self.jobs[api_job_id]["error"] = str(exc)
                self.jobs[api_job_id]["events"].append({
                    "type": "execution_failed", "at": utc_now(), "error": str(exc),
                })
                self._persist_job_locked(api_job_id)

    def get(self, api_job_id: str) -> dict[str, Any] | None:
        with self.lock:
            value = self.jobs.get(api_job_id)
            if value is not None:
                return json.loads(json.dumps(value))
        return self.history.get(api_job_id)

    def list_history(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.history.list(limit)


def make_handler(service: AssessmentService, dist: Path) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("request body must be a JSON object")
            return payload

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/partner-proof/publish":
                if not service.proof_publish_token:
                    self._json(404, {"error": "not found"})
                    return
                authorization = self.headers.get("Authorization", "")
                expected = f"Bearer {service.proof_publish_token}"
                if not hmac.compare_digest(authorization, expected):
                    self._json(401, {"error": "unauthorized"})
                    return
                try:
                    payload = self._read_json_body()
                    service.publish_partner_proof(payload)
                    self._json(200, {
                        "status": "published",
                        "jobId": payload["job"]["acpJobId"],
                    })
                except (ValueError, TypeError, json.JSONDecodeError) as exc:
                    self._json(400, {"error": str(exc)})
                return
            if parsed.path != "/api/assessments":
                self._json(404, {"error": "not found"})
                return
            try:
                payload = self._read_json_body()
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
                enabled = bool(config["enabled"] and service.allow_live_acp)
                if not service.allow_live_acp:
                    status = "Live ACP is disabled on this deployment"
                else:
                    status = "Live ACP is configured" if config["enabled"] else "Live ACP is not configured"
                self._json(200, {
                    "enabled": enabled,
                    "offering": config["offering"],
                    "network": config["network"],
                    "chainId": config["chainId"],
                    "maxExpectedSpend": config["maxExpectedSpend"],
                    "asset": config["asset"],
                    "status": status,
                })
                return
            if parsed.path == "/api/partner-proof/latest":
                proof = service.latest_partner_proof()
                self._json(200, proof) if proof else self._json(404, {"error": "no live partner proof recorded yet"})
                return
            if parsed.path == "/api/assessments":
                query = parse_qs(parsed.query)
                try:
                    limit = int(query.get("limit", ["50"])[0])
                except ValueError:
                    self._json(400, {"error": "limit must be an integer"})
                    return
                self._json(200, {"assessments": service.list_history(limit)})
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
    history_db = Path(os.environ.get("AMUYE_HISTORY_DB", memory_db.parent / "assessment-history.db"))
    service = AssessmentService(
        memory_db,
        history_db=history_db,
        allow_live_acp=env_flag("AMUYE_ALLOW_LIVE_ACP", True),
        proof_publish_url=os.environ.get("AMUYE_PROOF_PUBLISH_URL"),
        proof_publish_token=os.environ.get("AMUYE_PROOF_PUBLISH_TOKEN"),
    )
    server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(service, dist))
    print(f"Amúyẹ live console: http://localhost:{port}")
    print(f"Assessment history: {history_db}")
    if not service.allow_live_acp:
        state = "disabled on this deployment"
    else:
        state = "enabled with explicit confirmation" if service.acp_config["enabled"] else "not configured"
    print(f"Live ACP risk purchasing is {state}.")
    server.serve_forever()


if __name__ == "__main__":
    main()
