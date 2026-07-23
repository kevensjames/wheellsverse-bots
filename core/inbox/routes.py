"""Second Brain Inbox - Daily Life Organizer AI
Integrated into WheellsVerse core API.
"""
import os
import re
import json
import logging
from datetime import datetime
from enum import Enum
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
import aiosqlite
import openai

logger = logging.getLogger("inbox")

router = APIRouter()

openai_client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

DB_PATH = os.getenv("INBOX_DB_PATH", "/tmp/second_brain.db")


class ItemType(str, Enum):
    TASK = "task"
    IDEA = "idea"
    REMINDER = "reminder"
    EVENT = "event"
    NOTE = "note"


class Item(BaseModel):
    id: Optional[int] = None
    content: str
    item_type: ItemType
    parsed_from: str
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    due_date: Optional[str] = None
    completed: bool = False


class BrainDumpRequest(BaseModel):
    text: str


class BrainDumpResponse(BaseModel):
    items: list[Item]
    digest: Optional[str] = None


class DailyDigestResponse(BaseModel):
    date: str
    tasks: list[Item]
    reminders: list[Item]
    ideas: list[Item]


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                item_type TEXT NOT NULL,
                parsed_from TEXT NOT NULL,
                created_at TEXT NOT NULL,
                due_date TEXT,
                completed INTEGER DEFAULT 0
            )
        """)
        await db.commit()


async def classify_and_parse(text: str) -> list[Item]:
    system_prompt = """You are a smart inbox classifier. Parse the user's brain dump and extract each actionable item.

For each item, classify it as:
- task: Something that needs to be done
- idea: Creative thought or concept
- reminder: Something to remember or check
- event: Something scheduled in time
- note: General information

Return a JSON array with this structure:
[{"content": "the specific thing", "item_type": "task|idea|reminder|event|note", "due_date": "2024-01-15 14:00 or null"}]

Rules:
1. Split comma-separated items into separate entries
2. Detect time/date expressions (tomorrow, at 6pm, next week, etc.)
3. Keep content concise and actionable
4. If no clear type, default to "note"
5. Return empty array if nothing to parse"""

    try:
        from core.llm_client import safe_openai_call
        response = safe_openai_call(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            model="gpt-4o-mini",
            temperature=0.3,
            max_tokens=1000,
            bot_name="inbox",
        )
        
        content = response.choices[0].message.content
        json_match = re.search(r'\[.*\]', content, re.DOTALL)
        
        if json_match:
            parsed = json.loads(json_match.group())
            items = []
            
            for p in parsed:
                due_date = None
                if p.get("due_date"):
                    try:
                        due = datetime.fromisoformat(p["due_date"].replace("Z", "+00:00"))
                        due_date = due.isoformat()
                    except Exception as e:
                        logger.debug("Unparseable due_date %r — leaving unset: %s", p.get("due_date"), e)
                
                item = Item(
                    content=p["content"],
                    item_type=ItemType(p.get("item_type", "note")),
                    parsed_from=text,
                    due_date=due_date,
                )
                items.append(item)
            
            return items
        return []
    
    except Exception as e:
        print(f"Classification error: {e}")
        return [Item(content=text, item_type=ItemType.NOTE, parsed_from=text)]


async def generate_digest(items: list[Item]) -> str:
    tasks = [i for i in items if i.item_type == ItemType.TASK]
    reminders = [i for i in items if i.item_type == ItemType.REMINDER]
    ideas = [i for i in items if i.item_type == ItemType.IDEA]
    
    parts = []
    if tasks:
        parts.append(f"{len(tasks)} tasks")
    if reminders:
        parts.append(f"{len(reminders)} reminders")
    if ideas:
        parts.append(f"{len(ideas)} ideas")
    
    if not parts:
        return "Your mind is clear. No pending items."
    
    return " | ".join(parts)


@router.on_event("startup")
async def startup():
    await init_db()


@router.post("/brain-dump", response_model=BrainDumpResponse)
async def brain_dump(req: BrainDumpRequest):
    items = await classify_and_parse(req.text)
    
    async with aiosqlite.connect(DB_PATH) as db:
        for item in items:
            cursor = await db.execute(
                """INSERT INTO items (content, item_type, parsed_from, created_at, due_date, completed)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (item.content, item.item_type.value, item.parsed_from, item.created_at, item.due_date, 0)
            )
            item.id = cursor.lastrowid
        await db.commit()
    
    digest = await generate_digest(items)
    return BrainDumpResponse(items=items, digest=digest)


@router.get("/digest", response_model=DailyDigestResponse)
async def daily_digest(date: Optional[str] = None):
    target_date = date or datetime.utcnow().date().isoformat()
    
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT * FROM items 
               WHERE date(created_at) = date(?)
               ORDER BY due_date, created_at""",
            (target_date,)
        )
        rows = await cursor.fetchall()
    
    items = [Item(**dict(row)) for row in rows]
    
    tasks = [i for i in items if i.item_type == ItemType.TASK]
    reminders = [i for i in items if i.item_type == ItemType.REMINDER]
    ideas = [i for i in items if i.item_type == ItemType.IDEA]
    
    return DailyDigestResponse(
        date=target_date,
        tasks=tasks,
        reminders=reminders,
        ideas=ideas,
    )


@router.get("/search")
async def search_items(q: str, limit: int = 10):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT * FROM items 
               WHERE content LIKE ? OR parsed_from LIKE ?
               ORDER BY created_at DESC LIMIT ?""",
            (f"%{q}%", f"%{q}%", limit)
        )
        rows = await cursor.fetchall()
    
    return [Item(**dict(row)) for row in rows]


@router.post("/items/{item_id}/complete")
async def complete_item(item_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE items SET completed = 1 WHERE id = ?",
            (item_id,)
        )
        await db.commit()
    return {"status": "ok"}


@router.get("/items")
async def list_items(
    item_type: Optional[ItemType] = None,
    completed: Optional[bool] = None,
    limit: int = 50,
):
    query = "SELECT * FROM items WHERE 1=1"
    params = []
    
    if item_type:
        query += " AND item_type = ?"
        params.append(item_type.value)
    
    if completed is not None:
        query += " AND completed = ?"
        params.append(1 if completed else 0)
    
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
    
    return [Item(**dict(row)) for row in rows]


rt = router