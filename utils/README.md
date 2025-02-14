Este crate es una reimplementación en Rust de un módulo Python (GrpcBigBuffer) que provee funciones y estructuras para procesar “bloques” de archivos y metadatos, así como para gestionar la sincronización entre hilos y la configuración global del entorno.

La idea es contar con:

• Funciones de utilidad como:
  – get_file_hash: cálculo de hash SHA3-256 de un archivo.
  – encode_bytes: codificación de un entero en formato “varint”.
  – get_varint_at_position: búsqueda y decodificación de un varint en una “concatenación” virtual de archivos.
  – get_pruned_block_length y getsize: funciones para obtener tamaños de bloques y directorios que cuentan con un archivo de metadata (en formato JSON).

• Clases/estructuras “Signal” (implementada con Mutex y Condvar) para sincronización entre un “parser” y un “serializer”, y “MemManager” que actúa como un gestor (a modo de context manager en Python).

• Un singleton global (Environment) que contiene parámetros de configuración (como directorios de cache y bloques, profundidad de bloque, etc.) y que puede modificarse mediante la función modify_env. Cuando se modifica el algoritmo hash se elimina el directorio de bloques para forzar regenerar los mismos.

Este crate puede usarse directamente desde Rust o bien importarse en Python mediante pyo3. La implementación trata de respetar la “semántica” y las funcionalidades originales, aprovechando la seguridad y el rendimiento de Rust.