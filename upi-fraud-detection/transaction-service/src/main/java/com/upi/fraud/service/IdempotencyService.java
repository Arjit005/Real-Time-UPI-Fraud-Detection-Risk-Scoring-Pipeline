package com.upi.fraud.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.upi.fraud.dto.TransactionRequest;
import com.upi.fraud.dto.TransactionResponse;
import jakarta.annotation.PostConstruct;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Duration;
import java.util.Collections;
import java.util.UUID;

@Service
public class IdempotencyService {

    private static final Logger log = LoggerFactory.getLogger(IdempotencyService.class);
    private static final String IDEMPOTENCY_PREFIX = "upi:idempotency:v2:";

    // Lua script: compare claim token, update value and TTL if matched
    private static final String CAS_UPDATE_LUA =
            "local cur = redis.call('get', KEYS[1]); " +
            "if not cur then return 0 end; " +
            "local ok, data = pcall(cjson.decode, cur); " +
            "if ok and data['claimToken'] == ARGV[1] then " +
            "  redis.call('set', KEYS[1], ARGV[2], 'EX', ARGV[3]); " +
            "  return 1; " +
            "else " +
            "  return 0; " +
            "end;";

    // Lua script: compare claim token and delete key if matched
    private static final String CAS_DELETE_LUA =
            "local cur = redis.call('get', KEYS[1]); " +
            "if not cur then return 0 end; " +
            "local ok, data = pcall(cjson.decode, cur); " +
            "if ok and data['claimToken'] == ARGV[1] then " +
            "  redis.call('del', KEYS[1]); " +
            "  return 1; " +
            "else " +
            "  return 0; " +
            "end;";

    private final StringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper;

    @Value("${app.idempotency.ttl-hours:24}")
    private long ttlHours;

    @Value("${app.idempotency.claim-lease-duration-minutes:10}")
    private int claimLeaseMinutes = 10;

    @PostConstruct
    public void validateConfig() {
        if (ttlHours <= 0 || ttlHours > 720) {
            log.warn("Invalid app.idempotency.ttl-hours: {}, defaulting to 24", ttlHours);
            ttlHours = 24;
        }
    }

    public static class CachedIdempotencyRecord {
        private String claimToken;
        private String payloadHash;
        private TransactionResponse response;

        public CachedIdempotencyRecord() {}

        public CachedIdempotencyRecord(String claimToken, String payloadHash, TransactionResponse response) {
            this.claimToken = claimToken;
            this.payloadHash = payloadHash;
            this.response = response;
        }

        public String getClaimToken() { return claimToken; }
        public void setClaimToken(String claimToken) { this.claimToken = claimToken; }

        public String getPayloadHash() { return payloadHash; }
        public void setPayloadHash(String payloadHash) { this.payloadHash = payloadHash; }

        public TransactionResponse getResponse() { return response; }
        public void setResponse(TransactionResponse response) { this.response = response; }
    }

    public static class ClaimResult {
        private final boolean claimed;
        private final String claimToken;
        private final TransactionResponse cachedResponse;

        public ClaimResult(boolean claimed, String claimToken, TransactionResponse cachedResponse) {
            this.claimed = claimed;
            this.claimToken = claimToken;
            this.cachedResponse = cachedResponse;
        }

        public boolean isClaimed() { return claimed; }
        public String getClaimToken() { return claimToken; }
        public TransactionResponse getCachedResponse() { return cachedResponse; }
    }

    public IdempotencyService(StringRedisTemplate redisTemplate, ObjectMapper objectMapper) {
        this.redisTemplate = redisTemplate;
        this.objectMapper = objectMapper;
    }

    private String encodeField(String field) {
        String val = field != null ? field.trim() : "";
        return val.length() + ":" + val;
    }

    public String computePayloadHash(TransactionRequest request) {
        if (request == null) return "";
        String raw = String.join("|",
                encodeField(request.getSenderUpi()),
                encodeField(request.getReceiverUpi()),
                encodeField(request.getAmount() != null ? request.getAmount().stripTrailingZeros().toPlainString() : ""),
                encodeField(request.getCity()),
                encodeField(request.getDeviceId())
        );
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] encodedhash = digest.digest(raw.getBytes(StandardCharsets.UTF_8));
            StringBuilder hexString = new StringBuilder(2 * encodedhash.length);
            for (byte b : encodedhash) {
                String hex = Integer.toHexString(0xff & b);
                if (hex.length() == 1) {
                    hexString.append('0');
                }
                hexString.append(hex);
            }
            return hexString.toString();
        } catch (NoSuchAlgorithmException e) {
            throw new RuntimeException("SHA-256 algorithm not available", e);
        }
    }

    /**
     * Atomically claims the idempotency key using SET NX EX with an ownership token before transaction execution.
     * If key already exists, compares stored hash: returns cached response if matched, or throws 409 Conflict if payload differs or request is in-progress.
     */
    public ClaimResult claimKey(String idempotencyKey, TransactionRequest request) {
        if (idempotencyKey == null || idempotencyKey.isBlank()) {
            return new ClaimResult(true, null, null);
        }

        String cleanKey = idempotencyKey.trim();
        if (cleanKey.length() > 128 || !cleanKey.matches("^[a-zA-Z0-9_.-]+$")) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Idempotency-Key must be 1-128 alphanumeric/hyphen/underscore characters");
        }

        String key = IDEMPOTENCY_PREFIX + cleanKey;
        String currentHash = computePayloadHash(request);
        String claimToken = UUID.randomUUID().toString();

        CachedIdempotencyRecord initialRecord = new CachedIdempotencyRecord(claimToken, currentHash, null);
        String initialJson;
        try {
            initialJson = objectMapper.writeValueAsString(initialRecord);
        } catch (JsonProcessingException e) {
            throw new RuntimeException("Failed to serialize idempotency claim record", e);
        }

        Boolean claimed = false;
        try {
            // In-progress claim has a bounded lease duration
            Duration claimLeaseDuration = Duration.ofMinutes(claimLeaseMinutes);
            claimed = redisTemplate.opsForValue().setIfAbsent(key, initialJson, claimLeaseDuration);
        } catch (Exception e) {
            log.error("Redis unavailable during idempotency claim for key: {}", cleanKey, e);
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Idempotency store temporarily unavailable");
        }

        if (Boolean.TRUE.equals(claimed)) {
            // Successfully claimed key atomically with ownership token
            return new ClaimResult(true, claimToken, null);
        }

        // Key already exists, verify hash & completion state
        try {
            String existingJson = redisTemplate.opsForValue().get(key);
            if (existingJson != null) {
                com.fasterxml.jackson.databind.JsonNode rootNode = objectMapper.readTree(existingJson);
                // Check if JSON has legacy TransactionResponse shape (e.g. has 'transactionId' and lacks 'claimToken')
                if (rootNode.has("transactionId") && !rootNode.has("claimToken")) {
                    TransactionResponse legacyResponse = objectMapper.treeToValue(rootNode, TransactionResponse.class);
                    log.info("Idempotency legacy cache HIT for key: {}", idempotencyKey);
                    return new ClaimResult(false, null, legacyResponse);
                }

                CachedIdempotencyRecord existingRecord = objectMapper.treeToValue(rootNode, CachedIdempotencyRecord.class);
                if (existingRecord != null) {
                    if (existingRecord.getPayloadHash() != null && !existingRecord.getPayloadHash().equals(currentHash)) {
                        log.warn("Idempotency key {} reused with different payload! Stored: {}, Current: {}",
                                idempotencyKey, existingRecord.getPayloadHash(), currentHash);
                        throw new ResponseStatusException(HttpStatus.CONFLICT, "Idempotency key reused with different request payload");
                    }
                    if (existingRecord.getResponse() != null) {
                        log.info("Idempotency cache HIT for key: {}", idempotencyKey);
                        return new ClaimResult(false, null, existingRecord.getResponse());
                    } else {
                        log.warn("Idempotency key {} is currently IN_PROGRESS", idempotencyKey);
                        throw new ResponseStatusException(HttpStatus.CONFLICT, "Transaction is currently in progress for this idempotency key. Please retry shortly.");
                    }
                }
            }
        } catch (ResponseStatusException e) {
            throw e;
        } catch (Exception e) {
            log.error("Failed reading existing idempotency record from Redis: {}", idempotencyKey, e);
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Idempotency store error reading record");
        }

        throw new ResponseStatusException(HttpStatus.CONFLICT, "Transaction is currently in progress for this idempotency key. Please retry shortly.");
    }

    public TransactionResponse checkOrClaimKey(String idempotencyKey, TransactionRequest request) {
        ClaimResult result = claimKey(idempotencyKey, request);
        return result.getCachedResponse();
    }

    public void releaseKey(String idempotencyKey, String claimToken) {
        if (idempotencyKey == null || idempotencyKey.isBlank()) {
            return;
        }
        if (claimToken == null || claimToken.isBlank()) {
            log.warn("Attempted releaseKey without claimToken for key: {}. Ignored to prevent unowned release.", idempotencyKey);
            return;
        }
        String key = IDEMPOTENCY_PREFIX + idempotencyKey.trim();
        try {
            DefaultRedisScript<Long> script = new DefaultRedisScript<>(CAS_DELETE_LUA, Long.class);
            redisTemplate.execute(script, Collections.singletonList(key), claimToken);
            log.info("Released idempotency key: {}", idempotencyKey);
        } catch (Exception e) {
            log.warn("Failed to release idempotency key in Redis: {}", idempotencyKey, e);
        }
    }

    @Deprecated
    public void releaseKey(String idempotencyKey) {
        log.warn("Deprecated tokenless releaseKey called for idempotency key: {}", idempotencyKey);
    }

    public TransactionResponse getCachedResponse(String idempotencyKey) {
        if (idempotencyKey == null || idempotencyKey.isBlank()) {
            return null;
        }
        try {
            String cachedJson = redisTemplate.opsForValue().get(IDEMPOTENCY_PREFIX + idempotencyKey.trim());
            if (cachedJson != null) {
                CachedIdempotencyRecord record = objectMapper.readValue(cachedJson, CachedIdempotencyRecord.class);
                if (record.getResponse() != null) {
                    log.info("Idempotency cache HIT for key: {}", idempotencyKey);
                    return record.getResponse();
                }
            }
        } catch (Exception e) {
            log.warn("Failed to check idempotency key in Redis: {}", idempotencyKey, e);
        }
        return null;
    }

    public void cacheResponse(String idempotencyKey, TransactionResponse response, String payloadHash, String claimToken) {
        if (idempotencyKey == null || idempotencyKey.isBlank() || response == null) {
            return;
        }
        if (claimToken == null || claimToken.isBlank()) {
            log.warn("Attempted cacheResponse without claimToken for key: {}. Overwrite rejected.", idempotencyKey);
            return;
        }
        String key = IDEMPOTENCY_PREFIX + idempotencyKey.trim();
        try {
            CachedIdempotencyRecord record = new CachedIdempotencyRecord(claimToken, payloadHash, response);
            String json = objectMapper.writeValueAsString(record);
            long ttlSeconds = Math.multiplyExact(ttlHours, 3600L);

            DefaultRedisScript<Long> script = new DefaultRedisScript<>(CAS_UPDATE_LUA, Long.class);
            Long updated = redisTemplate.execute(script, Collections.singletonList(key), claimToken, json, String.valueOf(ttlSeconds));
            if (updated != null && updated > 0) {
                log.info("Atomically updated cached response for key: {}", idempotencyKey);
            } else {
                log.warn("CAS update missed for idempotency key: {} (claim token mismatch or expired)", idempotencyKey);
            }
        } catch (Exception e) {
            log.warn("Failed to store idempotency key in Redis: {}", e.getMessage());
        }
    }

    @Deprecated
    public void cacheResponse(String idempotencyKey, TransactionResponse response, String payloadHash) {
        log.warn("Deprecated tokenless cacheResponse called for idempotency key: {}", idempotencyKey);
    }

    @Deprecated
    public void cacheResponse(String idempotencyKey, TransactionResponse response) {
        log.warn("Deprecated tokenless cacheResponse called for idempotency key: {}", idempotencyKey);
    }
}
