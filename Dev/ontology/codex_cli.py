from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import base64
import tomllib

from .v5 import ROOT, write


class CodexClient:
    """Run one bounded CLI process in the project extraction container per request."""
    def __init__(self):
        if not Path("/.dockerenv").is_file() or os.environ.get("CODEX_HOME") != "/opt/ontology/codex-state":
            raise ValueError("Model calls require the ontology-extraction Docker service and dedicated Codex authentication volume")
        self.identity = snu_identity()

    def chat(self, messages, *, model, request_id, **settings):
        from .v5 import workspace_path
        identity = snu_identity()
        if identity != self.identity or model != "gpt-6-luna":
            raise ValueError("Korean generation requires the unchanged SNU workspace and gpt-6-luna")
        directory = workspace_path(settings.get("audit_directory", ROOT / "Tmp/codex" / request_id))
        if directory.exists():
            raise ValueError("Never automatically retransmit a previous CLI request")
        directory.mkdir(parents=True)
        working = ROOT / "Tmp/codex" / request_id
        working.mkdir(parents=True,exist_ok=True)
        output = directory / "response.json"
        prompt = "\n\n".join(message["content"] for message in messages)
        args = ["codex", "exec", "--ephemeral", "--skip-git-repo-check", "--sandbox", "read-only",
                "--cd", str(working), "--model", model, "--color", "never", "--json",
                "-c", 'approval_policy="never"', "-c", 'web_search="disabled"',
                "-c", 'model_reasoning_effort="medium"',
                "-c", 'model_provider="snu_chatgpt"',
                "-c", 'model_providers.snu_chatgpt={name="SNU ChatGPT",wire_api="responses",requires_openai_auth=true,request_max_retries=0,stream_max_retries=0}',
                "--output-last-message", str(output), "-"]
        if settings.get("output_schema"):
            write(directory / "response.schema.json", settings["output_schema"])
            args[-1:-1] = ["--output-schema",str(directory / "response.schema.json")]
        write(directory / "request.json", {"request_id":request_id, "argv":args, "messages":messages,
              "transport":"docker_codex_cli", "timeout_seconds":240, "automatic_process_retries":0,
              "authentication":identity, "model":model, "reasoning_effort":"medium",
              "output_token_limit":"not_enforced_by_cli"})
        environment = {key:value for key,value in os.environ.items()
                       if key not in {"OPENAI_API_KEY", "OPENAI_BASE_URL", "NOVA_DEV_KEY", "NOVA_API_BASE"}}
        with (directory / "events.jsonl").open("w", encoding="utf-8") as events, (directory / "stderr.log").open("w", encoding="utf-8") as errors:
            result = subprocess.run(args, input=prompt, text=True, stdout=events, stderr=errors, timeout=240, check=False, env=environment)
        if result.returncode != 0 or not output.is_file():
            raise RuntimeError("Codex process failed; inspect the request-specific audit and do not retry automatically")
        content = output.read_text(encoding="utf-8")
        json.loads(content)
        return {"choices":[{"finish_reason":"stop", "message":{"content":content}}],
                "transport":"docker_codex_cli", "audit_directory":str(directory.relative_to(ROOT))}


def snu_identity():
    home = Path("/opt/ontology/codex-state")
    settings = tomllib.loads((home / "config.toml").read_text())
    auth = json.loads((home / "auth.json").read_text())
    tokens = auth.get("tokens", {})
    token = tokens.get("id_token", "")
    try:
        claims = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
    except (ValueError, IndexError) as error:
        raise ValueError("SNU ChatGPT authentication cannot be verified") from error
    account = claims.get("https://api.openai.com/auth", {})
    pin = settings.get("forced_chatgpt_workspace_id")
    if (auth.get("auth_mode") != "chatgpt" or settings.get("forced_login_method") != "chatgpt"
            or not pin or tokens.get("account_id") != pin or account.get("chatgpt_account_id") != pin
            or not claims.get("email", "").endswith("@snu.ac.kr") or account.get("chatgpt_plan_type") != "education"):
        raise ValueError("Use the pinned SNU education workspace; API-key and other workspaces are forbidden")
    return {"mode":"chatgpt", "workspace_id":pin, "email_domain":"snu.ac.kr", "plan":"education"}
