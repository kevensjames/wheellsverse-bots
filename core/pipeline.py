#!/usr/bin/env python3
"""
core/pipeline.py
─────────────────────────────────────────────────────────────────────────────
Pipeline Engine — chains bots together, passing outputs as context.
Pipelines are defined in config.yaml under the 'pipelines' key.
─────────────────────────────────────────────────────────────────────────────
"""

import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

ROOT = Path(__file__).parent.parent
logger = logging.getLogger("pipeline")


class Pipeline:
    """
    A named sequence of bots. Each bot's output dict is merged into
    the shared context and forwarded to the next bot as kwargs.
    """

    def __init__(self, name: str, config: dict, orchestrator):
        self.name = name
        self.display_name = config.get("name", name)
        self.description = config.get("description", "")
        self.bot_names: List[str] = config.get("bots", [])
        self.orchestrator = orchestrator

        # State
        self.status = "idle"          # idle | running | done | error
        self.last_run: Optional[float] = None
        self.last_result: Optional[List[Dict]] = None
        self.run_count = 0
        self.error: Optional[str] = None

    def run(self, initial_context: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Execute all bots in sequence.
        Each bot receives the accumulated context from all previous bots.
        """
        self.status = "running"
        self.error = None
        context: Dict[str, Any] = initial_context or {}
        results: List[Dict] = []

        logger.info(f"▶  Pipeline '{self.name}' starting — {len(self.bot_names)} bots")

        for bot_name in self.bot_names:
            step_result: Dict = {
                "bot": bot_name,
                "started_at": datetime.now().isoformat(),
                "status": "pending",
                "result": None,
                "error": None,
            }
            try:
                logger.info(f"  → Running {bot_name}")
                result = self.orchestrator.run_bot(bot_name, **context)
                step_result["status"] = "success"
                step_result["result"] = result

                # Merge string-valued keys into shared context for chaining
                if isinstance(result, dict):
                    for k, v in result.items():
                        if isinstance(v, str) and len(v) < 4000:
                            context[k] = v

            except Exception as e:
                step_result["status"] = "error"
                step_result["error"] = str(e)
                logger.error(f"  ✗ {bot_name} failed: {e}")
                # Continue pipeline — don't stop on individual bot failure

            step_result["finished_at"] = datetime.now().isoformat()
            results.append(step_result)

        success_count = sum(1 for r in results if r["status"] == "success")
        self.status = "done" if success_count > 0 else "error"
        self.last_run = time.time()
        self.last_result = results
        self.run_count += 1

        logger.info(
            f"✅ Pipeline '{self.name}' complete — "
            f"{success_count}/{len(self.bot_names)} bots succeeded"
        )

        return {
            "pipeline": self.name,
            "display_name": self.display_name,
            "total_bots": len(self.bot_names),
            "succeeded": success_count,
            "failed": len(self.bot_names) - success_count,
            "results": results,
        }

    def get_info(self) -> Dict:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "bots": self.bot_names,
            "bot_count": len(self.bot_names),
            "status": self.status,
            "run_count": self.run_count,
            "last_run": (
                datetime.fromtimestamp(self.last_run).isoformat()
                if self.last_run else None
            ),
            "error": self.error,
        }


class PipelineEngine:
    """
    Loads all pipelines from config.yaml and provides execution methods.
    """

    def __init__(self, orchestrator):
        self.orchestrator = orchestrator
        self.pipelines: Dict[str, Pipeline] = {}
        self._load_pipelines()

    def _load_pipelines(self):
        config_path = ROOT / "config.yaml"
        if not config_path.exists():
            logger.warning("config.yaml not found — no pipelines loaded")
            return

        with open(config_path) as f:
            cfg = yaml.safe_load(f) or {}

        pipeline_configs = cfg.get("pipelines", {})
        for name, pcfg in pipeline_configs.items():
            self.pipelines[name] = Pipeline(name, pcfg, self.orchestrator)

        logger.info(f"🔗 {len(self.pipelines)} pipelines loaded")

    def run_pipeline(self, name: str, **kwargs) -> Dict[str, Any]:
        if name not in self.pipelines:
            raise ValueError(f"Pipeline '{name}' not found. Available: {list(self.pipelines)}")
        return self.pipelines[name].run(kwargs if kwargs else None)

    def list_pipelines(self) -> List[Dict]:
        return [p.get_info() for p in self.pipelines.values()]

    def get_pipeline(self, name: str) -> Optional[Pipeline]:
        return self.pipelines.get(name)
