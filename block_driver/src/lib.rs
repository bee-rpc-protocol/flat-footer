use std::collections::HashMap;
use std::fs;
use std::io::Write;
use std::path::Path;
use serde_json::Value;

// Constants used in the module.
const BLOCK_LENGTH: usize = 1024;
const METADATA_FILE_NAME: &str = "metadata.json";
const WITHOUT_BLOCK_POINTERS_FILE_NAME: &str = "without_block_pointers.dat";
const BLOCK_DIR: &str = "block_dir";

// This internal enum represents one component of the “buffer” (either data or a file path).
#[derive(Debug, Clone)]
pub enum BufferElement {
    Data(Vec<u8>),
    FilePath(String),
}

// Internal tree type for calculating lengths.
#[derive(Debug, Clone)]
pub enum TreeNode {
    Node(HashMap<u64, TreeNode>),
    Leaf(String),
}

// A helper function to encode an integer as a varint.
fn encode_varint(mut value: u64) -> Vec<u8> {
    let mut buf = Vec::new();
    loop {
        let byte = (value & 0x7F) as u8;
        value >>= 7;
        if value > 0 {
            buf.push(byte | 0x80);
        } else {
            buf.push(byte);
            break;
        }
    }
    buf
}

// Stub: Given a “varint position” and file list, return the decoded position length.
fn get_varint_at_position(varint_pos: u64, _file_list: &Vec<String>) -> Result<u64, String> {
    Ok(100)
}

// Stub: Given a block pointer (as a String), return its pruned length.
fn get_pruned_block_length(value: &String) -> Result<u64, String> {
    Ok(10)
}

// Stub: Validate the “lengths tree” using the provided blocks and file_list.
fn validate_lengths_tree(
    _blocks: &HashMap<String, Vec<Vec<u64>>>,
    _file_list: &Vec<String>,
) -> bool {
    true
}

// Stub: Create a “lengths tree” from blocks.
fn create_lengths_tree(_blocks: &HashMap<String, Vec<Vec<u64>>>) -> HashMap<u64, TreeNode> {
    HashMap::new()
}

/// Recursively computes the wbp (without block pointer) lengths from the tree and file list.
/// Returns a mapping from varint position to wbp-length.
pub fn compute_wbp_lengths(
    tree: &HashMap<u64, TreeNode>,
    file_list: &Vec<String>,
) -> Result<HashMap<u64, u64>, String> {
    fn rec_compute(
        tree: &HashMap<u64, TreeNode>,
        file_list: &Vec<String>,
    ) -> Result<HashMap<u64, (u64, u64)>, String> {
        let mut lengths: HashMap<u64, (u64, u64)> = HashMap::new();
        for (&key, node) in tree.iter() {
            let position_length = get_varint_at_position(key, file_list)?;
            let pruned_length: u64;
            match node {
                TreeNode::Node(inner) => {
                    let sub = rec_compute(inner, file_list)?;
                    let mut total_pruned = 0;
                    for (k, (wbp, p)) in sub.into_iter() {
                        total_pruned += p;
                        lengths.insert(k, (wbp, 0)); // Copy and set augmented pruned length to 0.
                    }
                    pruned_length = total_pruned;
                }
                TreeNode::Leaf(ref s) => {
                    pruned_length = get_pruned_block_length(s)?;
                }
            }
            if pruned_length > position_length {
                return Err("Invalid state: pruned_length greater than real length.".to_string());
            }
            let wbp = position_length - pruned_length;
            let aug = pruned_length
                + (encode_varint(position_length).len() as u64)
                - (encode_varint(position_length - pruned_length).len() as u64);
            lengths.insert(key, (wbp, aug));
        }
        Ok(lengths)
    }
    let rec = rec_compute(tree, file_list)?;
    Ok(rec.into_iter().map(|(k, (v, _))| (k, v)).collect())
}

/// Updates a varint within an in-memory buffer slice.
fn set_varint_value_in_slice(buffer: &Vec<u8>, varint_pos: usize, new_value: u64) -> Result<Vec<u8>, String> {
    let mut value_tmp = new_value;
    let mut varint_bytes = Vec::new();
    loop {
        let byte = (value_tmp & 0x7F) as u8;
        value_tmp >>= 7;
        if value_tmp > 0 {
            varint_bytes.push(byte | 0x80);
        } else {
            varint_bytes.push(byte);
            break;
        }
    }
    if varint_pos >= buffer.len() {
        return Err("varint position out of range".to_string());
    }
    let mut original_varint_length = 0;
    for &b in &buffer[varint_pos..] {
        original_varint_length += 1;
        if b & 0x80 == 0 {
            break;
        }
    }
    let mut new_buffer = Vec::with_capacity(buffer.len() - original_varint_length + varint_bytes.len());
    new_buffer.extend_from_slice(&buffer[..varint_pos]);
    new_buffer.extend_from_slice(&varint_bytes);
    new_buffer.extend_from_slice(&buffer[varint_pos + original_varint_length..]);
    Ok(new_buffer)
}

/// Updates the varint value in our buffer (a Vec of BufferElements) at a given absolute position.
pub fn set_varint_value(varint_pos: usize, buffer: &mut Vec<BufferElement>, new_value: u64) -> Result<(), String> {
    let mut offset = 0;
    for elem in buffer.iter_mut() {
        match elem {
            BufferElement::Data(data) => {
                let obj_size = data.len();
                if offset <= varint_pos && varint_pos < offset + obj_size {
                    let relative_pos = varint_pos - offset;
                    let new_data = set_varint_value_in_slice(data, relative_pos, new_value)?;
                    *data = new_data;
                    return Ok(());
                }
                offset += obj_size;
            }
            BufferElement::FilePath(ref path) => {
                let metadata = fs::metadata(path)
                    .map_err(|e| format!("Error reading file {}: {}", path, e))?;
                let obj_size = metadata.len() as usize;
                if offset <= varint_pos && varint_pos < offset + obj_size {
                    offset += obj_size;
                } else {
                    offset += obj_size;
                }
            }
        }
    }
    Err("Error: varint position not found".to_string())
}

// Protobuf definitions for Block and Hash using Prost.
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct Block {
    #[prost(message, repeated, tag = "1")]
    pub hashes: Vec<Hash>,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct Hash {
    #[prost(bytes, tag = "1")]
    pub value: Vec<u8>,
}

/// Reconstructs the output buffer by modifying varint positions and emitting the final bytes.
/// For BufferElements that are a file path, it uses the file name (assumed to be a hex string)
/// to build a Block message.
pub fn regenerate_buffer(
    lengths: &HashMap<u64, u64>,
    buffer: &mut Vec<BufferElement>,
) -> Result<Vec<Vec<u8>>, String> {
    let mut sorted_lengths: Vec<_> = lengths.iter().collect();
    sorted_lengths.sort_by(|a, b| b.0.cmp(a.0));

    for (&pos, &new_value) in sorted_lengths.iter() {
        set_varint_value(pos as usize, buffer, new_value)?;
    }

    let mut result = Vec::new();
    for elem in buffer.iter() {
        match elem {
            BufferElement::Data(data) => {
                result.push(data.clone());
            }
            BufferElement::FilePath(path) => {
                let parts: Vec<&str> = path.split('/').collect();
                let last = parts.last().ok_or_else(|| "Invalid file path".to_string())?;
                let hash_bytes = hex::decode(last)
                    .map_err(|e| format!("Hex decode error for {}: {}", last, e))?;
                let block = Block {
                    hashes: vec![Hash { value: hash_bytes }],
                };
                let mut buf = Vec::new();
                block.encode(&mut buf).map_err(|e| format!("Protobuf encode error: {}", e))?;
                if buf.len() != BLOCK_LENGTH {
                    return Err("Incorrect block format; block length mismatch.".to_string());
                }
                result.push(buf);
            }
        }
    }
    Ok(result)
}

/// Public API function: generates the WBP file based on a directory name.
/// It reads and processes the metadata, computes new lengths, and writes out the result.
pub fn generate_wbp_file(dirname: &str) -> Result<(), String> {
    let metadata_path = format!("{}/{}", dirname, METADATA_FILE_NAME);
    let metadata_contents = fs::read_to_string(&metadata_path)
        .map_err(|e| format!("Failed to read {}: {}", metadata_path, e))?;
    let json_val: Value = serde_json::from_str(&metadata_contents)
        .map_err(|e| format!("Failed to parse JSON: {}", e))?;
    let json_array = json_val
        .as_array()
        .ok_or_else(|| "Invalid JSON format, expected an array".to_string())?;

    let mut buffer: Vec<BufferElement> = Vec::new();
    let mut file_list: Vec<String> = Vec::new();
    let mut blocks: HashMap<String, Vec<Vec<u64>>> = HashMap::new();

    for entry in json_array.iter() {
        if entry.is_number() {
            let num = entry.as_u64().ok_or_else(|| "Expected integer in metadata".to_string())?;
            let file_path = format!("{}/{}", dirname, num);
            file_list.push(file_path.clone());
            let data = fs::read(&file_path)
                .map_err(|e| format!("Failed to read file {}: {}", file_path, e))?;
            buffer.push(BufferElement::Data(data));
        } else if entry.is_array() {
            let arr = entry.as_array().ok_or_else(|| "Expected array in metadata".to_string())?;
            if arr.is_empty() || !arr[0].is_string() {
                return Err("Invalid block entry in metadata.".to_string());
            }
            let name = arr[0].as_str().ok_or_else(|| "Expected string entry".to_string())?.to_string();
            if arr.len() < 2 {
                return Err("Block entry missing second element".to_string());
            }
            let data_array = arr[1].as_array().ok_or_else(|| "Expected numeric array".to_string())?;
            let mut nums = Vec::new();
            for val in data_array.iter() {
                let num = val.as_u64().ok_or_else(|| "Expected number in block data".to_string())?;
                nums.push(num);
            }
            let block_file = format!("{}/{}", BLOCK_DIR, name);
            file_list.push(block_file.clone());
            buffer.push(BufferElement::FilePath(block_file));
            blocks.entry(name).or_insert(Vec::new()).push(nums);
        } else {
            return Err("Invalid metadata entry type.".to_string());
        }
    }

    if !validate_lengths_tree(&blocks, &file_list) {
        return Err("Validation of lengths tree failed".to_string());
    }

    let tree = create_lengths_tree(&blocks);
    let recalculated_lengths = compute_wbp_lengths(&tree, &file_list)?;
    let regenerated_chunks = regenerate_buffer(&recalculated_lengths, &mut buffer)?;

    let output_path = format!("{}/{}", dirname, WITHOUT_BLOCK_POINTERS_FILE_NAME);
    let mut output_file = fs::File::create(&output_path)
        .map_err(|e| format!("Failed to create output file {}: {}", output_path, e))?;

    for chunk in regenerated_chunks {
        output_file.write_all(&chunk)
            .map_err(|e| format!("Failed to write chunk: {}", e))?;
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    // A basic test case. In a real situation, set up test fixture directories and files.
    #[test]
    fn test_generate_wbp_file() {
        let test_dir = "test_directory"; // Use a test folder prepared for testing.
        let result = generate_wbp_file(test_dir);
        // You can either expect success or a controlled failure, based on your test data.
        // For example:
        assert!(result.is_ok(), "Expected generate_wbp_file to succeed, got: {:?}", result);
    }
}