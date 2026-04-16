#!/usr/bin/env python3
"""
bots/books/publisher_engine/pipeline.py
─────────────────────────────────────────────────────────────────────────────
PublisherEnginePipeline — orchestrates all 7 agents sequentially.

Agents (in order):
  1. story_agent      — plot structure + pacing
  2. editing_agent    — grammar + clarity
  3. style_agent      — tone + dialogue
  4. market_agent     — titles + keywords + categories
  5. design_agent     — cover prompt + layout
  6. marketing_agent  — description + TikTok + email + sales page
  7. distribution_agent — KDP package + HTML + cover generation

Usage:
  python pipeline.py --manuscript path/to/book.md --title "My Book" --genre mystery
  python pipeline.py --test   (runs on sample text, no publish)
─────────────────────────────────────────────────────────────────────────────
"""
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from core.base_bot import BaseBot  # noqa: E402
from bots.books.publisher_engine import (  # noqa: E402
    story_agent, editing_agent, style_agent,
    market_agent, design_agent, marketing_agent, distribution_agent,
)

RESULTS_FILE = ROOT / "data" / "publisher_engine_results.json"
STATUS_FILE = ROOT / "data" / "publisher_engine_status.json"
MAX_RESULTS = 50

AGENTS = [
    ("story_agent", story_agent),
    ("editing_agent", editing_agent),
    ("style_agent", style_agent),
    ("market_agent", market_agent),
    ("design_agent", design_agent),
    ("marketing_agent", marketing_agent),
    ("distribution_agent", distribution_agent),
]


class PublisherEnginePipeline(BaseBot):
    """
    Runs a manuscript through the full 7-agent literary production pipeline.
    """

    def __init__(self):
        super().__init__("publisher_engine", "books")

    def run(self, action: str = "process", **kwargs) -> dict:
        if action == "process":
            return self.process(
                manuscript=kwargs.get("manuscript", ""),
                title=kwargs.get("title", "untitled"),
                genre=kwargs.get("genre", "mystery"),
                author=kwargs.get("author", "J.K. Blaze"),
                skip_agents=kwargs.get("skip_agents", []),
            )
        elif action == "status":
            return self._load_status()
        elif action == "results":
            return {"results": self._load_results()}
        return {}

    def process(
        self,
        manuscript: str,
        title: str,
        genre: str = "mystery",
        author: str = "J.K. Blaze",
        skip_agents: list = None,
        skip_word_check: bool = False,
    ) -> dict:
        """
        Run all 7 agents on the manuscript.
        Each agent receives the manuscript (possibly improved by prior agents)
        plus accumulated context from all previous agents.
        """
        # ── Hard completeness gate — block incomplete manuscripts ────────────
        word_count = len(manuscript.split())
        if not skip_word_check and word_count < 8000:
            self.logger.error("Publisher Engine blocked: manuscript too short (%d words)", word_count)
            return {
                "error":   "manuscript_too_short",
                "message": f"Manuscript only {word_count} words — minimum 8,000 required before Publisher Engine.",
                "title":   title,
                "genre":   genre,
            }
        _tail = manuscript[-400:].lower()
        _end_markers = ["the end", "**the end**", "epilogue", "about the author", "acknowledgment"]
        if not any(m in _tail for m in _end_markers):
            _stripped = manuscript.rstrip()
            if _stripped and _stripped[-1] not in ".!?\"'…":
                self.logger.error("Publisher Engine blocked: manuscript has no proper ending")
                return {
                    "error":   "manuscript_incomplete",
                    "message": "Manuscript does not have a proper ending — run QC first.",
                    "title":   title,
                    "genre":   genre,
                }

        skip_agents = skip_agents or []
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        word_count = len(manuscript.split())

        self.logger.info("Publisher Engine starting: '%s' (%d words, genre: %s)",
                         title, word_count, genre)

        self._update_status({
            "running": True,
            "title": title,
            "genre": genre,
            "started_at": datetime.now().isoformat(),
            "current_agent": None,
            "agents_completed": [],
            "word_count": word_count,
        })

        # Accumulated context passed to each agent
        context = {
            "title": title,
            "genre": genre,
            "author": author,
            "ts": ts,
        }

        # The manuscript evolves as each agent improves it
        current_manuscript = manuscript
        agent_results = {}
        errors = []

        for agent_name, agent_module in AGENTS:
            if agent_name in skip_agents:
                self.logger.info("Skipping agent: %s", agent_name)
                agent_results[agent_name] = {"skipped": True}
                continue

            self.logger.info("Running agent: %s", agent_name)
            self._update_status({
                "running": True,
                "title": title,
                "current_agent": agent_name,
                "agents_completed": list(agent_results.keys()),
            })

            t0 = time.time()
            try:
                result = agent_module.run(current_manuscript, context, self)
                elapsed = round(time.time() - t0, 1)
                result["elapsed_seconds"] = elapsed
                agent_results[agent_name] = result

                # Persist improved manuscript from writing agents
                improved_key = {
                    "story_agent": "improved_manuscript",
                    "editing_agent": "edited_manuscript",
                    "style_agent": "styled_manuscript",
                }.get(agent_name)

                if improved_key and result.get(improved_key):
                    new_ms = result[improved_key]
                    orig_lines = len(current_manuscript.split("\n"))
                    new_lines = len(new_ms.split("\n"))
                    if len(new_ms.split()) >= len(current_manuscript.split()) * 0.5:
                        # Guard: reject if line structure was destroyed (lost >90% of lines)
                        if new_lines < orig_lines * 0.1 and orig_lines > 50:
                            self.logger.warning(
                                "%s destroyed line structure (%d→%d lines) — keeping original",
                                agent_name, orig_lines, new_lines
                            )
                        else:
                            current_manuscript = new_ms
                            self.logger.info("Manuscript updated by %s (%d words, %d lines)",
                                             agent_name, len(new_ms.split()), new_lines)

                # Add this agent's output to context for downstream agents
                context[agent_name] = {k: v for k, v in result.items()
                                       if k not in ("improved_manuscript", "edited_manuscript",
                                                    "styled_manuscript") and isinstance(v, (str, list, dict, int, float, bool))}
                # Also promote key fields to top-level context
                for key in ("pricing_recommendation", "keywords", "titles", "recommended_title",
                             "target_reader", "description", "cover_prompt"):
                    if key in result:
                        context[key] = result[key]

                self.logger.info("Agent %s completed in %.1fs", agent_name, elapsed)

            except Exception as e:
                self.logger.error("Agent %s failed: %s", agent_name, e)
                agent_results[agent_name] = {"error": str(e), "skipped": False}
                errors.append(f"{agent_name}: {e}")
                # Continue pipeline — don't block on one agent failure

        # ── Save final manuscript ──────────────────────────────────────────────
        final_word_count = len(current_manuscript.split())
        out_dir = ROOT / "outputs" / "books" / genre
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_title = title.lower().replace(" ", "_").replace("'", "")[:40]
        ms_path = out_dir / f"pe_{safe_title}_{ts}.md"
        ms_path.write_text(current_manuscript, encoding="utf-8")
        self.logger.info("Final manuscript saved: %s (%d words)", ms_path.name, final_word_count)

        dist = agent_results.get("distribution_agent", {})
        final = {
            "title": title,
            "genre": genre,
            "author": author,
            "original_words": word_count,
            "final_words": final_word_count,
            "manuscript_path": str(ms_path),
            "html_path": dist.get("html_path"),
            "cover_path": dist.get("cover_path"),
            "kdp_package_path": dist.get("kdp_package_path"),
            "ready_to_publish": dist.get("ready_to_publish", False),
            "validation_errors": dist.get("validation_errors", []),
            "agents": agent_results,
            "errors": errors,
            "ts": ts,
            "completed_at": datetime.now().isoformat(),
            # Surface key outputs
            "titles": agent_results.get("market_agent", {}).get("titles", [title]),
            "recommended_title": agent_results.get("market_agent", {}).get("recommended_title", title),
            "keywords": agent_results.get("market_agent", {}).get("keywords", []),
            "description": agent_results.get("marketing_agent", {}).get("description", ""),
            "tiktok_hooks": agent_results.get("marketing_agent", {}).get("tiktok_hooks", []),
            "email_sequence": agent_results.get("marketing_agent", {}).get("email_sequence", []),
            "cover_prompt": agent_results.get("design_agent", {}).get("cover_prompt", ""),
        }

        self._save_result(final)
        self._update_status({"running": False, "last_completed": title,
                              "completed_at": final["completed_at"]})

        self.logger.info("Publisher Engine complete: '%s' — ready_to_publish=%s",
                         title, final["ready_to_publish"])

        # ── Autopilot QC + queue submission ───────────────────────────────────
        qc_result = {}
        autopilot_queued = False
        rewrite_queued = False
        try:
            from core.literary_qc import LiteraryQCAgent
            _qc = LiteraryQCAgent()
            qc_result = _qc.full_book_analysis(
                current_manuscript,
                title,
                genre=genre,
                manuscript_path=str(ms_path),
            )
            approved = qc_result.get("approved", False)
            ts_q = datetime.now().strftime("%Y%m%d_%H%M%S")
            q_entry = {
                "id": f"kdp_q_{ts_q}",
                "title": title,
                "genre": genre,
                "author": author,
                "manuscript_path": str(ms_path),
                "cover_path": dist.get("cover_path", ""),
                "html_path": dist.get("html_path", ""),
                "word_count": final_word_count,
                "qc_score": qc_result.get("overall_score", 0),
                "queued_at": datetime.now().isoformat(),
                "status": "queued",
            }
            if approved:
                queue_file = ROOT / "data" / "kdp_autopilot_queue.json"
                queue: list = []
                if queue_file.exists():
                    try:
                        queue = json.loads(queue_file.read_text(encoding="utf-8"))
                    except Exception:
                        queue = []
                # Deduplicate by manuscript_path
                queue = [q for q in queue if q.get("manuscript_path") != str(ms_path)]
                queue.append(q_entry)
                queue_file.write_text(json.dumps(queue, indent=2, ensure_ascii=False), encoding="utf-8")
                autopilot_queued = True
                self.logger.info("Autopilot: '%s' queued for KDP publish", title)
            else:
                # full_book_analysis() already wrote to narai_rewrite_queue internally
                rewrite_queued = True
                self.logger.info("Autopilot: '%s' sent to rewrite queue (score=%s)",
                                 title, qc_result.get("overall_score"))
        except Exception as _qc_err:
            self.logger.warning("Autopilot QC step failed (non-fatal): %s", _qc_err)

        final["qc_result"] = qc_result
        final["autopilot_queued"] = autopilot_queued
        final["rewrite_queued"] = rewrite_queued

        # ── Telegram notification ─────────────────────────────────────────────
        try:
            from core.telegram import notify
            queue_line = (
                "✅ Auto-queued for KDP" if autopilot_queued
                else ("⚠️ Sent to rewrite queue" if rewrite_queued else "📋 QC pending")
            )
            notify(
                f"📚 Publisher Engine Complete\n"
                f"📖 {title}\n"
                f"📊 {final_word_count:,} words\n"
                f"{'✅ Ready to publish' if final['ready_to_publish'] else '⚠️ Review needed'}\n"
                f"🎨 Cover: {'generated' if dist.get('cover_path') else 'pending'}\n"
                f"{queue_line}"
            )
        except Exception:
            pass

        return final

    # ── Persistence ───────────────────────────────────────────────────────────

    def _update_status(self, data: dict):
        try:
            STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATUS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _load_status(self) -> dict:
        try:
            if STATUS_FILE.exists():
                return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {"running": False}

    def _save_result(self, result: dict):
        try:
            results = []
            if RESULTS_FILE.exists():
                try:
                    results = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
                except Exception:
                    results = []
            # Store summary only (not full manuscript text)
            summary = {k: v for k, v in result.items()
                       if k not in ("agents",) and not isinstance(v, str) or len(str(v)) < 2000}
            results.append(summary)
            results = results[-MAX_RESULTS:]
            RESULTS_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False),
                                    encoding="utf-8")
        except Exception as e:
            self.logger.warning("Failed to save pipeline result: %s", e)

    def _load_results(self, limit: int = 20) -> list:
        try:
            if RESULTS_FILE.exists():
                results = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
                return results[-limit:]
        except Exception:
            pass
        return []


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="NarAI Publisher Engine — full 7-agent pipeline")
    p.add_argument("--manuscript", help="Path to .md manuscript file")
    p.add_argument("--title", default="", help="Book title")
    p.add_argument("--genre", default="mystery", help="Genre")
    p.add_argument("--author", default="J.K. Blaze", help="Author pen name")
    p.add_argument("--skip", nargs="*", default=[], help="Agent names to skip")
    p.add_argument("--test", action="store_true", help="Run on sample text")
    args = p.parse_args()

    pipeline = PublisherEnginePipeline()

    if args.test:
        sample = """# Test Mystery Novel\n\n*By J.K. Blaze*\n\n## Chapter 1: The Beginning\n\n
Detective Sara Chen pressed her palm to the cold floor. The museum was silent.
She felt nothing — no memories, just emptiness. Someone had stolen everything from the victim.

## Chapter 2: The Investigation\n\nShe followed the clues to a shadowy organization called the Meridian Group.
Dr. James Cortex — real name unknown — was behind it all.

## Chapter 14: The End\n\nSara defeated the Meridian Group. All memories were returned.
Rodriguez was safe. Justice was served.\n\n**THE END**"""
        result = pipeline.process(sample, "Test Mystery", "mystery")
        print(f"\n✅ Pipeline complete: {result['title']}")
        print(f"   Titles: {result['titles'][:2]}")
        print(f"   Ready: {result['ready_to_publish']}")
        sys.exit(0)

    if not args.manuscript:
        p.error("--manuscript or --test required")

    text = Path(args.manuscript).read_text(encoding="utf-8")
    title = args.title or Path(args.manuscript).stem.replace("_", " ").title()

    result = pipeline.process(text, title, args.genre, args.author, args.skip)

    print(f"\n{'=' * 60}")
    print("  PIPELINE COMPLETE")
    print(f"{'=' * 60}")
    print(f"  Title        : {result['title']}")
    print(f"  Final words  : {result['final_words']:,}")
    print(f"  HTML package : {result.get('html_path', 'n/a')}")
    print(f"  Cover        : {result.get('cover_path', 'n/a')}")
    print(f"  Ready        : {result['ready_to_publish']}")
    if result.get("titles"):
        print(f"  Title options: {result['titles'][:3]}")
    if result.get("errors"):
        print(f"  Errors       : {result['errors']}")
    print(f"{'=' * 60}")
