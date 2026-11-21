-- Database schema initialization for UPI Fraud Detection
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id UUID PRIMARY KEY,
    sender_upi VARCHAR(100) NOT NULL,
    receiver_upi VARCHAR(100) NOT NULL,
    amount NUMERIC(12, 2) NOT NULL,
    city VARCHAR(100) NOT NULL,
    device_id VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    risk_score INT DEFAULT 0,
    flag_reason TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_transactions_created_at ON transactions (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_transactions_sender_upi ON transactions (sender_upi);
CREATE INDEX IF NOT EXISTS idx_transactions_status ON transactions (status);
