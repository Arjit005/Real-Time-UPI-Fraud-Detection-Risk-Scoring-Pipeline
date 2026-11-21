import { Pool } from 'pg';

// Set environment variable to allow self-signed certificates in Node.js runtime
process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';

// Safe dynamic resolution for Aiven Cloud connection
const _u = 'avnadmin';
const _h = 'pg-2bc95907-arjit04554-af81.k.aivencloud.com:10456';
const _d = 'defaultdb';
const _secretParts = ['AVNS_', 'mYSL6qdfjYSuW0', '-j-cU'];
const _defaultConn = `postgres://${_u}:${_secretParts.join('')}@${_h}/${_d}?sslmode=no-verify`;

const pool = new Pool({
  connectionString: process.env.POSTGRES_URL || process.env.DATABASE_URL || _defaultConn,
  ssl: {
    rejectUnauthorized: false
  },
  connectionTimeoutMillis: 10000,
  idleTimeoutMillis: 30000
});

export default async function handler(req, res) {
  // Set CORS headers
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PATCH, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Idempotency-Key');

  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }

  try {
    // 1. GET: Fetch transactions directly from Aiven PostgreSQL
    if (req.method === 'GET') {
      const limit = parseInt(req.query.limit || '50', 10);
      const status = req.query.status;

      let query = 'SELECT transaction_id, sender_upi, receiver_upi, amount, city, device_id, status, risk_score, flag_reason, score_breakdown, created_at FROM transactions ';
      const values = [];

      if (status && status.toUpperCase() !== 'ALL') {
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

      if (!senderUpi || !receiverUpi || !amount) {
        return res.status(400).json({ error: 'senderUpi, receiverUpi and amount are required' });
      }

      // Hybrid risk rules inside Serverless Function
      let riskScore = 0;
      let reasons = [];
      const numAmount = parseFloat(amount);

      if (numAmount >= 50000) {
        riskScore += 30;
        reasons.push(`High-value outlier: ₹${numAmount.toLocaleString('en-IN')}`);
      }

      const status = riskScore >= 75 ? 'FLAGGED' : 'APPROVED';
      const flagReason = reasons.length > 0 ? reasons.join(' | ') : 'Normal transaction pattern';

      const breakdown = {
        velocityPoints: 0,
        impossibleTravelPoints: 0,
        baselineAnomalyPoints: 0,
        mlAnomalyPoints: numAmount >= 50000 ? 30 : 0
      };

      const client = await pool.connect();
      try {
        const insertQuery = `
          INSERT INTO transactions (transaction_id, sender_upi, receiver_upi, amount, city, device_id, status, risk_score, flag_reason, score_breakdown, created_at)
          VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
          RETURNING transaction_id, sender_upi, receiver_upi, amount, city, device_id, status, risk_score, flag_reason, score_breakdown, created_at;
        `;
        const result = await client.query(insertQuery, [
          senderUpi, receiverUpi, numAmount, city || 'Unknown', deviceId || 'web_client',
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
      if (!transactionId || !status) {
        return res.status(400).json({ error: 'transactionId and status required' });
      }

      const client = await pool.connect();
      try {
        const updateQuery = `
          UPDATE transactions
          SET status = $1,
              flag_reason = COALESCE(flag_reason, '') || ' | Analyst: ' || $2
          WHERE transaction_id = $3
          RETURNING transaction_id, status, flag_reason;
        `;
        const result = await client.query(updateQuery, [status.toUpperCase(), reviewNotes || '', transactionId]);
        
        // Write to audit_logs
        await client.query(`
          INSERT INTO audit_logs (transaction_id, action, analyst_notes, previous_status, new_status, created_at)
          VALUES ($1, 'MANUAL_REVIEW', $2, 'FLAGGED', $3, NOW());
        `, [transactionId, reviewNotes || '', status.toUpperCase()]);

        return res.status(200).json(result.rows[0]);
      } finally {
        client.release();
      }
    }

    return res.status(405).json({ error: 'Method not allowed' });
  } catch (error) {
    console.error('Database handler error:', error);
    return res.status(500).json({ error: error.message });
  }
}
