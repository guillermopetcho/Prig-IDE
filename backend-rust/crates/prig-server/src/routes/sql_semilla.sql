
    CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username VARCHAR(50) NOT NULL UNIQUE,
        email VARCHAR(100) NOT NULL UNIQUE,
        rol VARCHAR(20) DEFAULT 'desarrollador',
        activo BOOLEAN DEFAULT 1,
        creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS productos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sku VARCHAR(30) NOT NULL UNIQUE,
        nombre VARCHAR(120) NOT NULL,
        categoria VARCHAR(50) NOT NULL,
        precio DECIMAL(10,2) NOT NULL,
        stock INTEGER NOT NULL DEFAULT 0,
        estado VARCHAR(20) DEFAULT 'disponible'
    );

    CREATE TABLE IF NOT EXISTS pedidos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER NOT NULL,
        total DECIMAL(10,2) NOT NULL,
        estado VARCHAR(30) DEFAULT 'completado',
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
    );

    CREATE TABLE IF NOT EXISTS metricas_ia (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        modelo VARCHAR(50) NOT NULL,
        tokens_prompt INTEGER NOT NULL,
        tokens_salida INTEGER NOT NULL,
        latencia_ms REAL NOT NULL,
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS logs_actividad (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario VARCHAR(50) NOT NULL,
        accion VARCHAR(100) NOT NULL,
        ip VARCHAR(45) NOT NULL,
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    INSERT OR IGNORE INTO usuarios (id, username, email, rol, activo) VALUES
        (1, 'admin', 'admin@prig.local', 'administrador', 1),
        (2, 'alex_mercer', 'alex@prig.dev', 'desarrollador', 1),
        (3, 'sarah_connor', 'sarah@skynet.shield', 'seguridad', 1),
        (4, 'ada_lovelace', 'ada@analitica.org', 'cientifico_datos', 1),
        (5, 'linus_torvalds', 'linus@kernel.org', 'kernel_dev', 0);

    INSERT OR IGNORE INTO productos (id, sku, nombre, categoria, precio, stock, estado) VALUES
        (1, 'PRIG-BOOK-01', 'Libro: Dominando Rust y Sistemas Distribuidos', 'Libros', 49.99, 120, 'disponible'),
        (2, 'PRIG-KEY-RGB', 'Teclado Mecánico Custom 75% Gateron Oil King', 'Hardware', 189.50, 42, 'disponible'),
        (3, 'PRIG-MON-4K', 'Monitor OLED 32 pulgadas 240Hz 4K', 'Monitores', 899.00, 15, 'disponible'),
        (4, 'PRIG-POD-PRO', 'Micrófono Shure MV7 USB/XLR Podcast', 'Audio', 249.00, 8, 'bajo_stock'),
        (5, 'PRIG-MAT-XXL', 'Mousepad Desk Mat Prig Dark Edition 90x40', 'Accesorios', 29.99, 310, 'disponible');

    INSERT OR IGNORE INTO pedidos (id, usuario_id, total, estado) VALUES
        (1, 2, 239.49, 'completado'),
        (2, 4, 899.00, 'en_camino'),
        (3, 1, 49.99, 'completado'),
        (4, 3, 219.49, 'pendiente'),
        (5, 2, 29.99, 'completado');

    INSERT OR IGNORE INTO metricas_ia (id, modelo, tokens_prompt, tokens_salida, latencia_ms) VALUES
        (1, 'qwen2.5-coder:7b', 1250, 420, 185.4),
        (2, 'qwen2.5-coder:7b', 840, 190, 94.2),
        (3, 'deepseek-r1:8b', 2048, 512, 340.1),
        (4, 'llama3.2:3b', 800, 240, 89.0);

    INSERT OR IGNORE INTO logs_actividad (id, usuario, accion, ip) VALUES
        (1, 'admin', 'LOGIN_EXITOSO', '192.168.1.10'),
        (2, 'alex_mercer', 'DESAFIO_COMPLETADO_PYTHON', '127.0.0.1'),
        (3, 'sarah_connor', 'AUDITORIA_SEGURIDAD_MODULOS', '10.0.0.5'),
        (4, 'ada_lovelace', 'PIPELINE_DESPLIEGUE_RUST', '172.16.0.4');
    