-- Soft Delete 컬럼 추가 마이그레이션
-- chat_sessions 테이블에 is_deleted, deleted_at 컬럼 추가

-- 1. is_deleted 컬럼 추가 (기본값 0 = 삭제되지 않음)
IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('chat_sessions')
    AND name = 'is_deleted'
)
BEGIN
    ALTER TABLE chat_sessions ADD is_deleted BIT DEFAULT 0 NOT NULL;
    PRINT 'Added is_deleted column';
END
ELSE
BEGIN
    PRINT 'is_deleted column already exists';
END
GO

-- 2. deleted_at 컬럼 추가 (삭제된 시간)
IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('chat_sessions')
    AND name = 'deleted_at'
)
BEGIN
    ALTER TABLE chat_sessions ADD deleted_at DATETIME NULL;
    PRINT 'Added deleted_at column';
END
ELSE
BEGIN
    PRINT 'deleted_at column already exists';
END
GO

-- 3. 기존 데이터 업데이트 (혹시 NULL인 경우 0으로)
UPDATE chat_sessions SET is_deleted = 0 WHERE is_deleted IS NULL;
GO

PRINT 'Migration completed: Soft delete columns added to chat_sessions';
