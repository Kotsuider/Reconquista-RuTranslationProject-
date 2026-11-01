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


def main():
    scenario_dir = sys.argv[1] if len(sys.argv) > 1 else "scenario"
    yazlib_path = os.path.join(scenario_dir, "yazlib.mjil")
    patch_yazlib(yazlib_path)
    patch_inline_rubies(scenario_dir)

if __name__ == "__main__":
    main()
