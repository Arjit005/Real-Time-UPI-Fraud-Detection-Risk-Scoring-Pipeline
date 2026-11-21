package com.upi.fraud.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.upi.fraud.dto.TransactionResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.time.Duration;

@Service
public class IdempotencyService {

    private static final Logger log = LoggerFactory.getLogger(IdempotencyService.class);
    private static final String IDEMPOTENCY_PREFIX = "upi:idempotency:";

    private final StringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper;

    @Value("${app.idempotency.ttl-hours:24}")
    private long ttlHours;

    public IdempotencyService(StringRedisTemplate redisTemplate, ObjectMapper objectMapper) {
        this.redisTemplate = redisTemplate;
        this.objectMapper = objectMapper;
    }

    public TransactionResponse getCachedResponse(String idempotencyKey) {
        if (idempotencyKey == null || idempotencyKey.isBlank()) {
            return null;
        }
        try {
            String cachedJson = redisTemplate.opsForValue().get(IDEMPOTENCY_PREFIX + idempotencyKey.trim());
            if (cachedJson != null) {
                log.info("Idempotency cache HIT for key: {}", idempotencyKey);
                return objectMapper.readValue(cachedJson, TransactionResponse.class);
            }
        } catch (Exception e) {
            log.warn("Failed to check idempotency key in Redis: {}", idempotencyKey, e);
        }
        return null;
    }

    public void cacheResponse(String idempotencyKey, TransactionResponse response) {
        if (idempotencyKey == null || idempotencyKey.isBlank() || response == null) {
            return;
        }
        try {
            String json = objectMapper.writeValueAsString(response);
            redisTemplate.opsForValue().set(
                    IDEMPOTENCY_PREFIX + idempotencyKey.trim(),
                    json,
                    Duration.ofHours(ttlHours)
            );
            log.info("Cached response for idempotency key: {} with TTL {} hours", idempotencyKey, ttlHours);
        } catch (JsonProcessingException e) {
            log.error("Failed to serialize response for idempotency caching: {}", idempotencyKey, e);
        } catch (Exception e) {
            log.warn("Failed to store idempotency key in Redis: {}", idempotencyKey, e);
        }
    }
}
