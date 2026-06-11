<?php
session_start();

header('Content-Type: application/json; charset=utf-8');

function out($data, $code = 200) {
    http_response_code($code);
    echo json_encode($data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

function db() {
    $path = __DIR__ . '/xls/grades.sqlite';

    if (!is_dir(dirname($path))) {
        mkdir(dirname($path), 0775, true);
    }

    $pdo = new PDO('sqlite:' . $path);
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $pdo->setAttribute(PDO::ATTR_DEFAULT_FETCH_MODE, PDO::FETCH_ASSOC);

    init_db($pdo);

    return $pdo;
}

function column_exists($pdo, $table, $column) {
    $rows = $pdo->query("PRAGMA table_info($table)")->fetchAll();

    foreach ($rows as $row) {
        if ($row['name'] === $column) {
            return true;
        }
    }

    return false;
}

function init_db($pdo) {
    $pdo->exec('PRAGMA foreign_keys = ON');

    $pdo->exec("
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            display_name TEXT,
            password_hash TEXT,
            role TEXT NOT NULL DEFAULT 'teacher',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ");

    if (!column_exists($pdo, 'users', 'password_hash')) {
        $pdo->exec("ALTER TABLE users ADD COLUMN password_hash TEXT");
    }

    if (!column_exists($pdo, 'users', 'is_active')) {
        $pdo->exec("ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1");
    }

    $pdo->exec("
        CREATE TABLE IF NOT EXISTS subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id INTEGER NOT NULL,
            slug TEXT NOT NULL UNIQUE,
            full_name TEXT,
            source_filename TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(teacher_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ");

    $pdo->exec("
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_key TEXT NOT NULL UNIQUE,
            full_name TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ");

    $pdo->exec("
        CREATE TABLE IF NOT EXISTS grades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            subject_id INTEGER NOT NULL,
            I REAL,
            II REAL,
            III REAL,
            F REAL,
            O REAL,
            E REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(student_id, subject_id),
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE,
            FOREIGN KEY(subject_id) REFERENCES subjects(id) ON DELETE CASCADE
        )
    ");

    $pdo->exec("
        CREATE TABLE IF NOT EXISTS teaching_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id INTEGER NOT NULL UNIQUE,
            cycle TEXT,
            professional_module TEXT,
            academic_year TEXT,
            responsible_teacher TEXT,
            programming_units TEXT,
            planned_timing TEXT,
            actual_timing TEXT,
            timing_modifications TEXT,
            developed_activities TEXT,
            used_resources TEXT,
            first_evaluation TEXT,
            second_evaluation TEXT,
            third_evaluation TEXT,
            ordinary_evaluation TEXT,
            extraordinary_evaluation TEXT,
            detected_difficulties TEXT,
            relevant_incidents TEXT,
            diversity_measures TEXT,
            teaching_practice_assessment TEXT,
            improvement_proposals TEXT,
            complementary_activities TEXT,
            closing_text TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(subject_id) REFERENCES subjects(id) ON DELETE CASCADE
        )
    ");

    $count = (int)$pdo->query("SELECT COUNT(*) AS total FROM users")->fetch()['total'];

    if ($count === 0) {
        $stmt = $pdo->prepare("
            INSERT INTO users(username, display_name, password_hash, role, is_active)
            VALUES (?, ?, ?, ?, ?)
        ");

        $stmt->execute([
            'jocarsa',
            'Jocarsa',
            password_hash('jocarsa', PASSWORD_DEFAULT),
            'admin',
            1
        ]);
    }
}

function body() {
    return json_decode(file_get_contents('php://input') ?: '{}', true) ?: [];
}

function verify_password_compat($password, $hash) {
    if (str_starts_with((string)$hash, 'sha256$')) {
        return hash_equals('sha256$' . hash('sha256', $password), $hash);
    }

    return password_verify($password, $hash);
}

function current_user($pdo) {
    if (empty($_SESSION['uid'])) {
        return null;
    }

    $stmt = $pdo->prepare("
        SELECT id, username, display_name, role, is_active
        FROM users
        WHERE id = ? AND is_active = 1
    ");

    $stmt->execute([$_SESSION['uid']]);

    return $stmt->fetch() ?: null;
}

function require_user($pdo) {
    $user = current_user($pdo);

    if (!$user) {
        out(['ok' => false, 'error' => 'No autenticado'], 401);
    }

    return $user;
}

function require_admin($pdo) {
    $user = require_user($pdo);

    if ($user['role'] !== 'admin') {
        out(['ok' => false, 'error' => 'Administrador requerido'], 403);
    }

    return $user;
}

function get_subject($pdo, $id) {
    $user = require_user($pdo);

    $stmt = $pdo->prepare("
        SELECT
            s.*,
            COALESCE(NULLIF(s.full_name, ''), s.slug) AS full_name,
            u.username AS teacher_username,
            u.display_name AS teacher_display_name
        FROM subjects s
        JOIN users u ON u.id = s.teacher_id
        WHERE s.id = ?
    ");

    $stmt->execute([$id]);
    $subject = $stmt->fetch();

    if (!$subject) {
        out(['ok' => false, 'error' => 'Asignatura no encontrada'], 404);
    }

    if ($user['role'] !== 'admin' && (int)$subject['teacher_id'] !== (int)$user['id']) {
        out(['ok' => false, 'error' => 'Sin permiso'], 403);
    }

    return $subject;
}

function memory_fields() {
    return [
        'cycle',
        'professional_module',
        'academic_year',
        'responsible_teacher',
        'programming_units',
        'planned_timing',
        'actual_timing',
        'timing_modifications',
        'developed_activities',
        'used_resources',
        'first_evaluation',
        'second_evaluation',
        'third_evaluation',
        'ordinary_evaluation',
        'extraordinary_evaluation',
        'detected_difficulties',
        'relevant_incidents',
        'diversity_measures',
        'teaching_practice_assessment',
        'improvement_proposals',
        'complementary_activities',
        'closing_text'
    ];
}

function memory_progress_sql() {
    $parts = [];

    foreach (memory_fields() as $field) {
        $parts[] = "CASE WHEN tm.$field IS NOT NULL AND TRIM(tm.$field) <> '' THEN 1 ELSE 0 END";
    }

    $sum = implode(' + ', $parts);
    $total = count(memory_fields());

    return [
        'sum' => $sum,
        'total' => $total
    ];
}

$pdo = db();
$action = $_GET['action'] ?? 'auth_status';

try {
    if ($action === 'auth_status') {
        $user = current_user($pdo);

        out([
            'ok' => true,
            'authenticated' => (bool)$user,
            'user' => $user
        ]);
    }

    if ($action === 'login') {
        $data = body();

        $stmt = $pdo->prepare("
            SELECT *
            FROM users
            WHERE username = ? AND is_active = 1
        ");

        $stmt->execute([trim($data['username'] ?? '')]);
        $user = $stmt->fetch();

        if (!$user || !verify_password_compat($data['password'] ?? '', (string)$user['password_hash'])) {
            out(['ok' => false, 'error' => 'Credenciales incorrectas'], 401);
        }

        $_SESSION['uid'] = (int)$user['id'];

        out([
            'ok' => true,
            'user' => [
                'id' => $user['id'],
                'username' => $user['username'],
                'display_name' => $user['display_name'],
                'role' => $user['role']
            ]
        ]);
    }

    if ($action === 'logout') {
        session_destroy();
        out(['ok' => true]);
    }

    if ($action === 'users') {
        require_admin($pdo);

        $rows = $pdo->query("
            SELECT
                u.id,
                u.username,
                u.display_name,
                u.role,
                u.is_active,
                COUNT(s.id) AS total_subjects
            FROM users u
            LEFT JOIN subjects s ON s.teacher_id = u.id
            GROUP BY u.id
            ORDER BY u.username
        ")->fetchAll();

        out(['ok' => true, 'users' => $rows]);
    }

    if ($action === 'user_save') {
        require_admin($pdo);

        $data = body();
        $id = (int)($data['id'] ?? 0);
        $password = $data['password'] ?? '';

        if (trim($data['username'] ?? '') === '') {
            out(['ok' => false, 'error' => 'Usuario obligatorio'], 400);
        }

        if ($id) {
            if ($password !== '') {
                $stmt = $pdo->prepare("
                    UPDATE users
                    SET username = ?,
                        display_name = ?,
                        role = ?,
                        is_active = ?,
                        password_hash = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ");

                $stmt->execute([
                    $data['username'],
                    $data['display_name'] ?? '',
                    $data['role'] ?? 'teacher',
                    !empty($data['is_active']) ? 1 : 0,
                    password_hash($password, PASSWORD_DEFAULT),
                    $id
                ]);
            } else {
                $stmt = $pdo->prepare("
                    UPDATE users
                    SET username = ?,
                        display_name = ?,
                        role = ?,
                        is_active = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ");

                $stmt->execute([
                    $data['username'],
                    $data['display_name'] ?? '',
                    $data['role'] ?? 'teacher',
                    !empty($data['is_active']) ? 1 : 0,
                    $id
                ]);
            }
        } else {
            if ($password === '') {
                out(['ok' => false, 'error' => 'Contraseña obligatoria'], 400);
            }

            $stmt = $pdo->prepare("
                INSERT INTO users(username, display_name, role, is_active, password_hash)
                VALUES (?, ?, ?, ?, ?)
            ");

            $stmt->execute([
                $data['username'],
                $data['display_name'] ?? '',
                $data['role'] ?? 'teacher',
                !empty($data['is_active']) ? 1 : 0,
                password_hash($password, PASSWORD_DEFAULT)
            ]);
        }

        out(['ok' => true]);
    }

    if ($action === 'user_delete') {
        $user = require_admin($pdo);
        $id = (int)(body()['id'] ?? 0);

        if ($id === (int)$user['id']) {
            out(['ok' => false, 'error' => 'No puedes eliminarte'], 400);
        }

        $stmt = $pdo->prepare("DELETE FROM users WHERE id = ?");
        $stmt->execute([$id]);

        out(['ok' => true]);
    }

    if ($action === 'subjects') {
        $user = require_user($pdo);
        $progress = memory_progress_sql();

        $sql = "
            SELECT
                s.id,
                s.slug,
                COALESCE(NULLIF(s.full_name, ''), s.slug) AS full_name,
                s.source_filename,
                s.teacher_id,
                u.username AS teacher_username,
                u.display_name AS teacher_display_name,
                COUNT(g.id) AS total_grades,
                CASE WHEN tm.id IS NULL THEN 0 ELSE 1 END AS has_memory,
                ({$progress['sum']}) AS memory_filled,
                {$progress['total']} AS memory_total,
                ROUND((({$progress['sum']}) * 100.0) / {$progress['total']}, 0) AS memory_progress
            FROM subjects s
            JOIN users u ON u.id = s.teacher_id
            LEFT JOIN grades g ON g.subject_id = s.id
            LEFT JOIN teaching_memory tm ON tm.subject_id = s.id
        ";

        if ($user['role'] === 'admin') {
            $sql .= "
                GROUP BY s.id
                ORDER BY full_name
            ";

            $stmt = $pdo->query($sql);
        } else {
            $sql .= "
                WHERE s.teacher_id = ?
                GROUP BY s.id
                ORDER BY full_name
            ";

            $stmt = $pdo->prepare($sql);
            $stmt->execute([$user['id']]);
        }

        out([
            'ok' => true,
            'subjects' => $stmt->fetchAll()
        ]);
    }

    if ($action === 'grades') {
        $id = (int)($_GET['subject_id'] ?? 0);
        $subject = get_subject($pdo, $id);

        $stmt = $pdo->prepare("
            SELECT
                st.id AS student_id,
                st.full_name,
                g.I,
                g.II,
                g.III,
                g.F,
                g.O,
                g.E
            FROM grades g
            JOIN students st ON st.id = g.student_id
            WHERE g.subject_id = ?
            ORDER BY st.full_name
        ");

        $stmt->execute([$id]);

        out([
            'ok' => true,
            'subject' => $subject,
            'rows' => $stmt->fetchAll()
        ]);
    }

    if ($action === 'stats') {
        $id = (int)($_GET['subject_id'] ?? 0);
        $subject = get_subject($pdo, $id);
        $result = [];

        foreach (['I', 'II', 'III', 'F', 'O', 'E'] as $evaluation) {
            $stmt = $pdo->prepare("
                SELECT
                    COUNT($evaluation) AS total,
                    SUM(CASE WHEN $evaluation >= 5 THEN 1 ELSE 0 END) AS passed,
                    SUM(CASE WHEN $evaluation < 5 AND $evaluation IS NOT NULL THEN 1 ELSE 0 END) AS failed,
                    AVG($evaluation) AS average
                FROM grades
                WHERE subject_id = ? AND $evaluation IS NOT NULL
            ");

            $stmt->execute([$id]);
            $row = $stmt->fetch();

            $total = (int)$row['total'];
            $passed = (int)$row['passed'];
            $failed = (int)$row['failed'];

            $result[$evaluation] = [
                'total' => $total,
                'passed' => $passed,
                'failed' => $failed,
                'pass_pct' => $total ? round($passed / $total * 100, 2) : 0,
                'fail_pct' => $total ? round($failed / $total * 100, 2) : 0,
                'average' => $row['average'] !== null ? round((float)$row['average'], 2) : null
            ];
        }

        out([
            'ok' => true,
            'subject' => $subject,
            'stats' => $result
        ]);
    }

    if ($action === 'memory_get') {
        $id = (int)($_GET['subject_id'] ?? 0);
        $subject = get_subject($pdo, $id);

        $stmt = $pdo->prepare("
            SELECT *
            FROM teaching_memory
            WHERE subject_id = ?
        ");

        $stmt->execute([$id]);
        $memory = $stmt->fetch();

        if (!$memory) {
            $memory = [
                'subject_id' => $id,
                'professional_module' => $subject['full_name'],
                'responsible_teacher' => $subject['teacher_display_name'] ?: $subject['teacher_username'],
                'closing_text' => 'Quedo a vuestra disposición para cualquier aclaración.'
            ];
        }

        out([
            'ok' => true,
            'subject' => $subject,
            'memory' => $memory
        ]);
    }

    if ($action === 'memory_save') {
        $data = body();
        $id = (int)($data['subject_id'] ?? 0);

        get_subject($pdo, $id);

        $fields = memory_fields();

        $columns = 'subject_id,' . implode(',', $fields);
        $placeholders = '?' . str_repeat(',?', count($fields));

        $updates = [];

        foreach ($fields as $field) {
            $updates[] = "$field = excluded.$field";
        }

        $updates[] = "updated_at = CURRENT_TIMESTAMP";

        $values = [$id];

        foreach ($fields as $field) {
            $values[] = trim((string)($data[$field] ?? ''));
        }

        $stmt = $pdo->prepare("
            INSERT INTO teaching_memory($columns)
            VALUES($placeholders)
            ON CONFLICT(subject_id) DO UPDATE SET " . implode(',', $updates)
        );

        $stmt->execute($values);

        out(['ok' => true]);
    }

    out(['ok' => false, 'error' => 'Acción no válida'], 400);

} catch (Throwable $e) {
    out([
        'ok' => false,
        'error' => $e->getMessage()
    ], 500);
}
