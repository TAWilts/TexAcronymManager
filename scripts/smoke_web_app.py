"""Launch a hidden native WebView and verify that the shared UI receives data."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import threading
import time

import webview

from tacroman.web_app import DesktopWebApi, WebAppController, build_desktop_html


def main() -> None:
    failures: list[BaseException] = []
    result: dict[str, object] = {}
    completed = threading.Event()

    def timeout() -> None:
        if not completed.wait(20):
            print("ERROR: Desktop WebView startup timed out after 20 seconds.", flush=True)
            os._exit(2)

    threading.Thread(target=timeout, daemon=True).start()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        api = DesktopWebApi(
            WebAppController,
            database_path=root / "entries.json",
            output_path=root / "entries.tex",
            state_path=root / "state.json",
        )
        window = webview.create_window(
            "TAcroMan smoke test",
            html=build_desktop_html(),
            js_api=api,
            width=900,
            height=600,
            minimized=True,
        )
        api._attach_window(window)
        window.events.closed += api._stop

        def verify() -> None:
            try:
                print("Desktop WebView started; checking shared UI...", flush=True)
                for _attempt in range(30):
                    value = window.evaluate_js(
                        "JSON.stringify({"
                        "ready: document.readyState,"
                        "database: document.getElementById('database-path')?.textContent,"
                        "status: document.getElementById('status')?.textContent,"
                        "profile: document.getElementById('profile-select')?.value"
                        "})"
                    )
                    current = json.loads(value) if isinstance(value, str) else {}
                    if current.get("status") in {"Ready", "Bereit"}:
                        result.update(current)
                        break
                    time.sleep(0.25)
                if result.get("status") not in {"Ready", "Bereit"}:
                    raise RuntimeError(f"Shared UI did not become ready: {current}")
            except BaseException as error:  # pragma: no cover - smoke-test handoff
                failures.append(error)
            finally:
                window.destroy()

        webview.start(verify)
        completed.set()

    if failures:
        raise failures[0]
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
