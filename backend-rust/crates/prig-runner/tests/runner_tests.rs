use prig_runner::{CodeRunner, RunnerError};
use std::fs;

#[tokio::test]
async fn test_run_python_script() {
    let runner = CodeRunner::new();
    let temp_script = std::env::temp_dir().join("test_prig_run.py");
    fs::write(&temp_script, "print('PRIG_RUST_RUNNER_OK')\n").unwrap();

    let res = runner
        .run_file(&temp_script.to_string_lossy(), None, 10, None)
        .await
        .unwrap();

    assert!(res.success);
    assert_eq!(res.exit_code, 0);
    assert!(res.stdout.contains("PRIG_RUST_RUNNER_OK"));

    let _ = fs::remove_file(temp_script);
}

#[tokio::test]
async fn test_run_timeout_exceeded() {
    let runner = CodeRunner::new();
    let temp_script = std::env::temp_dir().join("test_prig_infinite.py");
    fs::write(&temp_script, "import time\ntime.sleep(10)\n").unwrap();

    let res = runner
        .run_file(&temp_script.to_string_lossy(), None, 1, None)
        .await;

    assert!(matches!(res, Err(RunnerError::Timeout(1))));

    let _ = fs::remove_file(temp_script);
}


/// Cancelar mata también a los hijos del programa y se informa como cancelación
#[tokio::test]
async fn test_cancelar_mata_al_grupo() {
    let runner = CodeRunner::new();
    let dir = std::env::temp_dir().join(format!("prig_runner_grupo_{}", std::process::id()));
    fs::create_dir_all(&dir).unwrap();
    let marca = dir.join("hijo_vivo");
    let script = dir.join("padre.py");
    fs::write(&script, format!(
        "import subprocess, sys, time\nsubprocess.Popen([sys.executable, '-c', 'import time; time.sleep(1.5); open({:?}, \"w\").write(\"x\")'])\ntime.sleep(30)\n",
        marca.to_string_lossy()
    )).unwrap();
    let r2 = runner.clone();
    let tarea = tokio::spawn(async move { r2.run_file(&script.to_string_lossy(), None, 20, Some("prueba".into())).await });
    tokio::time::sleep(std::time::Duration::from_millis(500)).await;
    assert!(runner.cancel("prueba").await);
    let res = tarea.await.unwrap().unwrap();
    assert!(res.cancelled && !res.success);
    tokio::time::sleep(std::time::Duration::from_millis(2000)).await;
    assert!(!marca.exists(), "el hijo tenía que morir con el grupo");
    let _ = fs::remove_dir_all(&dir);
}

/// Un programa que escribe sin parar no llena la memoria: se guarda hasta el tope
#[tokio::test]
async fn test_salida_con_tope() {
    let runner = CodeRunner::new();
    let script = std::env::temp_dir().join(format!("prig_runner_mucho_{}.py", std::process::id()));
    fs::write(&script, "import sys\nfor _ in range(6000):\n    sys.stdout.write('x' * 1000 + '\\n')\n").unwrap();
    let res = runner.run_file(&script.to_string_lossy(), None, 20, None).await.unwrap();
    assert!(res.success);
    assert!(res.stdout.len() < 2 * 1024 * 1024 + 100);
    assert!(res.stdout.ends_with("[... salida recortada por Prig ...]\n"));
    let _ = fs::remove_file(script);
}
