use std::collections::HashMap;

fn take<'a>(data: &'a [u8], pos: &mut usize, len: usize) -> Result<&'a [u8], String> {
    let part = data.get(*pos..*pos + len).ok_or("Усечённый шаблон диалога")?;
    *pos += len;
    Ok(part)
}

fn word(data: &[u8], pos: &mut usize) -> Result<u16, String> {
    Ok(u16::from_le_bytes(take(data, pos, 2)?.try_into().unwrap()))
}

fn field(
    data: &[u8],
    pos: &mut usize,
    out: &mut Vec<u8>,
    dict: Option<&HashMap<String, String>>,
) -> Result<(), String> {
    let start = *pos;
    let first = word(data, pos)?;
    if first == 0xffff {
        word(data, pos)?;
    } else if first != 0 {
        while word(data, pos)? != 0 {}
        if let Some(dict) = dict {
            let text: Vec<_> = data[start..*pos - 2].chunks_exact(2)
                .map(|b| u16::from_le_bytes([b[0], b[1]])).collect();
            if let Some(translated) = String::from_utf16(&text).ok().and_then(|s| dict.get(&s)) {
                out.extend(translated.encode_utf16().chain([0]).flat_map(u16::to_le_bytes));
                return Ok(());
            }
        }
    }
    out.extend_from_slice(&data[start..*pos]);
    Ok(())
}

pub fn translate(data: &[u8], dict: &HashMap<String, String>) -> Result<Vec<u8>, String> {
    let mut pos = 0;
    let header = take(data, &mut pos, 18)?;
    let style = u32::from_le_bytes(header[..4].try_into().unwrap());
    let count = u16::from_le_bytes(header[8..10].try_into().unwrap());
    let mut out = header.to_vec();
    field(data, &mut pos, &mut out, None)?;
    field(data, &mut pos, &mut out, None)?;
    field(data, &mut pos, &mut out, Some(dict))?;
    if style & 0x40 != 0 {
        out.extend_from_slice(take(data, &mut pos, 2)?);
        field(data, &mut pos, &mut out, None)?;
    }
    for _ in 0..count {
        pos = (pos + 3) & !3;
        out.resize((out.len() + 3) & !3, 0);
        out.extend_from_slice(take(data, &mut pos, 18)?);
        field(data, &mut pos, &mut out, None)?;
        field(data, &mut pos, &mut out, Some(dict))?;
        let start = pos;
        let len = word(data, &mut pos)? as usize;
        pos = start;
        out.extend_from_slice(take(data, &mut pos, len.max(2))?);
    }
    out.extend_from_slice(&data[pos..]);
    Ok(out)
}
