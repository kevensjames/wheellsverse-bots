#!/usr/bin/env python3
"""
Bot #56 — File Organization System Builder
Category: Assistant
Purpose: Design a complete file organization system with folder structures, naming
         conventions, archiving rules, and automation scripts for entrepreneurs.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402

FOLDER_TYPES = {
    "business": "Complete business file system — clients, finance, legal, operations",
    "content": "Content creator system — videos, images, scripts, drafts, published",
    "projects": "Project management system — active, archived, templates, resources",
    "downloads": "Downloads folder organization — sort by type and recency",
    "dev": "Developer workspace — repos, snippets, docs, environments",
    "marketing": "Marketing assets — campaigns, ads, copy, analytics, brand",
    "finance": "Financial documents — invoices, receipts, taxes, contracts",
    "media": "Media library — photos, videos, audio, organized by date/project",
}

OS_TYPES = ["mac", "windows", "linux", "cloud_drive"]


class FileOrganizerBot(BaseBot):

    def __init__(self):
        super().__init__("56_file_organizer", "assistant")

    def run(self, folder_type: str = None, os_type: str = None,
            current_chaos: str = None, file_types: str = None, **kwargs):

        cfg = self.config
        folder_type = folder_type or cfg.get("folder_type", "business")
        os_type = os_type or cfg.get("os_type", "mac")
        current_chaos = current_chaos or cfg.get("current_chaos",
            "files scattered across Desktop, Downloads, and random folders")
        file_types = file_types or cfg.get("file_types",
            "PDFs, spreadsheets, images, Python scripts, markdown files, video files")

        type_desc = FOLDER_TYPES.get(folder_type, folder_type)
        self.logger.info(f"Designing {folder_type} file organization system for {os_type}")

        system = (
            "You are a digital organization specialist and systems designer who has helped "
            "hundreds of entrepreneurs go from digital chaos to a clean, searchable, automated "
            "file system. You believe that a good file system has three properties: "
            "1) You can find any file in under 10 seconds, "
            "2) Anyone (or any bot) can understand the structure without explanation, "
            "3) It stays organized with minimal maintenance. "
            "You design for the long term — not just 'tidy up today' but 'never lose a file again.' "
            "You provide specific folder names, naming conventions, and automation scripts."
        )

        prompt = f"""Design a complete file organization system for:

SYSTEM TYPE: {folder_type} — {type_desc}
OPERATING SYSTEM: {os_type}
CURRENT SITUATION: {current_chaos}
FILE TYPES TO ORGANIZE: {file_types}
CONTEXT: WheellsVerse entrepreneur — AI automation, content creation, business operations

---

## CURRENT STATE ANALYSIS

**Problems with the current setup:**
[Based on "{current_chaos}", identify the specific problems this causes]

**Root causes:**
1. [Root cause 1]
2. [Root cause 2]
3. [Root cause 3]

---

## FOLDER STRUCTURE

Complete folder hierarchy for a {folder_type} system:

```
📁 [ROOT FOLDER NAME]/
├── 📁 [Category 1]/
│   ├── 📁 [Subcategory 1a]/
│   ├── 📁 [Subcategory 1b]/
│   └── 📁 _Archive/
├── 📁 [Category 2]/
│   ├── 📁 [Subcategory 2a]/
│   └── 📁 [Subcategory 2b]/
[Continue full hierarchy — minimum 3 levels deep for relevant categories]
├── 📁 _Inbox/          ← New files land here first
├── 📁 _Archive/        ← Files older than 1 year
└── 📁 _Templates/      ← Reusable templates
```

**Why this structure works:**
[Brief explanation of the organizational logic]

---

## FILE NAMING CONVENTIONS

**Universal naming formula:**
```
[YYYY-MM-DD]_[PROJECT]_[DESCRIPTOR]_[VERSION].[ext]
```

**Examples for each file type:**
| File Type | Bad Name | Good Name | Why |
| PDF contract | contract.pdf | 2025-03-15_ClientName_ServiceAgreement_v1.pdf | Searchable, dated, versioned |
| Image | image001.jpg | 2025-03-15_WheellsVerse_HeroBanner_1200x628.jpg | Specs embedded |
| Script | script.py | 2025-03-15_ContentBot_EmailGenerator_v2.py | Project context |
[Continue for all file types in: {file_types}]

**Versioning rules:**
- Draft: `_draft`
- In review: `_review`
- Final: `_final` or `_v1`, `_v2`
- Archive: Move to `_Archive/` folder — never delete

---

## SORTING RULES BY FILE TYPE

How to handle each type in {file_types}:
| File Type | Goes In | Naming Pattern | Retention Policy |
[One row per file type]

---

## ONE-TIME CLEANUP PLAN

5-step process to organize the existing chaos:

**Step 1 — Create the new structure (30 min)**
[Exact commands or steps for {os_type}]

**Step 2 — Sort the inbox (1-2 hours)**
[Process for sorting existing files — decision tree]

**Step 3 — Rename key files (1 hour)**
[Which files to rename first, bulk rename tools]

**Step 4 — Archive old files (30 min)**
[What qualifies for archive, how to move them]

**Step 5 — Set up automation (1 hour)**
[Auto-sort rules — see below]

---

## AUTOMATION SCRIPTS

### Auto-Sort New Files ({os_type})

```bash
# [Script or tool recommendation for {os_type} to auto-organize downloads/inbox]
# Tool: [Hazel (Mac) / File Juggler (Windows) / Python watchdog (Linux/all)]
```

**Rule examples:**
- Files ending in `.pdf` → sort into `Finance/` or `Projects/` based on name
- Files with `invoice` in name → `Finance/Invoices/`
- Image files → `Media/Images/YYYY-MM/`
[5-10 automation rules specific to: {file_types}]

### Weekly Maintenance Script (5 minutes)
```
1. Clear _Inbox folder
2. Move completed project files to _Archive
3. Delete duplicates (use [tool] for {os_type})
4. Backup to [cloud storage]
```

---

## SEARCH & RETRIEVAL TIPS

Find any file in under 10 seconds on {os_type}:
- **Search tool:** [Recommended search app for {os_type}]
- **Search tips:** [How to use naming convention for fast search]
- **Tagging:** [If applicable for {os_type}]

## MAINTENANCE SCHEDULE

| Frequency | Task | Time Needed |
| Daily | Clear inbox | 5 min |
| Weekly | Archive completed work | 15 min |
| Monthly | Delete duplicates | 30 min |
| Quarterly | Full audit + restructure if needed | 1-2 hours |"""

        result = self.ai(prompt, system=system,
                         model=os.getenv("OPENAI_MODEL_FAST", "gpt-4o-mini"),
                         max_tokens=2500)

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")

        output = f"""# File Organization System: {folder_type}
**OS:** {os_type}
**File Types:** {file_types}
**Generated:** {_dt.now().strftime('%Y-%m-%d %H:%M')}

---

{result}

---
*Generated by WheellsVerse File Organizer Bot*
"""
        path = self.save_output(output, f"fileorg_{folder_type}_{ts}.md", ext="md")
        self.logger.info(f"File organization system saved → {path}")
        return {"file": str(path), "folder_type": folder_type, "os": os_type}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="File Organization System Builder")
    parser.add_argument("--type", type=str, default="business",
                        choices=list(FOLDER_TYPES.keys()))
    parser.add_argument("--os", type=str, default="mac",
                        choices=OS_TYPES)
    parser.add_argument("--chaos", type=str, default=None)
    parser.add_argument("--filetypes", type=str, default=None)
    args = parser.parse_args()
    bot = FileOrganizerBot()
    result = bot.execute(folder_type=args.type, os_type=args.os,
                         current_chaos=args.chaos, file_types=args.filetypes)
    print(f"\n✅ File Organization System: {result['file']}")
