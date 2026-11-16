#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_reko_fonts_and_ui.py — Патч шрифтов и системных сообщений для Rekonquista.

1. Замена шрифтов на Noto Serif JP (кроме 小カレンダーフォント):
   - Замена строковых литералов "ＭＳ ゴシック", "MS UI Gothic", "ＭＳ 明朝" на "Noto Serif JP".
   - Разблокировка выбора системных шрифтов в окне настроек config.mjil (ldc.i 2).
   - Установка начального шрифта по умолчанию на "Noto Serif JP" в load_sysdata.mjil.

2. Перевод системных окон, диалогов и уведомлений (MSG_BOX / dialog):
   - Окна подтверждения сейва/лоада/выхода.
   - Системные уведомления о сохранении.
   - Вопросы переключения точки зрения (sightchange.mjil).
   - Подписи в окне настроек config.mjil.
"""

import os
import sys
import glob
import re

TARGET_FONT = "Noto Serif JP"

LEGACY_FONTS = (
    "Georgia",
    "Noto Sans Mono CJK JP",
    "NotoSansMonoCJKjp-VF",
)

FONT_REPLACEMENTS = {
    **{f'"{font}"': f'"{TARGET_FONT}"' for font in LEGACY_FONTS},
    '"ＭＳ ゴシック"': f'"{TARGET_FONT}"',
    '"MS UI Gothic"': f'"{TARGET_FONT}"',
    '"ＭＳ 明朝"': f'"{TARGET_FONT}"',
}

UI_STRING_REPLACEMENTS = {
    # Диалоги подтверждения и выхода (MSG_BOX)
    '"クイックセーブします。よろしいですか？"': '"Сохранить в быстрый слот?"',
    '"クイックロードします。よろしいですか？"': '"Загрузить быстрый сейв?"',
    '"データをロードします。よろしいですか？"': '"Загрузить сохранённые данные?"',
    '"上書きセーブします。よろしいですか？"': '"Перезаписать сохранение?"',
    '"タイトルに戻ります。よろしいですか？"': '"Вернуться в главное меню?"',
    '"ゲームを終了します。よろしいですか？"': '"Выйти из игры?"',
    '"終了します。よろしいですか？"': '"Выйти из игры?"',
    '"Sub Episode を終了しますか？"': '"Завершить дополнительный эпизод?"',

    # Системные сообщения и всплывающие плашки
    '"セーブできません"': '"Сохранение невозможно"',
    '"クイックセーブしました"': '"Быстрое сохранение выполнено"',
    '"セーブしました"': '"Сохранение выполнено"',
    '"】を保存します"': '"】 будет сохранено"',
    '"新規更新 はありません"': '"Новых обновлений нет"',
    '"Sub Episode はありません"': '"Дополнительных эпизодов нет"',
    '"年表が更新されました"': '"Хроника событий обновлена"',
    '" の Sub Episode が追加されました"': '": добавлен дополнительный эпизод"',
    '"現在は再生できません"': '"В данный момент воспроизведение невозможно"',
    '"まだ見ることは出来ません"': '"Пока недоступно для просмотра"',

    # Переключение точки зрения (sightchange.mjil)
    '"視点を選択してください"': '"Выберите точку зрения"',
    '"視点を槙野慶吾に切り替えますか？"': '"Переключить вид на Кэйго Макино?"',
    '"視点を三沢信哉に切り替えますか？"': '"Переключить вид на Синъю Мисаву?"',

    # Окно конфигурации (config.mjil)
    '"文字速度 : "': '"Скорость текста: "',
    '" / 音量 : "': '" / Громкость: "',
}


def patch_fonts_in_file(filepath: str) -> int:
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    modified = False
    count = 0

    # 1. Замена литералов шрифтов (НЕ трогая "小カレンダーフォント")
    for old_font, new_font in FONT_REPLACEMENTS.items():
        if old_font in content:
            c = content.count(old_font)
            content = content.replace(old_font, new_font)
            count += c
            modified = True

    # 2. Разблокировка выбора всех шрифтов в config.mjil
    if os.path.basename(filepath) == "config.mjil":
        old_dialog_pattern = """  line          #793
  ld            persistent int $b5788291  ; #confont_isproportional@SYSTEM
  ld            persistent string $391053c5  ; #confont_name$@SYSTEM
  syscall       $font_dialog$ (2)"""

        new_dialog_pattern = """  line          #793
  ldc.i         2
  ld            persistent string $391053c5  ; #confont_name$@SYSTEM
  syscall       $font_dialog$ (2)"""

        if old_dialog_pattern in content:
            content = content.replace(old_dialog_pattern, new_dialog_pattern, 1)
            modified = True
            print("  [OK] config.mjil: patched font_dialog to unlock all Windows fonts.")

    if os.path.basename(filepath) == "menu.mjil":
        # The click animation has its own font setup before each redraw.
        choice_font = re.compile(
            r"  ld +persistent int \$(?:b5788291|bc034238)[^\n]*\n"
            r"(  ld +(?:local int \$2ddacb97 9|savefile int \$f8d38ee1) *)\n"
            r"  ldc.i +2\n  div.i *\n\1\n"
            r"  ld +persistent string \$(?:391053c5|04f9eb39)[^\n]*\n"
            r"  syscallp +\$fontout_font \(4\)"
        )

        def choice_metrics(match):
            height = match[1].rstrip()
            return "\n".join((
                "  ldc.i         1",
                height,
                "  ldc.i         4",
                "  add.i",
                "  ldc.i         2",
                "  mul.i",
                "  ldc.i         3",
                "  div.i",
                height,
                "  ldc.i         4",
                "  add.i",
                f'  ldstr         "{TARGET_FONT}"',
                "  syscallp      $fontout_font (4)",
            ))

        content, choice_count = choice_font.subn(choice_metrics, content)
        count += choice_count
        modified |= bool(choice_count)

    if os.path.basename(filepath) == "message_box.mjil":
        old_metrics = f'  ldc.i         12\n  ldc.i         24\n  ldstr         "{TARGET_FONT}"'
        new_metrics = f'  ldc.i         18\n  ldc.i         28\n  ldstr         "{TARGET_FONT}"'
        if old_metrics in content:
            content = content.replace(old_metrics, new_metrics)
            modified = True

    if os.path.basename(filepath) == "loadsave.mjil":
        # The thumbnail caption and the date/time share the original font setup.
        slot_font = re.compile(
            r"(  line +#226\n)"
            r"  ld +persistent int \$c53f69b4 *\n"
            r"(  ld +persistent int \$5cc62704 *\n"
            r"  ldc.i +2\n  div.i *\n"
            r"  ld +persistent int \$5cc62704 *\n)"
            r"  ld +persistent string \$ea213e78 *\n"
            r"  syscallp +\$fontout_font \(4\)"
        )
        date_position = "  line          #234\n"
        match = slot_font.search(content)
        if match and date_position in content:
            caption_font = (
                match[1] + "  ldc.i         1\n  ldc.i         17\n  ldc.i         25\n"
                + f'  ldstr         "{TARGET_FONT}"\n'
                + "  syscallp      $fontout_font (4)"
            )
            content = (
                content[:match.start()] + caption_font + content[match.end():]
            ).replace(date_position, match[0][len(match[1]):] + "\n" + date_position, 1)
            modified = True
            count += 1

    if os.path.basename(filepath) == "start.mjil":
        # Cover the translated Extra label's glow when the item is locked.
        extra_mask = re.compile(
            r"( block_078a:\n)"
            r"  ldc.i +450\n  ldc.i +565\n"
            r"(  ld +savefile int \$9c805929[^\n]*\n)"
            r"  ldc.i +41\n  ldc.i +143\n  ldc.i +450\n  ldc.i +565\n"
            r"(  ld +local int \$babb1448 0\n  syscallp +\$grp_copy \(8\))"
        )
        content, mask_count = extra_mask.subn(
            r"\g<1>  ldc.i         448\n  ldc.i         561\n\g<2>"
            r"  ldc.i         46\n  ldc.i         168\n"
            r"  ldc.i         448\n  ldc.i         561\n\g<3>",
            content,
        )
        modified |= bool(mask_count)

    if os.path.basename(filepath) == "sightchange.mjil":
        # The widest localized label ends at x=612 on the 800px canvas.
        view_crop = re.compile(
            r"(  ldc.i +93\n  ldc.i +)275"
            r'(\n  ldc.i +384\n  ldc.i +292\n  ldstr +"[^"]+_view"\n'
            r"  syscall +\$sprite_create_file_ext \(5\))"
        )
        content, view_count = view_crop.subn(r"\g<1>328\g<2>", content)
        modified |= bool(view_count)

    if os.path.basename(filepath) == "chronicle.mjil":
        chronicle_font = re.compile(
            r'  ldc.i +0\n  ldc.i +(?:7|8)\n  ldc.i +(?:14|16)\n'
            rf'(  ldstr +"{TARGET_FONT}"\n  syscallp +\$fontout_font \(4\))'
        )
        content, chronicle_count = chronicle_font.subn(
            r"  ldc.i         1\n  ldc.i         10\n  ldc.i         20\n\g<1>",
            content,
        )
        modified |= bool(chronicle_count)

    # 3. Установка дефолтного системного шрифта в load_sysdata.mjil (если пустой)
    if os.path.basename(filepath) == "load_sysdata.mjil":
        old_load_pattern = """ block_00c0:
  line          #25
  ld            local int $a7934f1c 0
  syscall       $file_read$ (1)
  st.s          persistent string $391053c5  ; #confont_name$@SYSTEM
  pop          
  line          #26
  br            @block_0106"""

        new_load_pattern = f""" block_00c0:
  line          #25
  ld            local int $a7934f1c 0
  syscallp      $file_read$ (1)
  ldstr         "{TARGET_FONT}"
  st.s          persistent string $391053c5  ; #confont_name$@SYSTEM
  pop          
  line          #26
  br            @block_0106"""

        if old_load_pattern in content:
            content = content.replace(old_load_pattern, new_load_pattern, 1)
            modified = True
            print(f"  [OK] load_sysdata.mjil: default confont_name initialized to '{TARGET_FONT}'.")

        # A previous test font may already be in persistent system settings.
        saved_font_check = re.compile(
            r'  ldstr +""\n  ceq.s *\n  brfalse +@block_00ec'
        )
        if saved_font_check.search(content):
            checks = "".join(
                f'\n  ld            persistent string $391053c5'
                f'\n  ldstr         "{font}"\n  ceq.s\n  or'
                for font in LEGACY_FONTS
            )
            content = saved_font_check.sub(
                '  ldstr         ""\n  ceq.s' + checks + '\n  brfalse       @block_00ec',
                content,
                count=1,
            )
            modified = True

    if modified:
        with open(filepath, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)

    return count


def patch_ui_strings_in_file(filepath: str) -> int:
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    modified = False
    count = 0

    for old_s, new_s in UI_STRING_REPLACEMENTS.items():
        pattern = f'ldstr         {old_s}'
        replacement = f'ldstr         {new_s}'
        if pattern in content:
            c = content.count(pattern)
            content = content.replace(pattern, replacement)
            count += c
            modified = True

    if modified:
        with open(filepath, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)

    return count


def main():
    scenario_dir = sys.argv[1] if len(sys.argv) > 1 else "scenario"
    files = glob.glob(os.path.join(scenario_dir, "*.mjil"))
    
    total_fonts = 0
    total_ui = 0
    for f in files:
        fname = os.path.basename(f)
        cf = patch_fonts_in_file(f)
        cu = patch_ui_strings_in_file(f)
        total_fonts += cf
        total_ui += cu
        if cf > 0 or cu > 0:
            print(f"  [OK] {fname}: {cf} font literals replaced, {cu} UI strings translated.")

    print(f"\n[OK] Font patching complete: {total_fonts} occurrences updated to '{TARGET_FONT}'.")
    print(f"[OK] UI strings translation complete: {total_ui} occurrences translated.")


if __name__ == "__main__":
    main()
