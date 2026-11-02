use std::collections::HashMap;
use std::env;
use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};

// Windows API declarations via windows-sys or direct extern
#[link(name = "kernel32")]
extern "system" {
    fn BeginUpdateResourceW(pFileName: *const u16, bDeleteExistingResources: i32) -> *mut std::ffi::c_void;
    fn UpdateResourceW(
        hUpdate: *mut std::ffi::c_void,
        lpType: *const u16,
        lpName: *const u16,
        wLanguage: u16,
        lpData: *const std::ffi::c_void,
        cb: u32,
    ) -> i32;
    fn EndUpdateResourceW(hUpdate: *mut std::ffi::c_void, fDiscard: i32) -> i32;
    fn GetLastError() -> u32;
}

const RT_MENU: usize = 4;

struct PeMenu {
    res_id: u32,
    name: Option<String>,
    lang_id: u16,
    raw_bytes: Vec<u8>,
}

fn parse_pe_menus(exe_bytes: &[u8]) -> Result<Vec<PeMenu>, String> {
    if exe_bytes.len() < 0x40 || &exe_bytes[..2] != b"MZ" {
        return Err("Неверный формат PE (нет сигнатуры MZ)".into());
    }
    let pe_offset = u32::from_le_bytes(exe_bytes[0x3C..0x40].try_into().unwrap()) as usize;
    if exe_bytes.len() < pe_offset + 24 || &exe_bytes[pe_offset..pe_offset + 4] != b"PE\0\0" {
        return Err("Неверная сигнатура PE".into());
    }

    let num_sections = u16::from_le_bytes(exe_bytes[pe_offset + 6..pe_offset + 8].try_into().unwrap()) as usize;
    let opt_header_size = u16::from_le_bytes(exe_bytes[pe_offset + 20..pe_offset + 22].try_into().unwrap()) as usize;
    let opt_header_offset = pe_offset + 24;

    let rsrc_dir_offset = opt_header_offset + 96 + 2 * 8; // DataDirectory[2] = Resource
    if exe_bytes.len() < rsrc_dir_offset + 8 {
        return Err("Слишком короткий файл для заголовка ресурсов".into());
    }
    let rsrc_va = u32::from_le_bytes(exe_bytes[rsrc_dir_offset..rsrc_dir_offset + 4].try_into().unwrap());

    let section_table_offset = opt_header_offset + opt_header_size;
    let mut rsrc_raw: Option<usize> = None;
    let mut rsrc_sec_va: u32 = 0;
    let mut rsrc_sec_raw: usize = 0;

    for i in 0..num_sections {
        let sec_offset = section_table_offset + i * 40;
        if exe_bytes.len() < sec_offset + 40 {
            break;
        }
        let sec_va = u32::from_le_bytes(exe_bytes[sec_offset + 12..sec_offset + 16].try_into().unwrap());
        let sec_raw_size = u32::from_le_bytes(exe_bytes[sec_offset + 16..sec_offset + 20].try_into().unwrap());
        let sec_raw_ptr = u32::from_le_bytes(exe_bytes[sec_offset + 20..sec_offset + 24].try_into().unwrap()) as usize;

        if sec_va <= rsrc_va && rsrc_va < sec_va + sec_raw_size {
            rsrc_raw = Some(sec_raw_ptr + (rsrc_va - sec_va) as usize);
            rsrc_sec_va = sec_va;
            rsrc_sec_raw = sec_raw_ptr;
            break;
        }
    }

    let rsrc_base = rsrc_raw.ok_or("Не найдена секция ресурсов (.rsrc)")?;

    let get_entries = |offset: usize| -> Vec<(u32, Option<String>, bool, usize)> {
        if exe_bytes.len() < offset + 16 {
            return Vec::new();
        }
        let c_names = u16::from_le_bytes(exe_bytes[offset + 12..offset + 14].try_into().unwrap()) as usize;
        let c_ids = u16::from_le_bytes(exe_bytes[offset + 14..offset + 16].try_into().unwrap()) as usize;
        let mut entries = Vec::with_capacity(c_names + c_ids);

        for i in 0..(c_names + c_ids) {
            let entry_offset = offset + 16 + i * 8;
            if exe_bytes.len() < entry_offset + 8 {
                break;
            }
            let id_val = u32::from_le_bytes(exe_bytes[entry_offset..entry_offset + 4].try_into().unwrap());
            let off_val = u32::from_le_bytes(exe_bytes[entry_offset + 4..entry_offset + 8].try_into().unwrap());
            let is_dir = (off_val & 0x8000_0000) != 0;
            let target_off = rsrc_base + (off_val & 0x7FFF_FFFF) as usize;

            let mut name = None;
            if (id_val & 0x8000_0000) != 0 {
                let name_off = rsrc_base + (id_val & 0x7FFF_FFFF) as usize;
                if exe_bytes.len() >= name_off + 2 {
                    let n_len = u16::from_le_bytes(exe_bytes[name_off..name_off + 2].try_into().unwrap()) as usize;
                    if exe_bytes.len() >= name_off + 2 + n_len * 2 {
                        let u16_slice: Vec<u16> = exe_bytes[name_off + 2..name_off + 2 + n_len * 2]
                            .chunks_exact(2)
                            .map(|c| u16::from_le_bytes(c.try_into().unwrap()))
                            .collect();
                        name = String::from_utf16(&u16_slice).ok();
                    }
                }
            }
            entries.append(&mut vec![(id_val, name, is_dir, target_off)]);
        }
        entries
    };

    let mut pe_menus = Vec::new();
    let type_entries = get_entries(rsrc_base);
    for (tid, _, is_dir1, type_off) in type_entries {
        if tid == 4 && is_dir1 {
            // RT_MENU
            let name_entries = get_entries(type_off);
            for (rid, rname, is_dir2, name_off) in name_entries {
                if is_dir2 {
                    let lang_entries = get_entries(name_off);
                    for (lid, _, _, data_entry_off) in lang_entries {
                        if exe_bytes.len() >= data_entry_off + 16 {
                            let data_rva = u32::from_le_bytes(exe_bytes[data_entry_off..data_entry_off + 4].try_into().unwrap());
                            let data_sz = u32::from_le_bytes(exe_bytes[data_entry_off + 4..data_entry_off + 8].try_into().unwrap()) as usize;
                            let file_off = rsrc_sec_raw + (data_rva - rsrc_sec_va) as usize;
                            if exe_bytes.len() >= file_off + data_sz {
                                pe_menus.push(PeMenu {
                                    res_id: rid,
                                    name: rname.clone(),
                                    lang_id: lid as u16,
                                    raw_bytes: exe_bytes[file_off..file_off + data_sz].to_vec(),
                                });
                            }
                        }
                    }
                }
            }
        }
    }

    Ok(pe_menus)
}

struct MenuItem {
    flags: u16,
    id: Option<u16>,
    text: String,
}

fn decode_menu(data: &[u8]) -> Result<Vec<MenuItem>, String> {
    if data.len() < 4 {
        return Err("Слишком короткий заголовок меню".into());
    }
    let ver = u16::from_le_bytes(data[0..2].try_into().unwrap());
    if ver != 0 {
        return Err(format!("Неподдерживаемая версия меню: {}", ver));
    }

    let mut items = Vec::new();
    let mut pos = 4;
    while pos < data.len() {
        if pos + 2 > data.len() {
            break;
        }
        let flags = u16::from_le_bytes(data[pos..pos + 2].try_into().unwrap());
        pos += 2;

        let mut item_id = None;
        if (flags & 0x0010) == 0 {
            // Not MF_POPUP
            if pos + 2 > data.len() {
                break;
            }
            item_id = Some(u16::from_le_bytes(data[pos..pos + 2].try_into().unwrap()));
            pos += 2;
        }

        let mut u16_chars = Vec::new();
        while pos + 2 <= data.len() {
            let ch = u16::from_le_bytes(data[pos..pos + 2].try_into().unwrap());
            pos += 2;
            if ch == 0 {
                break;
            }
            u16_chars.push(ch);
        }

        let text = String::from_utf16_lossy(&u16_chars);
        items.push(MenuItem {
            flags,
            id: item_id,
            text,
        });
    }

    Ok(items)
}

fn encode_menu(items: &[MenuItem]) -> Vec<u8> {
    let mut out = Vec::new();
    out.extend_from_slice(&0u16.to_le_bytes());
    out.extend_from_slice(&0u16.to_le_bytes());

    for item in items {
        out.extend_from_slice(&item.flags.to_le_bytes());
        if (item.flags & 0x0010) == 0 {
            let id = item.id.unwrap_or(0);
            out.extend_from_slice(&id.to_le_bytes());
        }
        for ch in item.text.encode_utf16() {
            out.extend_from_slice(&ch.to_le_bytes());
        }
        out.extend_from_slice(&0u16.to_le_bytes());
    }
    out
}

fn to_wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

fn patch_exe_menu(exe_path: &Path, dict: &HashMap<String, String>) -> Result<usize, String> {
    let mut exe_bytes = Vec::new();
    fs::File::open(exe_path)
        .map_err(|e| format!("Не удалось открыть {}: {}", exe_path.display(), e))?
        .read_to_end(&mut exe_bytes)
        .map_err(|e| format!("Ошибка чтения {}: {}", exe_path.display(), e))?;

    let menus = parse_pe_menus(&exe_bytes)?;
    if menus.is_empty() {
        return Err("В файле не найдено ресурсов меню (RT_MENU)".into());
    }

    // Бэкап
    let bak_path = exe_path.with_extension(format!(
        "{}.bak",
        exe_path.extension().and_then(|s| s.to_str()).unwrap_or("exe")
    ));
    if !bak_path.exists() {
        println!("Создание резервной копии: {}", bak_path.display());
        let _ = fs::copy(exe_path, &bak_path);
    }

    let wide_exe = to_wide(exe_path.to_str().ok_or("Неверный путь к exe")?);
    let h_update = unsafe { BeginUpdateResourceW(wide_exe.as_ptr(), 0) };
    if h_update.is_null() {
        let err = unsafe { GetLastError() };
        return Err(format!("BeginUpdateResourceW завершился с ошибкой: {}", err));
    }

    let mut total_translated = 0;
    let mut success_all = true;

    for m in &menus {
        let items = match decode_menu(&m.raw_bytes) {
            Ok(it) => it,
            Err(_) => continue,
        };

        let mut changed = false;
        let mut new_items = Vec::new();
        for mut it in items {
            if let Some(trans) = dict.get(&it.text) {
                it.text = trans.clone();
                changed = true;
                total_translated += 1;
            }
            new_items.push(it);
        }

        if changed {
            let new_raw = encode_menu(&new_items);
            let lp_type = RT_MENU as *const u16;
            let wide_name: Option<Vec<u16>> = m.name.as_ref().map(|s| to_wide(s));
            let lp_name = match &wide_name {
                Some(w) => w.as_ptr(),
                None => m.res_id as usize as *const u16,
            };

            let res = unsafe {
                UpdateResourceW(
                    h_update,
                    lp_type,
                    lp_name,
                    m.lang_id,
                    new_raw.as_ptr() as *const std::ffi::c_void,
                    new_raw.len() as u32,
                )
            };
            if res == 0 {
                let err = unsafe { GetLastError() };
                println!("Ошибка при обновлении ресурса: {}", err);
                success_all = false;
            } else {
                let name_str = m.name.clone().unwrap_or_else(|| m.res_id.to_string());
                println!("Пропатчено меню: {} (Lang: 0x{:X})", name_str, m.lang_id);
            }
        }
    }

    let end_res = unsafe { EndUpdateResourceW(h_update, if success_all { 0 } else { 1 }) };
    if end_res == 0 {
        let err = unsafe { GetLastError() };
        return Err(format!("EndUpdateResourceW завершился с ошибкой: {}", err));
    }

    Ok(total_translated)
}

// Встроенный словарь переводов по умолчанию
const EMBEDDED_JSON: &str = include_str!("menu_translation.json");

fn main() {
    println!("============================================================");
    println!("  Патчер системного меню окна игр на движке Majiro (Rust)");
    println!("============================================================\n");

    let args: Vec<String> = env::args().collect();
    let mut exe_targets: Vec<PathBuf> = Vec::new();
    let mut custom_json: Option<PathBuf> = None;

    let mut i = 1;
    while i < args.len() {
        let arg = &args[i];
        if arg.ends_with(".json") {
            custom_json = Some(PathBuf::from(arg));
        } else {
            exe_targets.push(PathBuf::from(arg));
        }
        i += 1;
    }

    let dict: HashMap<String, String> = if let Some(ref jpath) = custom_json {
        println!("Загрузка словаря: {}", jpath.display());
        let content = fs::read_to_string(jpath).expect("Не удалось прочитать JSON-файл перевода");
        serde_json::from_str(&content).expect("Неверный синтаксис JSON")
    } else {
        // Попытка найти menu_translation.json рядом или в подпапках
        let exe_dir = env::current_exe().ok().and_then(|p| p.parent().map(|p| p.to_path_buf()));
        let mut loaded = None;
        if let Some(ref dir) = exe_dir {
            let candidates = [
                dir.join("menu_translation.json"),
                dir.join("tools").join("menu_translation.json"),
                PathBuf::from("menu_translation.json"),
            ];
            for cand in &candidates {
                if cand.exists() {
                    if let Ok(c) = fs::read_to_string(cand) {
                        if let Ok(d) = serde_json::from_str(&c) {
                            println!("Используется внешний словарь: {}", cand.display());
                            loaded = Some(d);
                            break;
                        }
                    }
                }
            }
        }
        loaded.unwrap_or_else(|| {
            println!("Используется встроенный словарь перевода.");
            serde_json::from_str(EMBEDDED_JSON).expect("Встроенный словарь повреждён")
        })
    };

    if exe_targets.is_empty() {
        // Автопоиск в текущей папке и родительской
        let mut search_dirs = vec![PathBuf::from(".")];
        if let Ok(curr) = env::current_dir() {
            search_dirs.push(curr.clone());
            if let Some(parent) = curr.parent() {
                search_dirs.push(parent.to_path_buf());
            }
        }
        if let Some(exe_dir) = env::current_exe().ok().and_then(|p| p.parent().map(|p| p.to_path_buf())) {
            search_dirs.push(exe_dir.clone());
            if let Some(parent) = exe_dir.parent() {
                search_dirs.push(parent.to_path_buf());
            }
        }

        let known_names = ["終わる世界とバースデイ.exe", "レコンキスタ.exe"];
        for dir in &search_dirs {
            for name in &known_names {
                let candidate = dir.join(name);
                if candidate.exists() && !exe_targets.contains(&candidate) {
                    exe_targets.push(candidate);
                }
            }
        }
    }

    if exe_targets.is_empty() {
        println!("[ПРЕДУПРЕЖДЕНИЕ] Не найдены исполняемые файлы (終わる世界とバースデイ.exe или レコンキスタ.exe)!");
        println!("Использование: patch_menu.exe [menu_translation.json] [game.exe ...]");
        println!("\nНажмите Enter для выхода...");
        let _ = std::io::stdin().read_line(&mut String::new());
        return;
    }

    for target in &exe_targets {
        println!("\nОбработка: {}", target.display());
        match patch_exe_menu(target, &dict) {
            Ok(count) => {
                println!(
                    "Успешно! Обновлено пунктов меню: {} в {}",
                    count,
                    target.file_name().and_then(|n| n.to_str()).unwrap_or("")
                );
            }
            Err(e) => {
                println!("[ОШИБКА] {}", e);
            }
        }
    }

    println!("\nГотово! Меню игры переведено.");
}
