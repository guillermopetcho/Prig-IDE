use prig_fs::{FileManager, FsError};
use std::fs;
use std::path::PathBuf;

fn make_temp_dir() -> PathBuf {
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let dir = std::env::temp_dir().join(format!("prig_fs_test_{}", nanos));
    fs::create_dir_all(&dir).unwrap();
    dir
}

#[test]
fn test_resolve_and_security() {
    let base = make_temp_dir();
    let fm = FileManager::new(base.clone());

    // Path dentro del workspace
    let resolved = fm.resolve("archivo.txt").unwrap();
    assert!(resolved.starts_with(&base));

    // Path fuera del workspace debe dar AccessDenied
    let denied = fm.resolve("/etc/passwd");
    assert!(matches!(denied, Err(FsError::AccessDenied(_))));

    // Path vacío
    let empty = fm.resolve("");
    assert!(matches!(empty, Err(FsError::EmptyPath)));

    let _ = fs::remove_dir_all(&base);
}

#[test]
fn test_get_file_tree_sorting_and_ignored() {
    let base = make_temp_dir();

    fs::create_dir_all(base.join("carpeta_b")).unwrap();
    fs::create_dir_all(base.join("carpeta_a")).unwrap();
    fs::create_dir_all(base.join(".git")).unwrap();
    fs::create_dir_all(base.join("node_modules")).unwrap();
    fs::write(base.join("archivo_z.txt"), "z").unwrap();
    fs::write(base.join("archivo_a.txt"), "a").unwrap();
    fs::write(base.join(".gitignore"), "target/").unwrap();

    let fm = FileManager::new(base.clone());
    let tree = fm.get_file_tree(None, 6);

    // .git y node_modules deben estar ignorados
    assert!(!tree.iter().any(|n| n.name == ".git"));
    assert!(!tree.iter().any(|n| n.name == "node_modules"));

    // .gitignore debe estar presente
    assert!(tree.iter().any(|n| n.name == ".gitignore"));

    // Carpetas deben ir antes que archivos
    assert!(tree[0].is_dir);
    assert_eq!(tree[0].name, "carpeta_a");
    assert!(tree[1].is_dir);
    assert_eq!(tree[1].name, "carpeta_b");

    let _ = fs::remove_dir_all(&base);
}

#[test]
fn test_read_and_write_file() {
    let base = make_temp_dir();
    let fm = FileManager::new(base.clone());

    // Escribir archivo
    let write_res = fm.write_file("sub/test.txt", "Hola Prig Rust");
    assert!(write_res.is_ok());

    // Leer archivo
    let read_res = fm.read_file("sub/test.txt").unwrap();
    assert_eq!(read_res.content, "Hola Prig Rust");
    assert_eq!(read_res.name, "test.txt");
    assert!(!read_res.is_notebook);
    assert!(read_res.notebook_data.is_none());

    let _ = fs::remove_dir_all(&base);
}

#[test]
fn test_read_notebook_structured() {
    let base = make_temp_dir();
    let fm = FileManager::new(base.clone());

    let ipynb_content = r##"{
      "cells": [
        {
          "cell_type": "markdown",
          "source": ["# Titulo Notebook\n", "Texto explicativo"],
          "outputs": []
        },
        {
          "cell_type": "code",
          "execution_count": 1,
          "source": ["print('Hola')\n"],
          "outputs": [
            {
              "output_type": "stream",
              "name": "stdout",
              "text": ["Hola\n"]
            }
          ]
        }
      ],
      "metadata": {},
      "nbformat": 4,
      "nbformat_minor": 2
    }"##;

    fm.write_file("demo.ipynb", ipynb_content).unwrap();

    let res = fm.read_file("demo.ipynb").unwrap();
    assert!(res.is_notebook);
    let nb_data = res.notebook_data.unwrap();
    assert_eq!(nb_data.cells.len(), 2);
    assert_eq!(nb_data.cells[0].cell_type, "markdown");
    assert_eq!(nb_data.cells[1].cell_type, "code");
    assert_eq!(nb_data.cells[1].execution_count, Some(1));
    assert_eq!(nb_data.cells[1].outputs.len(), 1);
    assert_eq!(nb_data.cells[1].outputs[0]["type"], "stream");

    let _ = fs::remove_dir_all(&base);
}

#[test]
fn test_create_and_delete_item() {
    let base = make_temp_dir();
    let fm = FileManager::new(base.clone());

    // Crear carpeta
    fm.create_item("nueva_carpeta", true).unwrap();
    assert!(base.join("nueva_carpeta").is_dir());

    // Crear archivo
    fm.create_item("nueva_carpeta/archivo.txt", false).unwrap();
    assert!(base.join("nueva_carpeta/archivo.txt").is_file());

    // Eliminar archivo
    fm.delete_item("nueva_carpeta/archivo.txt").unwrap();
    assert!(!base.join("nueva_carpeta/archivo.txt").exists());

    // Prohibido eliminar raíz del workspace
    let del_root = fm.delete_item("");
    assert!(matches!(del_root, Err(FsError::CannotDeleteRoot) | Err(FsError::EmptyPath)));

    let _ = fs::remove_dir_all(&base);
}


/// `zz/../../x`: un componente que no existe ya no deja la ruta sin normalizar (antes se escribía FUERA)
#[test]
fn test_no_escapa_por_componente_inexistente() {
    let base = make_temp_dir();
    let ws = base.join("ws");
    std::fs::create_dir_all(&ws).unwrap();
    let fm = FileManager::new(ws.clone());
    for ruta in ["zz/../../fuera.txt", "zz/yy/../../../fuera.txt", "./zz/../../fuera.txt"] {
        assert!(fm.write_file(ruta, "x").is_err(), "{ruta} tenía que rechazarse");
        assert!(fm.create_item(ruta, false).is_err(), "{ruta} tenía que rechazarse");
    }
    assert!(fm.create_item("yy/../../fuera_dir", true).is_err());
    assert!(!base.join("fuera.txt").exists());
    assert!(!base.join("fuera_dir").exists());
    assert!(!ws.join("zz").exists(), "no tiene que crear carpetas intermedias de una ruta rechazada");
    // Lo que se queda dentro sigue funcionando, aunque pase por un componente que no existe
    let dentro = fm.write_file("zz/../dentro.txt", "ok").unwrap();
    assert_eq!(dentro, ws.join("dentro.txt"));
    let _ = std::fs::remove_dir_all(&base);
}

/// Las rutas se comparan como en Python (`os.path.abspath`): sin resolver enlaces
#[test]
fn test_normalizar_como_abspath() {
    use prig_fs::normalizar;
    use std::path::Path;
    assert_eq!(normalizar(Path::new("/a/b/../c/./d")), Path::new("/a/c/d"));
    assert_eq!(normalizar(Path::new("/a/../../..")), Path::new("/"));
    assert_eq!(normalizar(Path::new("/a//b/")), Path::new("/a/b"));
}
