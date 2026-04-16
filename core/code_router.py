#!/usr/bin/env python3
"""
core/code_router.py
─────────────────────────────────────────────────────────────────────────────
FastAPI router for AI code generation, saving, running, and streaming.
Prefix: /api/code
─────────────────────────────────────────────────────────────────────────────
"""

import asyncio
import logging
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from core.code_engine import (
    active_runs,
    generate_code,
    kill_code,
    list_generated_files,
    read_generated_file,
    run_code,
    save_code,
    validate_code,
)

logger = logging.getLogger("code_router")
router = APIRouter(prefix="/api/code", tags=["code"])


# ─── Request models ───────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    prompt: str
    template: Optional[str] = None


class SaveRequest(BaseModel):
    name: str
    code: str


class RunRequest(BaseModel):
    path: str


class KillRequest(BaseModel):
    run_id: str


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.post("/generate")
async def code_generate(req: GenerateRequest):
    """Generate Python bot code with Claude and validate syntax."""
    try:
        code = await asyncio.to_thread(generate_code, req.prompt, req.template)
        valid, error = validate_code(code)
        return {
            "ok": True,
            "code": code,
            "valid": valid,
            "error": error,
        }
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.exception("Error generating code")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/save")
def code_save(req: SaveRequest):
    """Save generated code to generated_bots/{name}.py."""
    valid, error = validate_code(req.code)
    if not valid:
        raise HTTPException(status_code=400, detail=f"Invalid Python syntax: {error}")
    try:
        path = save_code(req.name, req.code)
        return {"ok": True, "path": str(path)}
    except Exception as e:
        logger.exception("Error saving code")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/run")
def code_run(req: RunRequest):
    """Run a Python file and return a run_id for streaming output."""
    try:
        run_id = run_code(req.path)
        return {"ok": True, "run_id": run_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("Error starting code run")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/kill")
def code_kill(req: KillRequest):
    """Terminate an active code run."""
    killed = kill_code(req.run_id)
    return {"ok": True, "killed": killed}


@router.get("/files")
def code_files():
    """List all files in generated_bots/."""
    return {"files": list_generated_files()}


@router.get("/file/{name}")
def code_file(name: str):
    """Read a generated bot file."""
    try:
        code = read_generated_file(name)
        return {"name": name, "code": code}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/runs")
def code_runs():
    """List currently active code runs."""
    return {"runs": active_runs()}


# ─── WebSocket: stream run output ─────────────────────────────────────────────

@router.websocket("/stream/{run_id}")
async def code_stream(websocket: WebSocket, run_id: str):
    """
    WebSocket endpoint to stream subprocess stdout line by line.
    Sends: {"line": "...", "ts": 1234567890.0}
    Closes with: {"done": true, "exit": <code>}
    """
    await websocket.accept()
    logger.info(f"[code_router] WebSocket connected for run_id={run_id}")

    from core.code_engine import _active_runs

    popen = _active_runs.get(run_id)
    if not popen:
        await websocket.send_json({"error": f"No active run: {run_id}"})
        await websocket.close()
        return

    try:
        # Read lines in a background thread to avoid blocking the event loop
        def _iter_lines():
            lines = []
            for line in popen.stdout:
                lines.append(line)
            return lines

        # Stream line-by-line using asyncio.to_thread for each read
        asyncio.get_event_loop()
        while True:
            # Non-blocking readline
            line = await asyncio.to_thread(popen.stdout.readline)
            if not line:
                # EOF — process finished
                popen.wait()
                _active_runs.pop(run_id, None)
                await websocket.send_json({"done": True, "exit": popen.returncode})
                break
            await websocket.send_json({"line": line.rstrip("\n"), "ts": time.time()})

    except WebSocketDisconnect:
        logger.info(f"[code_router] Client disconnected from run {run_id}")
        # Don't kill the process — client just closed the tab
    except Exception as e:
        logger.exception(f"[code_router] Stream error for run {run_id}")
        try:
            await websocket.send_json({"error": str(e)})
            await websocket.close()
        except Exception:
            pass
