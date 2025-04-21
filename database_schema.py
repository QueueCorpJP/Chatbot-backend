if cursor.fetchone() is None:
    create_usage_limits_table = """
    CREATE TABLE IF NOT EXISTS usage_limits (
        user_id VARCHAR(255) PRIMARY KEY,
        document_uploads_used INT DEFAULT 0,
        document_uploads_limit INT DEFAULT 3,
        questions_used INT DEFAULT 0,
        questions_limit INT DEFAULT 200,
        is_unlimited BOOLEAN DEFAULT FALSE,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """
    cursor.execute(create_usage_limits_table) 