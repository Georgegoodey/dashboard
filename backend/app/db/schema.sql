CREATE SEQUENCE IF NOT EXISTS doc_id_seq;
CREATE SEQUENCE IF NOT EXISTS chunk_id_seq;

CREATE TABLE IF NOT EXISTS documents (
    id           BIGINT PRIMARY KEY DEFAULT nextval('doc_id_seq'),
    filename     VARCHAR NOT NULL,
    content_type VARCHAR,
    n_chunks     INTEGER DEFAULT 0,
    created_at   TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS chunks (
    id          BIGINT PRIMARY KEY DEFAULT nextval('chunk_id_seq'),
    document_id BIGINT NOT NULL,
    chunk_index INTEGER NOT NULL,
    text        VARCHAR NOT NULL,
    embedding   FLOAT[__DIM__]
);

CREATE TABLE IF NOT EXISTS messages (
    session_id VARCHAR NOT NULL,
    role       VARCHAR NOT NULL,
    content    VARCHAR NOT NULL,
    created_at TIMESTAMP DEFAULT current_timestamp
);
