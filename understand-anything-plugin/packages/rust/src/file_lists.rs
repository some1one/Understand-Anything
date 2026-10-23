//! Filename handoffs preserve whitespace and host path semantics.
use crate::Result;
use std::{fs, path::Path};

pub fn read(path: &Path) -> Result<Vec<String>> {
    let raw = fs::read_to_string(path)?;
    let json = path.extension().is_some_and(|s| s.eq_ignore_ascii_case("json"))
        || raw.trim_start().starts_with('[');
    if json {
        // Typed decoding rejects malformed JSON and non-string entries.
        return Ok(serde_json::from_str::<Vec<String>>(&raw)?
            .into_iter().filter(|p| !p.is_empty()).collect());
    }
    // Retain compatibility with older scripts and saved partition inventories.
    Ok(raw.split(if raw.contains('\0') { '\0' } else { '\n' })
        .filter(|s| !s.is_empty()).map(str::to_owned).collect())
}
