from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import openai
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from datamate_agent.agent import build_system, read_data

DATASET = ROOT / "public_test"
PROMPT = "v3"
MODEL = "google/gemma-3-12b-it"
QUESTION_ID = "q_78a7454fde5d"
TABLE_FILE = "BanHang_TongHop_2025.xlsx"
TABLE_ROWS = 10

load_dotenv(ROOT / ".env")

rows = map(json.loads, (DATASET / "questions.jsonl").read_text(encoding="utf-8").splitlines())
question = next(row for row in rows if row["id"] == QUESTION_ID)
shop = question["business_id"]

system = build_system(dataset=DATASET, shop=shop, prompt=PROMPT, language="vi")
table = read_data(DATASET / "data" / shop, file_path=TABLE_FILE, num_row=TABLE_ROWS)
user = f"Hôm nay là {question['as_of_date']}.\nCâu hỏi: {question['question']}"


print(f"{system}\n\n# Bảng {TABLE_FILE}\n\n{table}")

client = openai.OpenAI(base_url=os.environ["OPENROUTER_BASE_URL"], api_key=os.environ["OPENROUTER_KEY"], timeout=120, max_retries=2)
response = client.chat.completions.create(
    model=MODEL,
    messages=[
        {"role": "system", "content": f"{system}\n\n# Bảng {TABLE_FILE}\n\n{table}"},
        {"role": "user", "content": user},
    ],
    temperature=0,
)

print(f"USER:\n{user}\n")
print(f"TABLE:\n{table}\n")
print(f"REPLY:\n{response.choices[0].message.content}\n")
print(f"finish_reason: {response.choices[0].finish_reason} | usage: {response.usage}")
