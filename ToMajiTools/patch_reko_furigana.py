#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_reko_furigana.py — Отключение вывода японской фуриганы и боутэн в Rekonquista.

1. yazlib.mjil:
   - func $3198fd01(base_str, furi_str): отключает наложение фуриганы сверху,
     выводит только базовое слово base_str (через ctrl "d") и завершает функцию.
   - func $2f93f26a(base_str): отключает наложение точек ударения (боутэн),
     выводит только базовое слово base_str (через ctrl "d") и завершает функцию.

2. Сюжетные файлы сценариев (*.mjil):
   - Нейтрализует 22 инлайн-вызова фуриганы через ctrl "o" / ctrl "r",
     чтобы обе переведённые фразы (фуригана и база) выводились последовательно,
     не наезжая друг на друга.
"""

import os
import sys
import glob
import json
import re

def patch_yazlib(filepath: str) -> bool:
    if not os.path.exists(filepath):
        print(f"Warning: {filepath} not found.")
        return False

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    modified = False

    # 1. Патчим func $3198fd01 (вывод фуриганы)
    # Аргументы: local string $5ce2ee99 -2 (base), local string $6e34ea44 -3 (furi)
    target_furi_func = """func $3198fd01(string, string) {
 entry:
  line          #1404
  argcheck      [string, string]
  alloca        [int, int, string, string, int, int, int, int, int]"""

    repl_furi_func = """func $3198fd01(string, string) {
 entry:
  line          #1404
  argcheck      [string, string]
  alloca        [int, int, string, string, int, int, int, int, int]
  ld            local string $5ce2ee99 -2
  ctrl          "d"
  proc          
  ldc.i         0
  ret           """

    if target_furi_func in content:
        content = content.replace(target_furi_func, repl_furi_func, 1)
        modified = True
        print("[OK] Patched yazlib.mjil func $3198fd01 (ruby disabled, base output only).")
    else:
        print("Warning: func $3198fd01 pattern not found in yazlib.mjil.")

    # 2. Патчим func $2f93f26a (вывод боутэн / точек ударения)
    # Аргумент: local string $c674aa5d -2 (base)
    target_bouten_func = """func $2f93f26a(string) {
 entry:
  line          #1382
  argcheck      [string]
  alloca        [int, int, string]"""

    repl_bouten_func = """func $2f93f26a(string) {
 entry:
  line          #1382
  argcheck      [string]
  alloca        [int, int, string]
  ld            local string $c674aa5d -2
  ctrl          "d"
  proc          
  ldc.i         0
  ret           """

    if target_bouten_func in content:
        content = content.replace(target_bouten_func, repl_bouten_func, 1)
        modified = True
        print("[OK] Patched yazlib.mjil func $2f93f26a (bouten dots disabled, base output only).")
    else:
        print("Warning: func $2f93f26a pattern not found in yazlib.mjil.")

    if modified:
        with open(filepath, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        return True
    return False


def patch_inline_rubies(scenario_dir: str) -> int:
    """
    Нейтрализует 22 инлайн-вызова фуриганы в сценариях.
    Убирает сдвиг назад (ctrl "o" с отрицательными координатами)
    и ctrl "r", разделяющий верхний и нижний слои, чтобы обе переведённые фразы
    выводились последовательно нормальным текстом.
    """
    patched_files = 0
    total_rubies = 0

    files = glob.glob(os.path.join(scenario_dir, "*.mjil"))
    for filepath in files:
        fname = os.path.basename(filepath)
        if fname == "yazlib.mjil":
            continue

        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        if 'ctrl          "r"' not in content:
            continue

        # Заменяем ctrl "r" на ldc.i 0 / pop, чтобы не переключать слой наложения
        new_content, n_r = re.subn(r'ctrl\s+"r"', 'ldc.i         0\n  pop', content)
        
        # Убираем отрицательный сдвиг курсора перед выводом фуриганы:
        new_content, n_o = re.subn(
            r'ldc\.i\s+\d+\s*\n\s*ldc\.i\s+\d+\s*\n\s*neg\.i\s*\n\s*ctrl\s+"o"',
            'ldc.i         0\n  ldc.i         0\n  ctrl          "o"',
            new_content
        )

        if n_r > 0:
            with open(filepath, "w", encoding="utf-8", newline="\n") as f:
                f.write(new_content)
            patched_files += 1
            total_rubies += n_r
            print(f"  [OK] Patched inline ruby in {fname} ({n_r} occurrences)")

    print(f"[OK] Inline rubies patched: {total_rubies} occurrences across {patched_files} files.")
    return total_rubies


def patch_prologue_insertions(scenario_dir: str) -> None:
    path = os.path.join(scenario_dir, "00_レコンキスタ_start_2.mjil")
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as source:
        content = source.read()
    # L2041 and L2042 already translate the verb. Keep a word separator.
    content = re.sub(
        r'  ldstr +"殺そう"\n(?=  callp +\$2f93f26a \(1\)\n  text +%\{L2042\})',
        '  ldstr         " "\n',
        content,
    )
    # The ordinal now appears in L2061 itself.
    content = re.sub(
        r'  ldstr +"みたび"\n  ldstr +"三度"\n  callp +\$3198fd01 \(2\)\n'
        r'(?=  text +%\{L2061\})',
        '',
        content,
    )
    with open(path, "w", encoding="utf-8", newline="\n") as target:
        target.write(content)


def apply_insertion_overrides(scenario_dir: str) -> None:
    manifest = os.path.join(os.path.dirname(__file__), "japanese_insertion_overrides.json")
    with open(manifest, encoding="utf-8") as source:
        scripts = json.load(source)

    count = 0
    for name, rules in scripts.items():
        path = os.path.join(scenario_dir, name + ".mjil")
        with open(path, encoding="utf-8") as source:
            content = source.read()
        edits = {}
        for rule in rules:
            block = rule["block"]
            matches = list(re.finditer(r"^" + re.escape(block) + r"$", content, re.MULTILINE))
            occurrence = rule["occurrence"]
            if occurrence >= len(matches):
                raise ValueError(f"{name}: reviewed insertion missing: {block!r}, occurrence {occurrence}")
            start, end = matches[occurrence].span()
            if (start, end) in edits:
                raise ValueError(f"{name}: duplicate insertion override: {block!r}")
            # The full stack operation is removed. Preserve a separator only
            # when adjacent translated fragments would otherwise run together.
            edits[start, end] = '  ldstr         " "\n  ctrl          "d"\n  proc' if rule["separator"] else ""
        for (start, end), replacement in sorted(edits.items(), reverse=True):
            if replacement:
                content = content[:start] + replacement + content[end:]
            else:
                content = content[:start] + content[end + 1:]
        with open(path, "w", encoding="utf-8", newline="\n") as target:
            target.write(content)
        count += len(edits)
    print(f"[OK] Applied {count} reviewed Japanese insertion overrides.")


def main():
    scenario_dir = sys.argv[1] if len(sys.argv) > 1 else "scenario"
    yazlib_path = os.path.join(scenario_dir, "yazlib.mjil")
    patch_yazlib(yazlib_path)
    patch_inline_rubies(scenario_dir)
    patch_prologue_insertions(scenario_dir)
    apply_insertion_overrides(scenario_dir)

if __name__ == "__main__":
    main()
