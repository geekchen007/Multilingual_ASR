CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    role TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tests (
    id TEXT PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    title TEXT,
    url TEXT,
    language TEXT,
    scene TEXT,
    start REAL,
    end REAL,
    audio TEXT,
    duration REAL DEFAULT 0,
    sha256 TEXT,
    status TEXT,
    blind INTEGER,
    parent_id TEXT REFERENCES tests(id),
    created TEXT
);

CREATE TABLE IF NOT EXISTS results (
    id TEXT PRIMARY KEY,
    test_id TEXT REFERENCES tests(id),
    slot INTEGER,
    provider TEXT,
    snapshot TEXT,
    demo INTEGER,
    status TEXT,
    text TEXT DEFAULT '',
    error TEXT DEFAULT '',
    elapsed REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS votes (
    test_id TEXT REFERENCES tests(id),
    user_id INTEGER REFERENCES users(id),
    choice TEXT,
    created TEXT,
    PRIMARY KEY(test_id,user_id)
);

CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY,
    test_id TEXT REFERENCES tests(id),
    user_id INTEGER REFERENCES users(id),
    result_id TEXT,
    start REAL,
    end REAL,
    selected_text TEXT,
    reference TEXT,
    types TEXT,
    feature TEXT,
    condition TEXT,
    impact TEXT,
    note TEXT,
    status TEXT DEFAULT '待复核',
    owner TEXT DEFAULT '',
    root_cause TEXT DEFAULT '',
    reference_reviewed TEXT DEFAULT '',
    regression INTEGER DEFAULT 0,
    duplicate_of TEXT DEFAULT '',
    revision INTEGER DEFAULT 0,
    created TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    case_id TEXT REFERENCES cases(id),
    user_id INTEGER REFERENCES users(id),
    body TEXT,
    created TEXT
);

CREATE INDEX IF NOT EXISTS tests_user_time ON tests(user_id, created);

CREATE INDEX IF NOT EXISTS results_test ON results(test_id);

CREATE INDEX IF NOT EXISTS cases_test ON cases(test_id);
