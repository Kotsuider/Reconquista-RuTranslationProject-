#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Выборы Majiro: таблица для перевода (md) и вставка перевода при сборке.

Выбор в Majiro — вызов функции модуля MENU, а не отдельная инструкция::

    ldstr         "третий вариант"
    ldstr         "второй вариант"
    ldstr         "первый вариант"
    call          $$select_color@MENU (3)     ; арность = число вариантов
    br.case       @block_0eef

Строки кладутся в стек в обратном порядке отображения: последний ``ldstr``
перед вызовом — первый пункт на экране. Тексты выборов лежат инлайн в .mjil
и в .mjres отсутствуют, поэтому обычный пайплайн их не переводит.

Команды::

    python choices_tool.py list  scenario                 # краткий список
    python choices_tool.py gen   scenario -o choices.md   # таблица для перевода
    python choices_tool.py apply choices.md scenario      # вставить перевод
    python choices_tool.py apply choices.md scenario --dry-run
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

CALL_RE = re.compile(
    r"^\s*(?:call|callp)\s+\$\$?(?P<name>\w+)(?:@(?P<module>\w+))?\s+\((?P<argc>\d+)\)")
LDSTR_RE = re.compile(r'^(?P<prefix>\s*ldstr\s+)"(?P<text>(?:[^"\\]|\\.)*)"\s*$')
TEXT_RE = re.compile(r'^\s*text\s+%\{L(?P<key>\d+)\}\s*;\s*"(?P<text>.*)"\s*$')

# функция выбора -> сколько её последних аргументов служебные (не пункты меню)
#   select_color@MENU(opt1..optN)                — Реконкиста
#   select@MENU(opt1..optN)                      — простой вариант
#   57f252db(opt1..optN, id, log_path)           — Owari
SELECT_FUNCS = {
    "select_color": 0,
    "select": 0,
    "57f252db": 2,
}

HEADER = ["ID", "File", "Line", "Slot", "Orig", "TL", "Ref (RU из mjres)", "Notes"]

# те же замены, что делает sanitize_mjres.py: шрифт игры не содержит этих глифов
SANITIZE = {
    "\u00ab": "\u201c",  # « -> “
    "\u00bb": "\u201d",  # » -> ”
    "\u2014": "\u2015",  # — -> ―
    "\u2013": "\u2015",  # – -> ―
    "\u201e": "\u201c",  # „ -> “
    "\u00f3": "o",
}


@dataclass
class Site:
    file: str
    line: int
    argc: int
    options: list[tuple[int, str]] = field(default_factory=list)   # (номер строки, текст)
    context: list[tuple[str, str]] = field(default_factory=list)   # (L-ключ, японский текст)


def read_mjres(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8", newline="") as fh:
            return {row[0]: row[1] for row in csv.reader(fh) if len(row) >= 2 and row[0] != "Key"}
    except (OSError, UnicodeDecodeError, csv.Error):
        return {}


def scan_sites(path: Path, context_depth: int) -> list[Site]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    sites: list[Site] = []
    for i, line in enumerate(lines):
        m = CALL_RE.match(line)
        if not m:
            continue
        meta = SELECT_FUNCS.get(m.group("name"))
        if meta is None:
            continue
        argc = int(m.group("argc"))
        option_count = argc - meta
        if option_count < 1:
            continue

        options: list[tuple[int, str]] = []
        j = i - 1
        while j >= 0 and len(options) < argc:
            mm = LDSTR_RE.match(lines[j])
            if mm:
                options.append((j, mm.group("text")))
            elif lines[j].strip() and not lines[j].strip().startswith("line "):
                break
            j -= 1
        if len(options) != argc:
            continue
        # служебные аргументы стоят в конце вызова, а обход назад даёт их первыми
        options = options[meta:]

        context: list[tuple[str, str]] = []
        j = i - 1
        while j >= 0 and len(context) < context_depth:
            tm = TEXT_RE.match(lines[j])
            if tm:
                context.append((tm.group("key"), tm.group("text")))
            elif CALL_RE.match(lines[j]) or lines[j].startswith("func "):
                break
            j -= 1

        sites.append(Site(
            file=path.name,
            line=i + 1,
            argc=option_count,
            options=options,                   # обход назад уже даёт порядок отображения
            context=list(reversed(context)),   # контекст — в хронологическом порядке
        ))
    return sites


def collect(scenario: Path, context_depth: int) -> list[Site]:
    sites: list[Site] = []
    for path in sorted(scenario.glob("*.mjil")):
        sites.extend(scan_sites(path, context_depth))
    return sites


def sanitize(text: str) -> str:
    for src, dst in SANITIZE.items():
        text = text.replace(src, dst)
    return text


def cell(text: str) -> str:
    """Экранирование для md-таблицы."""
    return text.replace("|", "\\|").replace("\n", " ")


# --------------------------------------------------------------------------
# list
# --------------------------------------------------------------------------


def cmd_list(args) -> int:
    sites = collect(Path(args.scenario), 0)
    total = sum(len(s.options) for s in sites)
    print(f"точек выбора: {len(sites)} в {len({s.file for s in sites})} файлах, "
          f"вариантов: {total}")
    for n, s in enumerate(sites, 1):
        print(f"C{n:03d} {s.file}:{s.line} ({s.argc})")
        for k, (_, text) in enumerate(s.options, 1):
            print(f"     {k}. {text}")
    return 0


# --------------------------------------------------------------------------
# gen
# --------------------------------------------------------------------------


def cmd_gen(args) -> int:
    scenario = Path(args.scenario)
    mjres_dir = Path(args.mjres_dir) if args.mjres_dir else scenario
    sites = collect(scenario, args.context)

    # защита от запуска по уже пропатченному каталогу (scenario вместо st):
    # тогда в таблицу попадут переводы вместо японских оригиналов
    cyrillic = sum(1 for s in sites for _, text in s.options
                   if any("а" <= ch.lower() <= "я" for ch in text))
    if cyrillic:
        print(f"warning: в {cyrillic} пунктах уже кириллица — похоже, каталог "
              f"пропатчен. Генерируйте таблицу по чистым скриптам (st).", file=sys.stderr)
    out: list[str] = [
        f"# Выборы — {scenario.resolve().name}",
        "",
        "Колонка **TL** — перевод пункта меню, её и правит переводчик.",
        "Строки со `Slot = ctx` — контекст (реплики перед выбором) и перевод этих реплик",
        "из `.mjres`; они не вставляются в скрипт, это подсказка.",
        "`Slot = opt1..optN` — пункты меню в порядке отображения (opt1 — верхний).",
        "Пустой TL = пункт останется на японском.",
        "",
        "| " + " | ".join(HEADER) + " |",
        "| " + " | ".join("---" for _ in HEADER) + " |",
    ]

    # уже готовые переводы переносим по паре (файл, оригинал) — устойчиво к сдвигу ID
    carry: dict[tuple[str, str], list[tuple[str, str]]] = {}
    if args.merge:
        for row in read_rows(Path(args.merge)):
            if row.slot.startswith("opt") and row.tl:
                carry.setdefault((row.file, row.orig), []).append((row.tl, row.note))

    carried = 0
    for n, site in enumerate(sites, 1):
        sid = f"C{n:03d}"
        mjres = read_mjres(mjres_dir / (Path(site.file).stem + ".mjres"))
        for key, jp in site.context:
            ru = mjres.get("L" + key, "")
            out.append(f"| {sid} | {cell(site.file)} | {site.line} | ctx | {cell(jp)} "
                       f"|  | {cell(ru)} | контекст |")
        for k, (_, jp) in enumerate(site.options, 1):
            tl = note = ""
            queue = carry.get((site.file, jp))
            if queue:
                tl, note = queue.pop(0)
                carried += 1
            out.append(f"| {sid} | {cell(site.file)} | {site.line} | opt{k} | {cell(jp)} "
                       f"| {tl} |  | {note} |")

    text = "\n".join(out) + "\n"
    Path(args.output).write_text(text, encoding="utf-8", newline="\n")
    total = sum(len(s.options) for s in sites)
    print(f"{args.output}: {len(sites)} точек выбора, {total} вариантов, "
          f"контекст {args.context} реплик")
    if args.merge:
        print(f"перенесено переводов из {args.merge}: {carried}")
    return 0


# --------------------------------------------------------------------------
# apply
# --------------------------------------------------------------------------


def read_table(path: Path) -> dict[str, dict[int, tuple[str, str]]]:
    """{site_id: {option_index: (перевод, оригинал)}}"""
    result: dict[str, dict[int, tuple[str, str]]] = {}
    for row in read_rows(path):
        m = re.fullmatch(r"opt(\d+)", row.slot)
        if not m or not row.tl:
            continue
        result.setdefault(row.sid, {})[int(m.group(1))] = (sanitize(row.tl), row.orig)
    return result


@dataclass
class Row:
    sid: str
    file: str
    slot: str
    orig: str
    tl: str
    note: str


def read_rows(path: Path) -> list[Row]:
    rows: list[Row] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 8 or cells[0] in ("ID", "") or set(cells[0]) <= set("- "):
            continue
        rows.append(Row(sid=cells[0], file=cells[1], slot=cells[3],
                        orig=cells[4], tl=cells[5], note=cells[7]))
    return rows


def cmd_apply(args) -> int:
    table = read_table(Path(args.table))
    if not table:
        print(f"error: в {args.table} нет заполненных переводов", file=sys.stderr)
        return 1

    scenario = Path(args.scenario)
    sites = collect(scenario, 0)
    applied = skipped = already = 0
    warnings: list[str] = []
    touched: dict[str, list[tuple[int, str]]] = {}

    for n, site in enumerate(sites, 1):
        sid = f"C{n:03d}"
        translations = table.get(sid, {})
        for k, (line_index, jp) in enumerate(site.options, 1):
            entry = translations.get(k)
            if not entry:
                continue
            new_text, orig = entry
            if orig and orig != jp and jp != new_text:
                warnings.append(f"{sid} opt{k}: в таблице «{orig}», в скрипте «{jp}» — пропущено")
                skipped += 1
                continue
            if '"' in new_text or "\\" in new_text:
                warnings.append(f"{sid} opt{k}: кавычка/бэкслеш в переводе, пропущено")
                skipped += 1
                continue
            if jp == new_text:
                already += 1
                continue
            touched.setdefault(site.file, []).append(
                (line_index, f'  ldstr         "{new_text}"'))
            applied += 1

    for name, changes in touched.items():
        path = scenario / name
        # newline="" — иначе universal newlines превратит CRLF в LF и файл
        # перезапишется целиком
        with path.open(encoding="utf-8", newline="") as fh:
            lines = fh.read().splitlines(keepends=True)
        for index, new_line in changes:
            old = lines[index]
            ending = old[len(old.rstrip("\r\n")):]
            # сохраняем исходный отступ
            indent = old[: len(old) - len(old.lstrip())]
            lines[index] = indent + new_line.lstrip() + ending
        if not args.dry_run:
            with path.open("w", encoding="utf-8", newline="") as fh:
                fh.write("".join(lines))

    print(f"{'[dry-run] ' if args.dry_run else ''}вставлено переводов: {applied}, "
          f"файлов: {len(touched)}, уже было: {already}")
    for w in warnings:
        print(f"  warning: {w}")
    if skipped:
        print(f"  пропущено: {skipped}")
    return 0


# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Выборы Majiro: таблица и вставка перевода")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="краткий список выборов")
    p.add_argument("scenario")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("gen", help="сгенерировать md-таблицу для перевода")
    p.add_argument("scenario")
    p.add_argument("-o", "--output", default="choices.md")
    p.add_argument("--context", type=int, default=4, help="реплик контекста (по умолчанию 4)")
    p.add_argument("--merge", metavar="OLD.md",
                   help="перенести готовые переводы из прежней таблицы")
    p.add_argument("--mjres-dir", metavar="DIR",
                   help="откуда брать переводы реплик для контекста (по умолчанию — "
                        "каталог скриптов); удобно указать собранный scenario")
    p.set_defaults(func=cmd_gen)

    p = sub.add_parser("apply", help="вставить перевод из md в .mjil")
    p.add_argument("table")
    p.add_argument("scenario")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_apply)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
