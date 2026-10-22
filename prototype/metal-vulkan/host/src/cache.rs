//! Private, bounded, checksummed local records. A rejected entry is a miss and is rebuilt.
use sha2::{Digest, Sha256};
use std::fs::{self, OpenOptions};
use std::io::{self, Read, Write};
use std::path::Path;
use std::sync::atomic::{AtomicU64, Ordering};

const MAGIC: &[u8; 8] = b"QM2CACHE";
const HEADER: usize = 8 + 4 + 32 + 8;
const CHECKSUM: usize = 32;
pub const AIR: u32 = 1;
pub const LIBRARY: u32 = 2;
pub const RECIPE: u32 = 3;
pub const MAX_LIBRARY: u64 = 64 << 20;
pub static REJECTED: AtomicU64 = AtomicU64::new(0);

/// Remove old records at startup. The scan keeps at most 16,384 entries in memory; excess
/// records are misses rather than an unbounded index. Active temporary writers are left alone.
pub fn trim(directory: &Path, capacity: u64, entries: usize) -> io::Result<u64> {
    let rows = match fs::read_dir(directory) {
        Ok(rows) => rows,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(0),
        Err(error) => return Err(error),
    };
    let mut files = Vec::new();
    let mut total = 0u64;
    for row in rows.flatten() {
        let path = row.path();
        let metadata = match row.metadata() {
            Ok(data) if data.is_file() => data,
            _ => continue,
        };
        if path.extension().and_then(|s| s.to_str()) != Some("qmc") {
            if path
                .extension()
                .and_then(|s| s.to_str())
                .is_some_and(|s| s.starts_with("tmp-"))
                && metadata
                    .modified()
                    .ok()
                    .and_then(|time| time.elapsed().ok())
                    .is_some_and(|age| age.as_secs() > 3600)
            {
                let _ = fs::remove_file(path);
            }
            continue;
        }
        if files.len() >= 16_384 {
            let _ = fs::remove_file(path);
            continue;
        }
        total = total.saturating_add(metadata.len());
        files.push((
            metadata.modified().unwrap_or(std::time::UNIX_EPOCH),
            path,
            metadata.len(),
        ));
    }
    files.sort_unstable_by_key(|row| row.0);
    let mut remaining = files.len();
    for (_, path, bytes) in files {
        if total <= capacity && remaining <= entries {
            break;
        }
        if fs::remove_file(path).is_ok() {
            total = total.saturating_sub(bytes);
            remaining -= 1;
        }
    }
    Ok(total)
}

pub fn hash(data: &[u8]) -> [u8; 32] {
    Sha256::digest(data).into()
}

pub fn hex(hash: &[u8; 32]) -> String {
    use std::fmt::Write;
    let mut text = String::with_capacity(64);
    for byte in hash {
        let _ = write!(text, "{byte:02x}");
    }
    text
}

pub fn unhex(text: &str) -> Option<[u8; 32]> {
    if text.len() != 64 || !text.bytes().all(|c| c.is_ascii_hexdigit()) {
        return None;
    }
    let mut key = [0; 32];
    for (index, byte) in key.iter_mut().enumerate() {
        *byte = u8::from_str_radix(&text[index * 2..index * 2 + 2], 16).ok()?;
    }
    Some(key)
}

pub fn read(path: &Path, kind: u32, key: &[u8; 32], limit: u64) -> io::Result<Option<Vec<u8>>> {
    let file = match fs::File::open(path) {
        Ok(file) => file,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error),
    };
    let maximum = limit + (HEADER + CHECKSUM) as u64;
    let length = file.metadata()?.len();
    let reject = || {
        REJECTED.fetch_add(1, Ordering::Relaxed);
        let _ = fs::remove_file(path);
        Ok(None)
    };
    if length < (HEADER + CHECKSUM) as u64 || length > maximum {
        return reject();
    }
    let mut bytes = Vec::with_capacity(length as usize);
    file.take(maximum + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 != length || bytes.get(..8) != Some(MAGIC) {
        return reject();
    }
    let stored_kind = u32::from_le_bytes(bytes[8..12].try_into().unwrap());
    let payload = u64::from_le_bytes(bytes[44..52].try_into().unwrap());
    if stored_kind != kind
        || bytes[12..44] != *key
        || payload != length - (HEADER + CHECKSUM) as u64
    {
        return reject();
    }
    let end = bytes.len() - CHECKSUM;
    if bytes[end..] != hash(&bytes[..end]) {
        return reject();
    }
    Ok(Some(bytes[HEADER..end].to_vec()))
}

pub fn write(path: &Path, kind: u32, key: &[u8; 32], bytes: &[u8], limit: u64) -> io::Result<()> {
    if bytes.len() as u64 > limit {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "cache entry exceeds its bound",
        ));
    }
    let parent = path
        .parent()
        .ok_or_else(|| io::Error::other("cache entry has no directory"))?;
    fs::create_dir_all(parent)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(parent, fs::Permissions::from_mode(0o700))?;
    }
    static NEXT: AtomicU64 = AtomicU64::new(0);
    let temporary = path.with_extension(format!(
        "tmp-{}-{}",
        std::process::id(),
        NEXT.fetch_add(1, Ordering::Relaxed)
    ));
    let result = (|| {
        let mut options = OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let mut file = options.open(&temporary)?;
        let mut header = Vec::with_capacity(HEADER);
        header.extend(MAGIC);
        header.extend(kind.to_le_bytes());
        header.extend(key);
        header.extend((bytes.len() as u64).to_le_bytes());
        let mut checksum = Sha256::new();
        checksum.update(&header);
        checksum.update(bytes);
        file.write_all(&header)?;
        file.write_all(bytes)?;
        file.write_all(&checksum.finalize())?;
        drop(file);
        fs::rename(&temporary, path)
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn corruption_truncation_foreign_keys_and_oversized_entries_are_misses() {
        let root = std::env::temp_dir().join(format!("quadra-cache-test-{}", std::process::id()));
        fs::create_dir_all(&root).unwrap();
        let path = root.join("entry");
        let key = hash(b"source");
        let content = b"an authored cache entry";
        write(&path, AIR, &key, content, 1024).unwrap();
        let frame = fs::read(&path).unwrap();
        assert_eq!(read(&path, AIR, &key, 1024).unwrap().unwrap(), content);
        for data in [
            frame[..20].to_vec(),
            {
                let mut broken = frame.clone();
                broken[HEADER] ^= 1;
                broken
            },
            vec![0; 2048],
        ] {
            fs::write(&path, data).unwrap();
            assert!(read(&path, AIR, &key, 1024).unwrap().is_none());
            assert!(!path.exists());
        }
        write(&path, AIR, &key, content, 1024).unwrap();
        assert!(read(&path, AIR, &hash(b"another source"), 1024)
            .unwrap()
            .is_none());
        assert!(write(&path, AIR, &key, &[0; 2048], 1024).is_err());
        fs::remove_dir_all(root).unwrap();
    }
}
