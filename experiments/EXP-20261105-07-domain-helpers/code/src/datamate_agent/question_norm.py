from __future__ import annotations

import re

from datamate.norm import fold_key

ABBREVIATIONS = (
    (r"\b(hnay|bua nay|hom ni|bua ni)\b", "hom nay"),
    (r"\bbua qua\b", "hom qua"),
    (r"\bbua\b", "ngay"),
    (r"\b(\d+) (cu|trieu|tr)\b", r"\g<1>000000"),
    (r"\b(mo|chi)\b(?=\s*$)", "nao"),
    (r"\bni\b", "nay"),
    (r"\b(nhut|nhứt)\b", "nhat"),
    (r"\bmik\b", "minh"),
    (r"\bwan\b", "quan"),
    (r"\btrog\b", "trong"),
    (r"\bcko\b", "cho"),
    (r"\bkua\b", "cua"),
    (r"\bkon\b", "con"),
    (r"\bjum\b", "gium"),
    (r"\bth nay\b", "thang nay"),
    (r"\bth truoc\b", "thang truoc"),
    (r"\bth trc\b", "thang truoc"),
    (r"\bdthu\b", "doanh thu"),
    (r"\bdt\b", "doanh thu"),
    (r"\b(bnhiu|bnhieu|bao nhiu|bn|nhiu)\b", "bao nhieu"),
    (r"\b(mi|may)\b", "may"),
    (r"\bhqua\b", "hom qua"),
    (r"\b(dh|ddh)\b", "don"),
    (r"\bdon hang\b", "don"),
    (r"\b(th|thg|t)(?=\s*\d)", "thang "),
    (r"\b(trc|truoc do)\b", "truoc"),
    (r"\b(dc|duoc)\b", "duoc"),
    (r"\b(ko|khong)\b", "khong"),
    (r"\bvs\b", "voi"),
    (r"\bnv\b(?=\s*\d)", "nv"),
    (r"\bsp\b", "san pham"),
    (r"\bmh\b", "mat hang"),
    (r"\bti le\b", "ty le"),
    (r"\bti trong\b", "ty trong"),
)


def _detelex(word: str) -> str:
    if not word.isalpha() or len(word) < 3:
        return word
    out = word
    if out.startswith("dd"):
        out = out[1:]
    out = out.replace("aa", "a").replace("ee", "e").replace("oo", "o").replace("aw", "a").replace("ow", "o").replace("uw", "u")
    if out[-1] in "sfrxj" and len(out) > 2:
        out = out[:-1]
    return out


def normalize(text: str) -> str:
    """Câu hỏi bỏ dấu, sửa telex hỏng, mở từ viết tắt, chỉ dùng để khớp."""
    folded = re.sub(r"[?!.,:;\"'“”]+(?=\s|$)", " ", fold_key(text))
    words = " ".join(_detelex(word) for word in folded.split())
    for pattern, target in ABBREVIATIONS:
        words = re.sub(pattern, target, words)
    return " ".join(words.split())
