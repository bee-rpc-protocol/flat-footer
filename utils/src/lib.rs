use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use serde_json;
use sha3::{Digest, Sha3_256};
use std::fs;
use std::fs::File;
use std::io::{BufReader, Read, Seek, SeekFrom};
use std::path::Path;
use std::sync::{Condvar, Mutex};
use once_cell::sync::Lazy;

// Algunos parámetros globales y constantes
const CHUNK_SIZE: usize = 1024 * 1024;  // 1 MB
const MAX_DIR: u64 = 999999999;
const WITHOUT_BLOCK_POINTERS_FILE_NAME: &str = "wbp.bin";
const METADATA_FILE_NAME: &str = "_.json";
const BLOCK_LENGTH: u64 = 36;

// -------------------------------------------------------------------
// Signal
// -------------------------------------------------------------------

#[pyclass]
pub struct Signal {
    exist: bool,
    // La bandera “open” indica si el buffer sigue activo.
    open: Mutex<bool>,
    condvar: Condvar,
}

#[pymethods]
impl Signal {
    #[new]
    pub fn new(exist: Option<bool>) -> Self {
        let exist = exist.unwrap_or(true);
        let initial_state = if exist { true } else { false };
        Signal {
            exist,
            open: Mutex::new(initial_state),
            condvar: Condvar::new(),
        }
    }

    /// Si existe y está abierto, lo cierra (detiene el buffer); en caso contrario notifica y vuelve a abrir.
    pub fn change(&self) {
        if !self.exist {
            return;
        }
        let mut open = self.open.lock().unwrap();
        if *open {
            *open = false; // Detenemos la entrada.
        } else {
            self.condvar.notify_all();
            *open = true; // Continuamos la entrada.
        }
    }

    /// Si existe y está cerrado, espera a que se notifique.
    pub fn wait(&self) {
        if self.exist {
            let mut open = self.open.lock().unwrap();
            if !*open {
                let _ = self.condvar.wait(open).unwrap();
            }
        }
    }
}

// -------------------------------------------------------------------
// MemManager (dummy, similar a un context manager)
// -------------------------------------------------------------------

#[pyclass]
pub struct MemManager {
    len: usize,
}

#[pymethods]
impl MemManager {
    #[new]
    pub fn new(len: usize) -> Self {
        MemManager { len }
    }

    fn __enter__(slf: PyRef<Self>) -> PyRef<Self> {
        slf
    }

    fn __exit__(
        &self,
        _exc_type: Option<&PyAny>,
        _exc_value: Option<&PyAny>,
        _trace: Option<&PyAny>,
    ) -> PyResult<()> {
        Ok(())
    }
}

// -------------------------------------------------------------------
// Dir (estructura sencilla para agrupar un directorio y un “tipo”)
// -------------------------------------------------------------------

#[pyclass]
pub struct Dir {
    dir: String,
    // Usamos "kind" en lugar de "type" (palabra reservada)
    kind: String,
}

#[pymethods]
impl Dir {
    #[new]
    pub fn new(dir: String, kind: String) -> Self {
        Dir { dir, kind }
    }

    #[getter]
    pub fn get_dir(&self) -> PyResult<&str> {
        Ok(&self.dir)
    }

    #[getter]
    pub fn get_kind(&self) -> PyResult<&str> {
        Ok(&self.kind)
    }
}

// -------------------------------------------------------------------
// Environment Global
// -------------------------------------------------------------------

pub struct Environment {
    pub cache_dir: String,
    pub block_dir: String,
    pub block_depth: u32,
    pub skip_wbp_generation: bool,
    pub hash_type: Vec<u8>,
}

impl Default for Environment {
    fn default() -> Self {
        // Se asume el directorio actual; en una aplicación real se podría parametrizar
        let base = std::env::current_dir().unwrap_or_else(|_| Path::new(".").to_path_buf());
        Environment {
            cache_dir: base.join("__cache__/grpcbigbuffer/").to_string_lossy().into(),
            block_dir: base.join("__block__/").to_string_lossy().into(),
            block_depth: 1,
            skip_wbp_generation: false,
            // Valor por defecto: SHA3_256 (hex en minúsculas)
            hash_type: hex::decode("a7ffc6f8bf1ed76651c14756a061d662f580ff4de43b49fa82d80a4b80f8434a")
                .unwrap(),
        }
    }
}

// Usamos once_cell para crear una variable global mutable (accesible de forma segura)
static ENVIRONMENT: Lazy<Mutex<Environment>> = Lazy::new(|| Mutex::new(Environment::default()));

/// Permite modificar parámetros globales.
/// En este ejemplo se ignora el parámetro mem_manager (ya que en Rust no se utiliza de la misma manera).
#[pyfunction]
pub fn modify_env(
    cache_dir: Option<String>,
    hash_type: Option<String>,  // Se espera un string hexadecimal.
    block_depth: Option<u32>,
    block_dir: Option<String>,
    skip_wbp_generation: Option<bool>,
) -> PyResult<()> {
    let mut env = ENVIRONMENT.lock().unwrap();
    if let Some(c) = cache_dir {
        env.cache_dir = format!("{}{}", c, "grpcbigbuffer/");
    }
    if let Some(bd) = block_depth {
        env.block_depth = bd;
    }
    if let Some(bd) = block_dir {
        env.block_dir = bd;
    }
    if let Some(skip) = skip_wbp_generation {
        env.skip_wbp_generation = skip;
    }
    if let Some(ht) = hash_type {
        let new_hash = hex::decode(ht).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyValueError, _>(format!("Error en hash_type: {:?}", e))
        })?;
        if new_hash != env.hash_type {
            env.hash_type = new_hash;
            // Si se modifica el algoritmo hash, se elimina el directorio de bloques
            if Path::new(&env.block_dir).exists() {
                fs::remove_dir_all(&env.block_dir).map_err(|e| {
                    PyErr::new::<pyo3::exceptions::PyIOError, _>(format!(
                        "Error al eliminar block_dir: {}",
                        e
                    ))
                })?;
            }
        }
    }
    Ok(())
}

// -------------------------------------------------------------------
// Función: get_file_hash
// -------------------------------------------------------------------

#[pyfunction]
pub fn get_file_hash(file_path: String) -> PyResult<String> {
    let file = File::open(&file_path).map_err(|e| {
        PyErr::new::<pyo3::exceptions::PyIOError, _>(format!("Error al abrir {}: {}", file_path, e))
    })?;
    let mut reader = BufReader::new(file);
    let mut hasher = Sha3_256::new();
    let mut buffer = [0u8; 1024];
    loop {
        let n = reader.read(&mut buffer).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyIOError, _>(format!("Error al leer {}: {}", file_path, e))
        })?;
        if n == 0 {
            break;
        }
        hasher.update(&buffer[..n]);
    }
    let result = hasher.finalize();
    Ok(hex::encode(result))
}

// -------------------------------------------------------------------
// Función: create_lengths_tree
// Toma un diccionario (clave: str => lista de listas de enteros)
// y construye un árbol (diccionario anidado) cuyos “hojas” son los id de bloque.
// -------------------------------------------------------------------

#[pyfunction]
pub fn create_lengths_tree(py: Python, pointer_container: &PyDict) -> PyResult<PyObject> {
    let tree = PyDict::new(py);
    // Iteramos sobre (clave, valor)
    for (key, value) in pointer_container.into_iter() {
        let key_str: String = key.extract()?;
        let outer_list: &PyList = value.downcast()?;
        for item in outer_list.iter() {
            let pointer_list: Vec<i32> = item.extract()?;
            let mut current_level = tree;
            let len_list = pointer_list.len();
            for (idx, pointer) in pointer_list.iter().enumerate() {
                if idx == len_list - 1 {
                    current_level.set_item(pointer, &key_str)?;
                } else {
                    let next_level = if let Ok(existing) = current_level.get_item(pointer) {
                        if existing.is_instance::<PyDict>()? {
                            existing.downcast::<PyDict>()?
                        } else {
                            let new_dict = PyDict::new(py);
                            current_level.set_item(pointer, new_dict)?;
                            new_dict
                        }
                    } else {
                        let new_dict = PyDict::new(py);
                        current_level.set_item(pointer, new_dict)?;
                        new_dict
                    };
                    current_level = next_level;
                }
            }
        }
    }
    Ok(tree.to_object(py))
}

// -------------------------------------------------------------------
// Función: encode_bytes
// Codifica un entero en bytes usando el formato varint.
// -------------------------------------------------------------------

#[pyfunction]
pub fn encode_bytes(n: u64) -> PyResult<Vec<u8>> {
    let mut value = n;
    let mut buf = Vec::new();
    loop {
        let towrite = (value & 0x7F) as u8;
        value >>= 7;
        if value != 0 {
            buf.push(towrite | 0x80);
        } else {
            buf.push(towrite);
            break;
        }
    }
    Ok(buf)
}

// -------------------------------------------------------------------
// Función: get_varint_at_position
// Lee un entero codificado en varint a partir de una posición en la “concatenación” de una lista de archivos.
// -------------------------------------------------------------------

#[pyfunction]
pub fn get_varint_at_position(position: u64, file_list: Vec<String>) -> PyResult<u64> {
    let mut total_size = 0u64;
    for file in &file_list {
        let meta = fs::metadata(file).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyIOError, _>(format!("Error con {}: {}", file, e))
        })?;
        total_size += meta.len();
    }
    if position > total_size {
        return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
            "Position {} is out of buffer range.",
            position
        )));
    }
    let mut pos = position;
    let mut file_index = 0;
    while file_index < file_list.len() {
        let meta = fs::metadata(&file_list[file_index]).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyIOError, _>(format!(
                "Error con {}: {}",
                file_list[file_index],
                e
            ))
        })?;
        let file_size = meta.len();
        if pos < file_size {
            break;
        } else {
            pos -= file_size;
            file_index += 1;
        }
    }
    if file_index >= file_list.len() {
        return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(
            "File index out of range.",
        ));
    }
    let mut file = File::open(&file_list[file_index]).map_err(|e| {
        PyErr::new::<pyo3::exceptions::PyIOError, _>(format!(
            "Error al abrir {}: {}",
            file_list[file_index],
            e
        ))
    })?;
    file.seek(SeekFrom::Start(pos)).map_err(|e| {
        PyErr::new::<pyo3::exceptions::PyIOError, _>(format!(
            "Error al posicionar {}: {}",
            file_list[file_index],
            e
        ))
    })?;
    let mut result = 0u64;
    let mut shift = 0;
    loop {
        let mut byte_buf = [0u8; 1];
        let n = file.read(&mut byte_buf).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyIOError, _>(format!(
                "Error al leer de {}: {}",
                file_list[file_index],
                e
            ))
        })?;
        if n == 0 {
            break;
        }
        let byte = byte_buf[0];
        result |= ((byte & 0x7F) as u64) << shift;
        if (byte & 0x80) == 0 {
            break;
        }
        shift += 7;
    }
    Ok(result)
}

// -------------------------------------------------------------------
// Función: get_pruned_block_length
// Retorna el tamaño de un bloque (archivo) restándole BLOCK_LENGTH.
// -------------------------------------------------------------------

#[pyfunction]
pub fn get_pruned_block_length(block_name: String) -> PyResult<u64> {
    let env = ENVIRONMENT.lock().unwrap();
    let path = Path::new(&env.block_dir).join(&block_name);
    let meta = fs::metadata(&path).map_err(|e| {
        PyErr::new::<pyo3::exceptions::PyIOError, _>(format!(
            "Error accediendo a {}: {}",
            path.display(),
            e
        ))
    })?;
    let size = meta.len();
    if size < BLOCK_LENGTH {
        return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(
            "Block size inferior a BLOCK_LENGTH",
        ));
    }
    Ok(size - BLOCK_LENGTH)
}

// -------------------------------------------------------------------
// Función: getsize
// Si el path no existe se retorna 0. Si es directorio, se procesa el archivo
// de metadata (JSON) y se suman los tamaños de los archivos o se usan los bloques podados.
// -------------------------------------------------------------------

#[pyfunction]
pub fn getsize(path: String) -> PyResult<u64> {
    let p = Path::new(&path);
    if !p.exists() {
        return Ok(0);
    }
    if p.is_dir() {
        let meta_path = p.join(METADATA_FILE_NAME);
        let file = File::open(&meta_path).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyIOError, _>(format!(
                "Error al abrir {}: {}",
                meta_path.display(),
                e
            ))
        })?;
        let json_val: serde_json::Value = serde_json::from_reader(file).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyValueError, _>(format!("Error al parsear JSON: {}", e))
        })?;
        let arr = json_val.as_array().ok_or_else(|| {
            PyErr::new::<pyo3::exceptions::PyValueError, _>("El JSON de metadata no es un array")
        })?;
        let mut total_size = 0u64;
        for e in arr {
            if e.is_i64() {
                // Convertimos el entero a string para conformar el path del archivo.
                let file_name = e.to_string();
                let file_path = p.join(file_name);
                let meta = fs::metadata(&file_path).map_err(|e| {
                    PyErr::new::<pyo3::exceptions::PyIOError, _>(format!(
                        "Error accediendo a {}: {}",
                        file_path.display(),
                        e
                    ))
                })?;
                total_size += meta.len();
            } else if e.is_array() {
                let arr_inner = e.as_array().unwrap();
                if arr_inner.is_empty() {
                    continue;
                }
                let block_id_value = &arr_inner[0];
                let block_id = block_id_value.as_str().ok_or_else(|| {
                    PyErr::new::<pyo3::exceptions::PyValueError, _>("El id de bloque no es un string")
                })?;
                total_size += get_pruned_block_length(block_id.to_string())?;
            } else {
                return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(
                    "Entrada inválida en metadata",
                ));
            }
        }
        Ok(total_size)
    } else {
        let meta = fs::metadata(p).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyIOError, _>(format!("Error accediendo a {}: {}", path, e))
        })?;
        Ok(meta.len())
    }
}

// -------------------------------------------------------------------
// Módulo de pyo3
// -------------------------------------------------------------------

#[pymodule]
fn grpcbigbuffer(py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(get_file_hash, m)?)?;
    m.add_function(wrap_pyfunction!(modify_env, m)?)?;
    m.add_function(wrap_pyfunction!(create_lengths_tree, m)?)?;
    m.add_function(wrap_pyfunction!(encode_bytes, m)?)?;
    m.add_function(wrap_pyfunction!(get_varint_at_position, m)?)?;
    m.add_function(wrap_pyfunction!(get_pruned_block_length, m)?)?;
    m.add_function(wrap_pyfunction!(getsize, m)?)?;
    m.add_class::<Signal>()?;
    m.add_class::<MemManager>()?;
    m.add_class::<Dir>()?;
    Ok(())
}