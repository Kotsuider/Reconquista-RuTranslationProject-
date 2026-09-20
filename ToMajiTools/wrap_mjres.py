import os
import sys
import glob
import re

MAX_LINE_LEN = 54

def wrap_text_entry(val: str, max_len: int = MAX_LINE_LEN) -> str:
    """
    Если строка длинная, вставляем одиночный \n и невидимый отступ \u3000
    ровно так же, как устроено в оригинале st/*.mjres.
    """
    if "\n" in val or "\r" in val:
        return val

    # Учитываем имя персонажа Имя「текст」
    open_b = val.find("「")
    close_b = val.rfind("」")

    if open_b != -1 and close_b > open_b:
        prefix = val[:open_b + 1]
        inner = val[open_b + 1:close_b]
        suffix = val[close_b:]

        limit = max_len - len(prefix)
        if limit < 20:
            limit = 20

        if len(inner) > limit:
            pos = inner.rfind(" ", 0, limit)
            if pos > 0:
                # В оригинале после \n идет полноширинный отступ \u3000
                inner = inner[:pos] + "\n\u3000" + inner[pos + 1:]
                return prefix + inner + suffix
        return val

    # Нарратив (без кавычек)
    if len(val) > max_len:
        pos = val.rfind(" ", 0, max_len)
        if pos > 0:
            return val[:pos] + "\n" + val[pos + 1:]

    return val


def process_file_exact(file_path: str):
    """
    Читает и пишет файл в ТОЧНОСТИ по бинарному формату оригинала st:
    - Разделитель строк CSV: CRLF (0x0D 0x0A)
    - Перенос строки внутри кавычек: строго одиночный LF (0x0A)
    - Никаких \r внутри полей!
    """
    with open(file_path, "rb") as f:
        raw_data = f.read()

    text = raw_data.decode("utf-8", errors="replace")
    
    # Парсим CSV с сохранением многострочности
    import csv, io
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
        val = row[1]
        # Очищаем от случайных литералов \n из предыдущей попытки
        val = val.replace(r"\n", "\n")
        new_val = wrap_text_entry(val)
        rows.append((key, new_val))

    # Записываем в БИНАРНОМ режиме (wb), чтобы избежать нормализации Windows CRLF
    out_buf = io.BytesIO()
    if header:
        out_buf.write(f"{header[0]},{header[1]}\r\n".encode("utf-8"))
    else:
        out_buf.write(b"Key,Value\r\n")

    for key, val in rows:
        # Если значение содержит запятую, кавычки или LF — оборачиваем в кавычки
        if "," in val or '"' in val or "\n" in val:
            escaped = val.replace('"', '""')
            line_str = f'{key},"{escaped}"\r\n'
        else:
            line_str = f'{key},{val}\r\n'
        out_buf.write(line_str.encode("utf-8"))

    with open(file_path, "wb") as f:
        f.write(out_buf.getvalue())

    print(f"  {os.path.basename(file_path)}: written with exact st byte format")


def main():
    target_dir = "scenario"
    if len(sys.argv) > 1:
        target_dir = sys.argv[1]

    files = glob.glob(os.path.join(target_dir, "*.mjres"))
    print(f"=== Applying exact st newline format to {len(files)} files ===")
    for f in sorted(files):
        process_file_exact(f)
    print("=== Done ===")


if __name__ == "__main__":
    main()
