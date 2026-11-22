package com.upi.fraud.service;

import com.upi.fraud.dto.ReviewRequest;
import com.upi.fraud.dto.TransactionRequest;
import com.upi.fraud.dto.TransactionResponse;
import com.upi.fraud.entity.TransactionEntity;
import com.upi.fraud.entity.TransactionStatus;
import com.upi.fraud.repository.TransactionRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.domain.PageRequest;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.time.Instant;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.stream.Collectors;

@Service
public class TransactionService {

    private static final Logger log = LoggerFactory.getLogger(TransactionService.class);

    private final TransactionRepository transactionRepository;
    private final KafkaProducerService kafkaProducerService;
    private final IdempotencyService idempotencyService;

    public TransactionService(TransactionRepository transactionRepository,
                              KafkaProducerService kafkaProducerService,
                              IdempotencyService idempotencyService) {
        this.transactionRepository = transactionRepository;
        this.kafkaProducerService = kafkaProducerService;
        this.idempotencyService = idempotencyService;
    }

    @Transactional
    public TransactionResponse processTransaction(TransactionRequest request, String idempotencyKey) {
        String payloadHash = null;
        String claimToken = null;

        if (idempotencyKey != null && !idempotencyKey.isBlank()) {
            IdempotencyService.ClaimResult claimResult = idempotencyService.claimKey(idempotencyKey, request);
            if (!claimResult.isClaimed()) {
                if (claimResult.getCachedResponse() != null) {
                    return claimResult.getCachedResponse();
                }
                throw new ResponseStatusException(HttpStatus.CONFLICT, "Transaction is currently in progress for this idempotency key. Please retry shortly.");
            }
            claimToken = claimResult.getClaimToken();
            payloadHash = idempotencyService.computePayloadHash(request);
        }

        TransactionEntity entity = new TransactionEntity();
        entity.setSenderUpi(request.getSenderUpi().trim());
        entity.setReceiverUpi(request.getReceiverUpi().trim());
        entity.setAmount(request.getAmount());
        entity.setCity(request.getCity().trim());
        entity.setDeviceId(request.getDeviceId().trim());
        entity.setStatus(TransactionStatus.PENDING);
        entity.setRiskScore(0);
        entity.setFlagReason(null);
        entity.setCreatedAt(Instant.now());

        TransactionEntity saved;
        try {
            saved = transactionRepository.save(entity);
            log.info("Saved transaction {} with status PENDING", saved.getTransactionId());

            Map<String, Object> payload = new HashMap<>();
            payload.put("transactionId", saved.getTransactionId().toString());
            payload.put("senderUpi", saved.getSenderUpi());
            payload.put("receiverUpi", saved.getReceiverUpi());
            payload.put("amount", saved.getAmount().toPlainString());
            payload.put("city", saved.getCity());
            payload.put("deviceId", saved.getDeviceId());
            payload.put("createdAt", saved.getCreatedAt().toString());

            // Synchronous delivery check: If Kafka streaming fails after bounded retries,
            // exception triggers DB rollback and releases the idempotency key.
            publishWithRetry(payload, 3);

            final TransactionResponse response = TransactionResponse.fromEntity(saved);

            if (idempotencyKey != null && !idempotencyKey.isBlank()) {
                idempotencyService.cacheResponse(idempotencyKey, response, payloadHash, claimToken);
            }

            return response;
        } catch (Exception e) {
            if (idempotencyKey != null && !idempotencyKey.isBlank()) {
                idempotencyService.releaseKey(idempotencyKey, claimToken);
            }
            throw e;
        }
    }

    private void publishWithRetry(Map<String, Object> payload, int maxAttempts) {
        int attempt = 0;
        long backoffMs = 100L;
        Exception lastException = null;

        while (attempt < maxAttempts) {
            attempt++;
            try {
                kafkaProducerService.publishRawTransaction(payload);
                return;
            } catch (Exception ex) {
                lastException = ex;
                log.warn("Kafka publish attempt {} failed for txn {}: {}", attempt, payload.get("transactionId"), ex.getMessage());
                if (attempt < maxAttempts) {
                    try {
                        Thread.sleep(backoffMs);
                    } catch (InterruptedException ie) {
                        Thread.currentThread().interrupt();
                        break;
                    }
                    backoffMs *= 2;
                }
            }
        }
        log.error("CRITICAL: Failed to publish transaction {} to Kafka after {} attempts", payload.get("transactionId"), maxAttempts);
        throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Kafka service unavailable for transaction streaming", lastException);
    }

    @Transactional(readOnly = true)
    public List<TransactionResponse> getRecentTransactions(int limit, String statusFilter) {
        int clampedLimit = Math.max(1, Math.min(limit, 100));
        PageRequest pageRequest = PageRequest.of(0, clampedLimit);
        List<TransactionEntity> list;
        if (statusFilter != null && !statusFilter.isBlank() && !statusFilter.equalsIgnoreCase("ALL")) {
            try {
                TransactionStatus status = TransactionStatus.valueOf(statusFilter.toUpperCase());
                list = transactionRepository.findByStatusOrderByCreatedAtDesc(status, pageRequest);
            } catch (IllegalArgumentException e) {
                list = transactionRepository.findAllByOrderByCreatedAtDesc(pageRequest);
            }
        } else {
            list = transactionRepository.findAllByOrderByCreatedAtDesc(pageRequest);
        }
        return list.stream().map(TransactionResponse::fromEntity).collect(Collectors.toList());
    }

    @Transactional
    public TransactionResponse reviewTransaction(UUID transactionId, ReviewRequest reviewRequest) {
        TransactionEntity entity = transactionRepository.findById(transactionId)
                .orElseThrow(() -> new IllegalArgumentException("Transaction not found with ID: " + transactionId));

        TransactionStatus newStatus = TransactionStatus.valueOf(reviewRequest.getStatus().toUpperCase());
        entity.setStatus(newStatus);
        if (reviewRequest.getReviewNotes() != null && !reviewRequest.getReviewNotes().isBlank()) {
            String updatedReason = (entity.getFlagReason() != null ? entity.getFlagReason() + " | " : "")
                    + "Analyst Note: " + reviewRequest.getReviewNotes();
            entity.setFlagReason(updatedReason);
        }

        TransactionEntity updated = transactionRepository.save(entity);
        log.info("Manual review applied for txn {}: Status updated to {}", transactionId, newStatus);
        return TransactionResponse.fromEntity(updated);
    }

    @Transactional
    public void updateScoredTransaction(UUID transactionId, String statusStr, int riskScore, String flagReason) {
        transactionRepository.findById(transactionId).ifPresentOrElse(entity -> {
            try {
                TransactionStatus status = TransactionStatus.valueOf(statusStr.toUpperCase());
                entity.setStatus(status);
            } catch (Exception e) {
                entity.setStatus(TransactionStatus.FLAGGED);
            }
            entity.setRiskScore(riskScore);
            entity.setFlagReason(flagReason);
            transactionRepository.save(entity);
            log.info("Updated transaction {} -> status: {}, risk_score: {}, reason: {}",
                    transactionId, entity.getStatus(), riskScore, flagReason);
        }, () -> log.warn("Received score update for non-existent transaction ID: {}", transactionId));
    }
}
