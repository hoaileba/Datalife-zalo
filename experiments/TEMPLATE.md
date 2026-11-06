# Template một thực nghiệm

Copy bốn file dưới vào `experiments/EXP-<YYYYMMDD>-<NN>-<slug>/`, tạo `code/`, `logs/`, `out/` rỗng.

## manifest.json

```json
{
  "id": "EXP-20261029-01-<slug>",
  "opened_at": "2026-10-29T00:00:00+07:00",
  "goal": "<một câu>",
  "hypothesis": null,
  "metrics": ["score", "accuracy", "coverage"],
  "dataset": {"path": "train/split/test_questions.jsonl", "n": 450},
  "phase": "P0",
  "model": null,
  "seed": 42,
  "parent": null,
  "status": "open"
}
```

## RULES.md

```
# Luật áp dụng cho <id>

## Đã code hoá
| Luật rulebook | File |
| --- | --- |

## Cố ý chưa làm
| Luật | Vì sao hoãn |
| --- | --- |

## Quyết định tạm, chưa thành ADR
| Quyết định | Lý do | Cần ADR không |
| --- | --- | --- |
```

## STEPS.md

```
# Nhật ký <id>

## <ISO 8601> — bước 1/<N>
Đã làm:
Kết quả:
Bước tiếp:
```

## RESULT.md

```
# Kết quả <id>

## Số đo
| Metric | Giá trị |
| --- | --- |
| score | |
| accuracy | |
| coverage | |

## So với parent
| Metric | parent | lần này | lệch |
| --- | --- | --- | --- |

## Milestone
Milestone của phase: <trích từ docs/02>
Đạt: có / không

## Kết luận
Giả thuyết: đúng / sai / không kết luận được

## Việc còn treo
```
