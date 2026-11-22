import { Pool } from 'pg';

const databaseUrl = process.env.DATABASE_URL || process.env.POSTGRES_URL;
if (!databaseUrl) {
  throw new Error('DATABASE_URL environment variable is required');
}

const pool = new Pool({
  connectionString: databaseUrl,
  ssl: {
    rejectUnauthorized: true
  },
  connectionTimeoutMillis: 10000,
  idleTimeoutMillis: 30000
});

export default async function handler(req, res) {
  // Set CORS headers
  const allowedOrigins = (process.env.CORS_ALLOWED_ORIGINS || 'http://localhost:5173')
    .split(',')
    .map(o => o.trim())
    .filter(Boolean);

  const reqOrigin = req.headers.origin;
  if (reqOrigin && !allowedOrigins.includes(reqOrigin)) {
    return res.status(403).json({ error: 'Origin not allowed' });
  }
  if (reqOrigin) {
    res.setHeader('Access-Control-Allow-Origin', reqOrigin);
  }

  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PATCH, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, X-API-Key, Authorization');

  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }

  // Reject unsupported HTTP methods first
  if (!['GET', 'POST', 'PATCH'].includes(req.method)) {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  // Fail-closed authentication check on ALL non-OPTIONS requests
  const requiredApiKey = process.env.ANALYST_API_KEY;
  if (!requiredApiKey) {
    return res.status(503).json({ error: 'Service Unavailable: Authentication service not configured' });
  }

  const apiKeyHeader = req.headers['x-api-key'];
  const authHeader = req.headers['authorization'];
  const bearerToken = authHeader && authHeader.toLowerCase().startsWith('bearer ') ? authHeader.substring(7).trim() : null;
  const providedKey = apiKeyHeader || bearerToken || authHeader;

    if (!providedKey || providedKey !== requiredApiKey) {
      return res.status(401).json({ error: 'Unauthorized: Invalid or missing API key' });
    }

  try {
    // 1. GET: Fetch transactions directly from Aiven PostgreSQL
    if (req.method === 'GET') {
      const rawLimit = req.query.limit || '50';
      const parsedLimit = Number(rawLimit);
      if (!Number.isInteger(parsedLimit) || parsedLimit <= 0) {
        return res.status(400).json({ error: 'limit must be a positive integer' });
      }
      const limit = Math.max(1, Math.min(parsedLimit, 100));
      const status = req.query.status;

      let query = 'SELECT transaction_id, sender_upi, receiver_upi, amount, city, device_id, status, risk_score, flag_reason, score_breakdown, created_at FROM transactions ';
      const values = [];

      if (status && typeof status === 'string' && status.toUpperCase() !== 'ALL') {
        query += 'WHERE status = $1 ORDER BY created_at DESC LIMIT $2';
        values.push(status.toUpperCase(), limit);
      } else {
        query += 'ORDER BY created_at DESC LIMIT $1';
        values.push(limit);
      }

      const client = await pool.connect();
      try {
        const result = await client.query(query, values);
        const rows = result.rows.map(r => ({
          transactionId: r.transaction_id,
          senderUpi: r.sender_upi,
          receiverUpi: r.receiver_upi,
          amount: parseFloat(r.amount),
          city: r.city,
          deviceId: r.device_id,
          status: r.status,
          riskScore: r.risk_score || 0,
          flagReason: r.flag_reason,
          scoreBreakdown: r.score_breakdown,
          createdAt: r.created_at ? r.created_at.toISOString() : null
        }));
        return res.status(200).json(rows);
      } finally {
        client.release();
      }
    }

    // 2. POST: Ingest new transaction directly on Vercel Serverless Function
    if (req.method === 'POST') {
      const { senderUpi, receiverUpi, amount, city, deviceId } = req.body || {};

      if (typeof amount !== 'number' && typeof amount !== 'string') {
        return res.status(400).json({ error: 'amount must be a valid positive number' });
      }
      const rawAmountStr = String(amount).trim();
      if (!/^\d{1,8}(\.\d{1,2})?$/.test(rawAmountStr)) {
        return res.status(400).json({ error: 'amount must be a valid numeric value up to 8 integer digits and 2 decimal places' });
      }

      const numAmount = Number(rawAmountStr);
      if (!senderUpi || !receiverUpi || !Number.isFinite(numAmount) || numAmount <= 0 || numAmount > 10000000) {
        return res.status(400).json({ error: 'senderUpi, receiverUpi and a positive amount up to ₹10,000,000 are required' });
      }

      const upiRegex = /^[\w.-]+@[\w.-]+$/;
      if (typeof senderUpi !== 'string' || senderUpi.length > 50 || !upiRegex.test(senderUpi)) {
        return res.status(400).json({ error: 'senderUpi must be a valid UPI ID (e.g., user@bank) up to 50 characters' });
      }
      if (typeof receiverUpi !== 'string' || receiverUpi.length > 50 || !upiRegex.test(receiverUpi)) {
        return res.status(400).json({ error: 'receiverUpi must be a valid UPI ID (e.g., merchant@bank) up to 50 characters' });
      }
      if (city && (typeof city !== 'string' || city.length > 50)) {
        return res.status(400).json({ error: 'city must be a string up to 50 characters' });
      }
      if (deviceId && (typeof deviceId !== 'string' || deviceId.length > 50)) {
        return res.status(400).json({ error: 'deviceId must be a string up to 50 characters' });
      }

      let riskScore = 0;
      const reasons = [];

      if (numAmount >= 50000) {
        riskScore += 80;
        reasons.push(`High-value outlier: ₹${numAmount.toLocaleString('en-IN')}`);
      }

      const status = riskScore >= 75 ? 'FLAGGED' : 'PENDING';
      const flagReason = reasons.length > 0 ? reasons.join(' | ') : 'Pending risk engine evaluation';

      const breakdown = {
        velocityPoints: 0,
        impossibleTravelPoints: 0,
        baselineAnomalyPoints: 0,
        mlAnomalyPoints: numAmount >= 50000 ? 80 : 0
      };

      const client = await pool.connect();
      try {
        const insertQuery = `
          INSERT INTO transactions (transaction_id, sender_upi, receiver_upi, amount, city, device_id, status, risk_score, flag_reason, score_breakdown, created_at)
          VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
          RETURNING transaction_id, sender_upi, receiver_upi, amount, city, device_id, status, risk_score, flag_reason, score_breakdown, created_at;
        `;
        const result = await client.query(insertQuery, [
          senderUpi, receiverUpi, rawAmountStr, city || 'Unknown', deviceId || 'web_client',
          status, riskScore, flagReason, JSON.stringify(breakdown)
        ]);
        const r = result.rows[0];

        return res.status(201).json({
          transactionId: r.transaction_id,
          senderUpi: r.sender_upi,
          receiverUpi: r.receiver_upi,
          amount: parseFloat(r.amount),
          city: r.city,
          deviceId: r.device_id,
          status: r.status,
          riskScore: r.risk_score,
          flagReason: r.flag_reason,
          scoreBreakdown: r.score_breakdown,
          createdAt: r.created_at ? r.created_at.toISOString() : null
        });
      } finally {
        client.release();
      }
    }

    // 3. PATCH: Analyst review action (Approve / Block)
    if (req.method === 'PATCH') {
      const { transactionId, status, reviewNotes } = req.body || {};
      if (!transactionId || typeof transactionId !== 'string' || !status || typeof status !== 'string') {
        return res.status(400).json({ error: 'transactionId (string) and status (string) are required' });
      }

      if (reviewNotes !== undefined && reviewNotes !== null) {
        if (typeof reviewNotes !== 'string' || reviewNotes.length > 500) {
          return res.status(400).json({ error: 'reviewNotes must be a string up to 500 characters' });
        }
      }

      const normalizedStatus = status.toUpperCase();
      if (normalizedStatus !== 'APPROVED' && normalizedStatus !== 'BLOCKED') {
        return res.status(400).json({ error: "Invalid status: status must be strictly 'APPROVED' or 'BLOCKED'" });
      }

      const client = await pool.connect();
      try {
        await client.query('BEGIN');

        // Check if row exists and capture previous status
        const checkResult = await client.query(
          'SELECT status FROM transactions WHERE transaction_id = $1 FOR UPDATE;',
          [transactionId]
        );
        if (checkResult.rows.length === 0) {
          await client.query('ROLLBACK');
          return res.status(404).json({ error: 'Transaction not found' });
        }

        const previousStatus = checkResult.rows[0].status;

        // One-way state transition validation: finalized reviews cannot be undone
        if (previousStatus === 'BLOCKED') {
          await client.query('ROLLBACK');
          return res.status(400).json({ error: 'Cannot transition a BLOCKED transaction: terminal state' });
        }
        if (previousStatus === normalizedStatus) {
          await client.query('ROLLBACK');
          return res.status(400).json({ error: `Transaction is already in status ${normalizedStatus}` });
        }

        const sanitizedNotes = (typeof reviewNotes === 'string' ? reviewNotes.trim().substring(0, 500) : '');

        const updateQuery = `
          UPDATE transactions
          SET status = $1,
              flag_reason = CASE 
                WHEN $2 <> '' THEN COALESCE(flag_reason, '') || ' | Analyst: ' || $2
                ELSE flag_reason
              END
          WHERE transaction_id = $3
          RETURNING transaction_id, status, flag_reason;
        `;
        const result = await client.query(updateQuery, [normalizedStatus, sanitizedNotes, transactionId]);

        // Insert into audit_logs only after confirming transaction existence with accurate previous_status
        await client.query(`
          INSERT INTO audit_logs (transaction_id, action, analyst_notes, previous_status, new_status, created_at)
          VALUES ($1, 'MANUAL_REVIEW', $2, $3, $4, NOW());
        `, [transactionId, sanitizedNotes, previousStatus, normalizedStatus]);

        await client.query('COMMIT');
        return res.status(200).json(result.rows[0]);
      } catch (patchErr) {
        try {
          await client.query('ROLLBACK');
        } catch (rbErr) {
          console.error('Error during transaction rollback:', rbErr);
        }
        throw patchErr;
      } finally {
        client.release();
      }
    }

    return res.status(405).json({ error: 'Method not allowed' });
  } catch (error) {
    console.error('Database handler error:', error);
    return res.status(500).json({ error: 'Internal server error' });
  }
}
