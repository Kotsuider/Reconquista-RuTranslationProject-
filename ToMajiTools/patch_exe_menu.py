# -*- coding: utf-8 -*-
"""
Утилита для локализации системного меню окна Win32 (.exe) игр на движке Majiro.
Извлекает оригинальные меню, переводит их по словарю menu_translation.json
и обновляет ресурсы в исполняемом файле (.exe).
"""

import sys
import os
import struct
import json
import shutil
import ctypes
from ctypes import wintypes

def parse_pe_menus(exe_path):
    with open(exe_path, "rb") as f:
        data = f.read()

    if data[:2] != b"MZ":
        raise ValueError("Not a valid PE executable (no MZ header)")
    pe_offset = struct.unpack("<I", data[0x3C:0x40])[0]
    if data[pe_offset:pe_offset+4] != b"PE\x00\x00":
        raise ValueError("Not a valid PE signature")

    opt_header_offset = pe_offset + 24
    opt_header_size = struct.unpack("<H", data[pe_offset+20:pe_offset+22])[0]
    num_sections = struct.unpack("<H", data[pe_offset+6:pe_offset+8])[0]
    rsrc_dir_offset = opt_header_offset + 96 + 2 * 8
    rsrc_va, rsrc_size = struct.unpack("<II", data[rsrc_dir_offset:rsrc_dir_offset+8])

    section_table_offset = opt_header_offset + opt_header_size
    rsrc_raw = None
    rsrc_sec_va = None
    rsrc_sec_raw = None
    for i in range(num_sections):
        sec_offset = section_table_offset + i * 40
        sec_va = struct.unpack("<I", data[sec_offset+12:sec_offset+16])[0]
        sec_raw_size = struct.unpack("<I", data[sec_offset+16:sec_offset+20])[0]
        sec_raw_ptr = struct.unpack("<I", data[sec_offset+20:sec_offset+24])[0]
        if sec_va <= rsrc_va < sec_va + sec_raw_size:
            rsrc_raw = sec_raw_ptr + (rsrc_va - sec_va)
            rsrc_sec_va = sec_va
            rsrc_sec_raw = sec_raw_ptr
            break

    if not rsrc_raw:
        raise ValueError("Could not find .rsrc section")

    def get_entries(offset):
        c_names, c_ids = struct.unpack("<HH", data[offset+12:offset+16])
        res = []
        for i in range(c_names + c_ids):
            entry = offset + 16 + i * 8
            id_val, off_val = struct.unpack("<II", data[entry:entry+8])
            name = None
            if id_val & 0x80000000:
                name_offset = rsrc_raw + (id_val & 0x7FFFFFFF)
                n_len = struct.unpack("<H", data[name_offset:name_offset+2])[0]
                name = data[name_offset+2:name_offset+2+n_len*2].decode("utf-16le", errors="replace")
            res.append((id_val, name, bool(off_val & 0x80000000), rsrc_raw + (off_val & 0x7FFFFFFF)))
        return res

    menus = []
    for tid, tname, is_dir, off in get_entries(rsrc_raw):
        if tid == 4: # RT_MENU
            for rid, rname, is_dir2, off2 in get_entries(off):
                for lid, lname, is_dir3, off3 in get_entries(off2):
                    data_rva, data_sz, data_cp, data_res = struct.unpack("<IIII", data[off3:off3+16])
                    data_file_offset = rsrc_sec_raw + (data_rva - rsrc_sec_va)
                    menu_bytes = data[data_file_offset:data_file_offset+data_sz]
                    menus.append({
                        "res_id": rid,
                        "name": rname,
                        "lang_id": lid,
                        "raw_bytes": menu_bytes
                    })
    return menus

def decode_standard_menu(menu_bytes):
    ver, offset = struct.unpack("<HH", menu_bytes[:4])
    if ver != 0:
        raise ValueError(f"Unsupported menu version: {ver} (expected standard MENU ver 0)")
    items = []
    pos = 4
    while pos < len(menu_bytes):
        flags = struct.unpack("<H", menu_bytes[pos:pos+2])[0]
        pos += 2
        if not (flags & 0x10): # MF_POPUP = 0x0010
            item_id = struct.unpack("<H", menu_bytes[pos:pos+2])[0]
            pos += 2
        else:
            item_id = None
        str_pos = pos
        str_end = str_pos
        while str_end + 2 <= len(menu_bytes) and menu_bytes[str_end:str_end+2] != b"\x00\x00":
            str_end += 2
        text = menu_bytes[str_pos:str_end].decode("utf-16le", errors="replace")
        pos = str_end + 2
        items.append({"flags": flags, "id": item_id, "text": text})
    return items

def encode_standard_menu(items):
    out = bytearray()
    out += struct.pack("<HH", 0, 0)
    for it in items:
        flags = it["flags"]
        item_id = it["id"]
        text = it["text"]
        out += struct.pack("<H", flags)
        if not (flags & 0x10):
            out += struct.pack("<H", item_id if item_id is not None else 0)
        encoded_text = text.encode("utf-16le") + b"\x00\x00"
        out += encoded_text
    return bytes(out)

def patch_executable_menu(exe_path, translations_dict):
    if not os.path.exists(exe_path):
        print(f"File not found: {exe_path}")
        return False

    bak_path = exe_path + ".bak"
    if not os.path.exists(bak_path):
        print(f"Creating backup: {bak_path}")
        shutil.copyfile(exe_path, bak_path)

    menus = parse_pe_menus(exe_path)
    if not menus:
        print("No MENU resources found in executable.")
        return False

    kernel32 = ctypes.windll.kernel32
    BeginUpdateResourceW = kernel32.BeginUpdateResourceW
    BeginUpdateResourceW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL]
    BeginUpdateResourceW.restype = wintypes.HANDLE

    UpdateResourceW = kernel32.UpdateResourceW
    UpdateResourceW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.WORD, wintypes.LPVOID, wintypes.DWORD]
    UpdateResourceW.restype = wintypes.BOOL

    EndUpdateResourceW = kernel32.EndUpdateResourceW
    EndUpdateResourceW.argtypes = [wintypes.HANDLE, wintypes.BOOL]
    EndUpdateResourceW.restype = wintypes.BOOL

    hUpdate = BeginUpdateResourceW(exe_path, False)
    if not hUpdate:
        err = kernel32.GetLastError()
        print(f"Failed to BeginUpdateResourceW on {exe_path}. Error code: {err}")
        return False

    success_all = True
    total_replaced_strings = 0

    for m in menus:
        res_name = m["name"]
        res_id = m["res_id"]
        lang_id = m["lang_id"]
        raw = m["raw_bytes"]

        try:
            items = decode_standard_menu(raw)
        except Exception as e:
            print(f"Skipping menu {res_name or res_id}: {e}")
            continue

        changed = False
        for it in items:
            orig = it["text"]
            if orig in translations_dict:
                it["text"] = translations_dict[orig]
                changed = True
                total_replaced_strings += 1

        if changed:
            new_raw = encode_standard_menu(items)
            lpType = ctypes.cast(ctypes.c_void_p(4), wintypes.LPCWSTR) # RT_MENU
            if res_name:
                lpName = res_name
            else:
                lpName = ctypes.cast(ctypes.c_void_p(res_id), wintypes.LPCWSTR)
            
            buf = ctypes.create_string_buffer(new_raw)
            ok = UpdateResourceW(hUpdate, lpType, lpName, lang_id, buf, len(new_raw))
            if not ok:
                err = kernel32.GetLastError()
                print(f"UpdateResourceW failed for {res_name or res_id}. Error: {err}")
                success_all = False
            else:
                print(f"Patched menu: {res_name or res_id} (Lang: 0x{lang_id:X})")

    end_ok = EndUpdateResourceW(hUpdate, not success_all)
    if not end_ok:
        err = kernel32.GetLastError()
        print(f"EndUpdateResourceW failed. Error: {err}")
        return False

    print(f"Successfully updated menu resources in {os.path.basename(exe_path)}. Total strings translated: {total_replaced_strings}")
    return True

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(base_dir, "menu_translation.json")
    if not os.path.exists(json_path):
        # Fallback to parent dir or current dir
        json_path = os.path.join(os.path.dirname(base_dir), "tools", "menu_translation.json")
    
    if len(sys.argv) > 1 and sys.argv[1].endswith(".json"):
        json_path = sys.argv[1]
        target_exes = sys.argv[2:]
    else:
        target_exes = sys.argv[1:]

    if not os.path.exists(json_path):
        print(f"Error: translation json not found at {json_path}")
        sys.exit(1)

    with open(json_path, "r", encoding="utf-8") as f:
        translations = json.load(f)

    if not target_exes:
        # Default scan known executables in parent folder
        parent = os.path.dirname(base_dir)
        possible_exes = [
            os.path.join(parent, "終わる世界とバースデイ.exe"),
            os.path.join(parent, "レコンキスタ.exe")
        ]
        target_exes = [e for e in possible_exes if os.path.exists(e)]

    if not target_exes:
        print("No target executable specified or found.")
        print("Usage: python patch_exe_menu.py [path_to_translation.json] <path_to_exe1> [path_to_exe2...]")
        sys.exit(1)

    for exe in target_exes:
        print(f"\nProcessing: {exe}")
        patch_executable_menu(exe, translations)

if __name__ == "__main__":
    main()
