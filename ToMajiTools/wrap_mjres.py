#!/usr/bin/env python3
"""
wrap_mjres.py — Безопасный автоперенос длинных строк для Majiro (.mjres)
Адаптирован для «終わる世界とバースデイ» (Owari no Sekai to Birthday).

Движок Majiro имеет ограничение на максимальную длину строки (рекомендуется до 54-58 символов,
абсолютный лимит 64). Скрипт разбивает длинные строки по пробелам между словами,
добавляя японский отступ (\\u3000) для диалогов.

Использование:
  python wrap_mjres.py [scenario_dir] [--max-len 54]
"""

import os
import sys
import glob
import csv
import io
import argparse

DEFAULT_MAX_LINE_LEN = 64


def wrap_block(text: str, max_len: int) -> list:
    """Разбивает текст на части не длиннее max_len символов, разрезая по пробелам."""
    lines = []
    remaining = text
    while len(remaining) > max_len:
        pos = remaining.rfind(" ", 0, max_len)
        if pos <= 0:
            # Нет пробела — режем жёстко по лимиту
            lines.append(remaining[:max_len])
            remaining = remaining[max_len:]
        else:
            lines.append(remaining[:pos])
            remaining = remaining[pos + 1:]
    if remaining:
        lines.append(remaining)
    return lines


def wrap_text_entry(val: str, max_len: int = DEFAULT_MAX_LINE_LEN) -> str:
    """
    Если строка длинная, вставляем переносы \\n с отступом \\u3000 для диалогов,
    либо \\n для нарратива. Поддерживает несколько переносов (до 3 строк).
    """
    if "\n" in val or "\r" in val:
        return val

    # Диалог персонажа вида: Имя「текст」
    open_b = val.find("「")
    close_b = val.rfind("」")

    if open_b != -1 and close_b > open_b:
        prefix = val[:open_b + 1]
        inner = val[open_b + 1:close_b]
        suffix = val[close_b:]

        if len(inner) > max_len:
            parts = wrap_block(inner, max_len)
            inner = ("\n\u3000").join(parts)
            return prefix + inner + suffix
        return val

    # Нарратив (без кавычек)
    if len(val) > max_len:
        parts = wrap_block(val, max_len)
        return "\n".join(parts)

    return val


def process_file_exact(file_path: str, max_len: int = DEFAULT_MAX_LINE_LEN):
    """
    Читает и перезаписывает .mjres в строгом бинарном формате Majiro:
    - Разделитель строк CSV: CRLF (0x0D 0x0A)
    - Перенос строки внутри полей: строго одиночный LF (0x0A)
    """
    with open(file_path, "rb") as f:
        raw_data = f.read()

    text = raw_data.decode("utf-8", errors="replace")

    reader = csv.reader(io.StringIO(text))
    rows = []
    header = None

    for i, row in enumerate(reader):
        if i == 0 and len(row) >= 2 and row[0].lower() == "key":
            header = row
            continue
        if len(row) < 2:
            continue
        key = row[0]
        val = row[1].replace(r"\n", "\n")
        new_val = wrap_text_entry(val, max_len)
        rows.append((key, new_val))

    out_buf = io.BytesIO()
    if header:
        out_buf.write(f"{header[0]},{header[1]}\r\n".encode("utf-8"))
    else:
        out_buf.write(b"Key,Value\r\n")

    for key, val in rows:
        if "," in val or '"' in val or "\n" in val:
            escaped = val.replace('"', '""')
            line_str = f'{key},"{escaped}"\r\n'
        else:
            line_str = f"{key},{val}\r\n"
        out_buf.write(line_str.encode("utf-8"))

    with open(file_path, "wb") as f:
        f.write(out_buf.getvalue())


def main():
    parser = argparse.ArgumentParser(description="Автоматический перенос строк в .mjres")
    parser.add_argument("target_dir", nargs="?", default="scenario", help="Папка с .mjres файлами")
    parser.add_argument("--max-len", type=int, default=DEFAULT_MAX_LINE_LEN, help="Максимальная длина строки")

    args = parser.parse_args()

    files = sorted(glob.glob(os.path.join(args.target_dir, "*.mjres")))
    if not files:
        print(f"Не найдено .mjres файлов в {args.target_dir}")
        return

    print(f"Применение автопереноса строк (макс. {args.max_len} симв.) к {len(files)} файлам...")
    for f in files:
        process_file_exact(f, args.max_len)
    print("Автоперенос строк завершён успешно.")


if __name__ == "__main__":
    main()
