import argparse
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
import json
import keyword
import re
import shlex
import sys
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
import uuid

from aiohttp import web
import httpx
import pyperclip
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Header, Input, Static, TabbedContent, TabPane


@dataclass
class ReplayResult:
    status_code: int
    elapsed_ms: float
    response_body: str
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))
    error: Optional[str] = None


@dataclass
class CapturedRequest:
    method: str
    path: str
    headers: Dict[str, str]
    query_params: Dict[str, str]
    raw_body: str
    client_ip: str = "127.0.0.1"
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S.%f")[:-3])
    last_replay: Optional[ReplayResult] = None

    @property
    def parsed_json(self) -> Optional[Any]:
        if not self.raw_body:
            return None
        try:
            return json.loads(self.raw_body)
        except Exception:
            return None

    @property
    def formatted_body(self) -> str:
        parsed = self.parsed_json
        if parsed is not None:
            return json.dumps(parsed, indent=2, ensure_ascii=False)
        return self.raw_body or ""

    @property
    def size_bytes(self) -> int:
        return len(self.raw_body.encode("utf-8")) if self.raw_body else 0

    @property
    def source_badge(self) -> str:
        lower_headers = {k.lower(): v for k, v in self.headers.items()}
        if "stripe-signature" in lower_headers:
            return "Stripe"
        if "x-github-event" in lower_headers:
            return f"GitHub:{lower_headers['x-github-event']}"
        if "x-telegram-bot-api-secret-token" in lower_headers or "telegram" in self.path.lower():
            return "Telegram"
        if "svix-id" in lower_headers:
            return "Svix"
        return "HTTP"

    def to_curl(self, base_url: str = "http://localhost:8000") -> str:
        target = f"{base_url.rstrip('/')}{self.path}"
        if self.query_params:
            qs = "&".join(f"{k}={v}" for k, v in self.query_params.items())
            target = f"{target}?{qs}"
        parts = ["curl", "-X", self.method, shlex.quote(target)]
        excluded = {"host", "content-length", "connection", "accept-encoding"}
        for k, v in self.headers.items():
            if k.lower() not in excluded:
                parts.extend(["-H", shlex.quote(f"{k}: {v}")])
        if self.raw_body:
            parts.extend(["-d", shlex.quote(self.raw_body)])
        return " \\\n  ".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "method": self.method,
            "path": self.path,
            "headers": self.headers,
            "query_params": self.query_params,
            "raw_body": self.raw_body,
            "client_ip": self.client_ip,
        }


def _to_pascal_case(name: str) -> str:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    cleaned = re.sub(r"[^a-zA-Z0-9]+", " ", spaced).strip()
    if not cleaned:
        return "GeneratedModel"
    pascal = "".join(word.capitalize() for word in cleaned.split())
    if pascal[0].isdigit():
        pascal = f"Model{pascal}"
    return pascal


def _sanitize_field_name(key: str) -> Tuple[str, bool]:
    cleaned = re.sub(r"[^a-zA-Z0-9_]", "_", key)
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"field_{cleaned}"
    if keyword.iskeyword(cleaned) or cleaned in {"model_config", "model_fields"}:
        return f"{cleaned}_", True
    return cleaned, cleaned != key


def infer_pydantic_schema(payload: Any, root_name: str = "WebhookPayload") -> str:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            return "from pydantic import BaseModel\n\n\nclass RawPayload(BaseModel):\n    raw_body: str\n"

    models: List[str] = []
    visited_names: Dict[str, int] = {}

    def unique_model_name(base: str) -> str:
        pascal = _to_pascal_case(base)
        count = visited_names.get(pascal, 0)
        visited_names[pascal] = count + 1
        return pascal if count == 0 else f"{pascal}{count + 1}"

    def resolve_type(value: Any, field_hint: str) -> str:
        if value is None:
            return "Optional[Any]"
        if isinstance(value, bool):
            return "bool"
        if isinstance(value, int):
            return "int"
        if isinstance(value, float):
            return "float"
        if isinstance(value, str):
            return "str"
        if isinstance(value, list):
            if not value:
                return "List[Any]"
            first_non_null = next((item for item in value if item is not None), value[0])
            inner_type = resolve_type(first_non_null, f"{field_hint}Item")
            return f"List[{inner_type}]"
        if isinstance(value, dict):
            nested_name = unique_model_name(field_hint)
            build_model(value, nested_name)
            return nested_name
        return "Any"

    def build_model(obj: Dict[str, Any], model_name: str) -> None:
        lines = [f"class {model_name}(BaseModel):"]
        if not obj:
            lines.append("    pass")
            models.append("\n".join(lines))
            return

        for raw_key, val in obj.items():
            safe_name, needs_alias = _sanitize_field_name(str(raw_key))
            type_annotation = resolve_type(val, str(raw_key))
            if val is None:
                if needs_alias:
                    lines.append(f'    {safe_name}: {type_annotation} = Field(default=None, alias="{raw_key}")')
                else:
                    lines.append(f"    {safe_name}: {type_annotation} = None")
            else:
                if needs_alias:
                    lines.append(f'    {safe_name}: {type_annotation} = Field(alias="{raw_key}")')
                else:
                    lines.append(f"    {safe_name}: {type_annotation}")
        models.append("\n".join(lines))

    if isinstance(payload, dict):
        top_name = unique_model_name(root_name)
        build_model(payload, top_name)
    elif isinstance(payload, list):
        top_name = unique_model_name(root_name)
        sample = payload[0] if payload and isinstance(payload[0], dict) else {"items": payload}
        if isinstance(sample, dict):
            build_model(sample, top_name)
    else:
        return "from pydantic import BaseModel\n\n\nclass ScalarPayload(BaseModel):\n    value: str\n"

    header = "from typing import Any, List, Optional\nfrom pydantic import BaseModel, Field\n\n\n"
    return header + "\n\n\n".join(models) + "\n"


async def replay_request(req: CapturedRequest, target_base_url: str, timeout: float = 10.0) -> ReplayResult:
    url = f"{target_base_url.rstrip('/')}{req.path}"
    excluded_headers = {"host", "content-length", "connection", "accept-encoding"}
    headers = {k: v for k, v in req.headers.items() if k.lower() not in excluded_headers}
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.request(
                method=req.method,
                url=url,
                params=req.query_params,
                headers=headers,
                content=req.raw_body.encode("utf-8") if req.raw_body else b"",
            )
        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
        result = ReplayResult(
            status_code=response.status_code,
            elapsed_ms=elapsed_ms,
            response_body=response.text[:4000],
        )
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
        result = ReplayResult(
            status_code=0,
            elapsed_ms=elapsed_ms,
            response_body="",
            error=str(exc),
        )
    req.last_replay = result
    return result


def build_demo_requests() -> list[CapturedRequest]:
    return [
        CapturedRequest(
            method="POST",
            path="/webhooks/stripe",
            headers={
                "Content-Type": "application/json",
                "Stripe-Signature": "t=1729412400,v1=6a8f9b2c4d1e",
                "User-Agent": "Stripe/1.0 (+https://stripe.com/docs/webhooks)",
            },
            query_params={"env": "staging"},
            raw_body='{"id":"evt_3Q9xLm2eZvKYlo2C","object":"event","api_version":"2024-06-20","created":1729412400,"type":"payment_intent.succeeded","data":{"object":{"id":"pi_3Q9xLm2eZvKYlo2C","amount":4900,"currency":"usd","customer":"cus_R1x9KpL2mN","status":"succeeded","metadata":{"plan":"pro_annual","user_id":8421}}}}',
            client_ip="54.187.205.235",
        ),
        CapturedRequest(
            method="POST",
            path="/webhooks/github",
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "push",
                "X-GitHub-Delivery": "9a7d8c20-8e4f-11ef-9b12-0242ac120002",
                "User-Agent": "GitHub-Hookshot/a1b2c3d",
            },
            query_params={},
            raw_body='{"ref":"refs/heads/main","repository":{"id":91827364,"name":"hookpulse","full_name":"dev/hookpulse","stargazers_count":1420,"private":false},"pusher":{"name":"alexdev","email":"alex@example.com"},"head_commit":{"id":"8f4e2a1c9b","message":"feat: add instant Pydantic v2 schema generator","timestamp":"2026-10-20T08:30:00Z"}}',
            client_ip="140.82.115.68",
        ),
        CapturedRequest(
            method="POST",
            path="/webhooks/telegram",
            headers={
                "Content-Type": "application/json",
                "X-Telegram-Bot-Api-Secret-Token": "tg_live_98f2a1c4b",
            },
            query_params={},
            raw_body='{"update_id":73918241,"message":{"message_id":412,"from":{"id":4918273,"is_bot":false,"first_name":"Nikita","username":"nikita_py"},"chat":{"id":4918273,"type":"private"},"date":1729412490,"text":"/deploy production"}}',
            client_ip="149.154.167.220",
        ),
    ]


class WebhookCaptureServer:
    def __init__(
        self,
        host: str,
        port: int,
        on_request: Callable[[CapturedRequest], Awaitable[None]],
        forward_target: Optional[str] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.on_request = on_request
        self.forward_target = forward_target
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None

    async def _handle_all(self, request: web.Request) -> web.Response:
        raw_bytes = await request.read()
        raw_text = raw_bytes.decode("utf-8", errors="replace")
        captured = CapturedRequest(
            method=request.method,
            path=request.path,
            headers=dict(request.headers),
            query_params=dict(request.query),
            raw_body=raw_text,
            client_ip=request.remote or "127.0.0.1",
        )
        if self.forward_target:
            asyncio.create_task(self._forward_and_notify(captured))
        else:
            await self.on_request(captured)
        return web.json_response(
            {
                "ok": True,
                "captured_id": captured.id,
                "source": captured.source_badge,
            },
            status=200,
        )

    async def _forward_and_notify(self, captured: CapturedRequest) -> None:
        if self.forward_target:
            await replay_request(captured, self.forward_target)
        await self.on_request(captured)

    async def start(self) -> None:
        app = web.Application(client_max_size=10 * 1024 * 1024)
        app.router.add_route("*", "/{tail:.*}", self._handle_all)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()


class HookPulseApp(App):
    CSS = """
    Screen {
        background: $surface-darken-1;
    }
    #top-bar {
        height: 3;
        background: $panel;
        border-bottom: solid $primary;
        padding: 0 2;
        content-align: left middle;
        color: $accent;
        text-style: bold;
    }
    #main-split {
        height: 1fr;
    }
    #left-pane {
        width: 44%;
        border-right: solid $primary;
    }
    #right-pane {
        width: 56%;
        padding: 0 1;
    }
    #filter-input {
        dock: top;
        margin: 1 1 0 1;
    }
    DataTable {
        height: 1fr;
    }
    .detail-box {
        padding: 1 1;
        height: 1fr;
        overflow-y: auto;
    }
    """

    BINDINGS = [
        Binding("r", "replay_selected", "Replay Request"),
        Binding("p", "copy_pydantic", "Copy Pydantic"),
        Binding("c", "copy_curl", "Copy cURL"),
        Binding("d", "load_demo", "Demo Webhooks"),
        Binding("x", "clear_requests", "Clear All"),
        Binding("s", "export_json", "Save JSON"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 9000,
        target_url: str = "http://localhost:8000",
        preload_demo: bool = False,
    ) -> None:
        super().__init__()
        self.host = host
        self.port = port
        self.target_url = target_url
        self.preload_demo = preload_demo
        self.requests: List[CapturedRequest] = []
        self.filtered_requests: List[CapturedRequest] = []
        self.selected_request: Optional[CapturedRequest] = None
        self.server: Optional[WebhookCaptureServer] = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(
            f"⚡ HookPulse Listening on http://{self.host}:{self.port}   ➔   Replay Target: {self.target_url}",
            id="top-bar",
        )
        with Horizontal(id="main-split"):
            with Vertical(id="left-pane"):
                yield Input(placeholder="Filter by path, source (Stripe/GitHub), or method...", id="filter-input")
                yield DataTable(id="request-table", cursor_type="row")
            with Vertical(id="right-pane"):
                with TabbedContent(initial="tab-body"):
                    with TabPane("JSON / Body", id="tab-body"):
                        yield Static("Select or send a webhook to inspect payload.", id="view-body", classes="detail-box")
                    with TabPane("Pydantic v2 Schema", id="tab-schema"):
                        yield Static("Select a JSON webhook to generate Pydantic v2 models.", id="view-schema", classes="detail-box")
                    with TabPane("Headers & Replay", id="tab-headers"):
                        yield Static("Headers and replay status will appear here.", id="view-headers", classes="detail-box")
                    with TabPane("cURL Command", id="tab-curl"):
                        yield Static("cURL command will appear here.", id="view-curl", classes="detail-box")
        yield Footer()

    async def on_mount(self) -> None:
        table = self.query_one("#request-table", DataTable)
        table.add_columns("Time", "Method", "Source", "Path", "Replay")
        self.server = WebhookCaptureServer(
            host=self.host,
            port=self.port,
            on_request=self.handle_incoming_request,
        )
        await self.server.start()
        if self.preload_demo:
            for item in build_demo_requests():
                self.requests.append(item)
            self._refresh_table()

    async def on_unmount(self) -> None:
        if self.server:
            await self.server.stop()

    async def handle_incoming_request(self, req: CapturedRequest) -> None:
        self.requests.insert(0, req)
        self._refresh_table()
        self.notify(f"Captured {req.method} {req.path} ({req.source_badge})", title="Incoming Webhook")

    def _refresh_table(self) -> None:
        query = self.query_one("#filter-input", Input).value.strip().lower()
        table = self.query_one("#request-table", DataTable)
        table.clear()
        self.filtered_requests = [
            r
            for r in self.requests
            if not query
            or query in r.path.lower()
            or query in r.method.lower()
            or query in r.source_badge.lower()
            or query in r.raw_body.lower()
        ]
        for req in self.filtered_requests:
            if req.last_replay:
                if req.last_replay.error:
                    replay_label = "ERR"
                else:
                    replay_label = f"{req.last_replay.status_code} ({req.last_replay.elapsed_ms}ms)"
            else:
                replay_label = "—"
            table.add_row(req.timestamp, req.method, req.source_badge, req.path, replay_label, key=req.id)

        if self.filtered_requests and self.selected_request is None:
            self.selected_request = self.filtered_requests[0]
            self._update_detail_views(self.selected_request)
        elif self.selected_request:
            self._update_detail_views(self.selected_request)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter-input":
            self._refresh_table()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key and event.row_key.value:
            req_id = str(event.row_key.value)
            for req in self.filtered_requests:
                if req.id == req_id:
                    self.selected_request = req
                    self._update_detail_views(req)
                    break

    def _update_detail_views(self, req: CapturedRequest) -> None:
        body_widget = self.query_one("#view-body", Static)
        schema_widget = self.query_one("#view-schema", Static)
        headers_widget = self.query_one("#view-headers", Static)
        curl_widget = self.query_one("#view-curl", Static)

        formatted = req.formatted_body
        lexer = "json" if req.parsed_json is not None else "text"
        body_widget.update(Syntax(formatted or "<Empty Body>", lexer, theme="monokai", word_wrap=True))

        schema_code = infer_pydantic_schema(req.parsed_json if req.parsed_json is not None else req.raw_body)
        schema_widget.update(Syntax(schema_code, "python", theme="monokai", word_wrap=True))

        hdr_table = Table(show_header=True, header_style="bold cyan", expand=True)
        hdr_table.add_column("Header", style="bold cyan", width=28)
        hdr_table.add_column("Value", style="white")
        for k, v in req.headers.items():
            hdr_table.add_row(k, v)
        if req.last_replay:
            rep = req.last_replay
            status_line = f"Error: {rep.error}" if rep.error else f"HTTP {rep.status_code} in {rep.elapsed_ms} ms"
            hdr_table.add_row("Last Replay Status", status_line)
        headers_widget.update(Panel(hdr_table, title=f"{req.method} {req.path} ({req.size_bytes} bytes)"))

        curl_cmd = req.to_curl(self.target_url)
        curl_widget.update(Syntax(curl_cmd, "bash", theme="monokai", word_wrap=True))

    async def action_replay_selected(self) -> None:
        if not self.selected_request:
            self.notify("Select a request first.", severity="warning")
            return
        req = self.selected_request
        self.notify(f"Replaying {req.method} {req.path} -> {self.target_url} ...")
        result = await replay_request(req, self.target_url)
        self._refresh_table()
        if result.error:
            self.notify(f"Replay failed: {result.error}", severity="error")
        else:
            self.notify(f"Replay HTTP {result.status_code} ({result.elapsed_ms} ms)", title="Replay Complete")

    def action_copy_pydantic(self) -> None:
        if not self.selected_request:
            return
        req = self.selected_request
        code = infer_pydantic_schema(req.parsed_json if req.parsed_json is not None else req.raw_body)
        try:
            pyperclip.copy(code)
            self.notify("Pydantic v2 schema copied to clipboard!", title="Copied")
        except Exception:
            self.notify("Clipboard unavailable in headless environment; view in Pydantic tab.", severity="warning")

    def action_copy_curl(self) -> None:
        if not self.selected_request:
            return
        cmd = self.selected_request.to_curl(self.target_url)
        try:
            pyperclip.copy(cmd)
            self.notify("cURL command copied to clipboard!", title="Copied")
        except Exception:
            self.notify("Clipboard unavailable in headless environment; view in cURL tab.", severity="warning")

    def action_load_demo(self) -> None:
        for item in build_demo_requests():
            self.requests.insert(0, item)
        self._refresh_table()
        self.notify("Loaded 3 sample webhooks (Stripe, GitHub, Telegram)", title="Demo Mode")

    def action_clear_requests(self) -> None:
        self.requests.clear()
        self.filtered_requests.clear()
        self.selected_request = None
        self._refresh_table()
        self.notify("Cleared all captured webhooks.")

    def action_export_json(self) -> None:
        data = [r.to_dict() for r in self.requests]
        with open("hookpulse_history.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        self.notify("Saved captured requests to hookpulse_history.json", title="Exported")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hookpulse",
        description="HookPulse — Interactive TUI Webhook & API Request Debugger with instant Replay and Pydantic v2 schema generation.",
    )
    parser.add_argument("-p", "--port", type=int, default=9000, help="Local port to listen for incoming webhooks (default: 9000)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host address to bind (default: 0.0.0.0)")
    parser.add_argument("-t", "--target", type=str, default="http://localhost:8000", help="Target local server URL for Replay (default: http://localhost:8000)")
    parser.add_argument("--demo", action="store_true", help="Preload realistic Stripe, GitHub, and Telegram webhooks on startup")
    parser.add_argument("--schema-from-file", type=str, default=None, help="Generate Pydantic v2 schema directly from a JSON file and print to stdout")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.schema_from_file:
        with open(args.schema_from_file, "r", encoding="utf-8") as f:
            raw = f.read()
        print(infer_pydantic_schema(raw))
        return 0

    app = HookPulseApp(
        host=args.host,
        port=args.port,
        target_url=args.target,
        preload_demo=args.demo,
    )
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
