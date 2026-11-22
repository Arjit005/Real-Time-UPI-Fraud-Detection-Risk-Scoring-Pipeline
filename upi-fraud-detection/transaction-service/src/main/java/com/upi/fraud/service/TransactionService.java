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
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
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

        final String finalIdempotencyKey = idempotencyKey;
        final String finalPayloadHash = payloadHash;
        final String finalClaimToken = claimToken;

        TransactionEntity saved;
        try {
            saved = transactionRepository.save(entity);
            log.info("Saved transaction {} with status PENDING", saved.getTransactionId());

            final Map<String, Object> payload = new HashMap<>();
            payload.put("transactionId", saved.getTransactionId().toString());
            payload.put("senderUpi", saved.getSenderUpi());
            payload.put("receiverUpi", saved.getReceiverUpi());
            payload.put("amount", saved.getAmount().toPlainString());
            payload.put("city", saved.getCity());
            payload.put("deviceId", saved.getDeviceId());
            payload.put("createdAt", saved.getCreatedAt().toString());

            final TransactionResponse response = TransactionResponse.fromEntity(saved);

            if (TransactionSynchronizationManager.isSynchronizationActive()) {
                // Outbox coordination: Publish to Kafka and cache response strictly AFTER DB commit confirms
                TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                    @Override
                    public void afterCommit() {
                        if (finalIdempotencyKey != null && !finalIdempotencyKey.isBlank()) {
                            idempotencyService.cacheResponse(finalIdempotencyKey, response, finalPayloadHash, finalClaimToken);
                        }
                        kafkaProducerService.publishRawTransaction(payload);
                    }

                    @Override
                    public void afterCompletion(int status) {
                        if (status != TransactionSynchronization.STATUS_COMMITTED && finalIdempotencyKey != null && !finalIdempotencyKey.isBlank()) {
                            idempotencyService.releaseKey(finalIdempotencyKey, finalClaimToken);
                        }
                    }
                });
            } else {
                // Synchronous fallback (e.g. standalone test execution)
                kafkaProducerService.publishRawTransaction(payload);
                if (finalIdempotencyKey != null && !finalIdempotencyKey.isBlank()) {
                    idempotencyService.cacheResponse(finalIdempotencyKey, response, finalPayloadHash, finalClaimToken);
                }
            }

            return response;
        } catch (Exception e) {
            if (idempotencyKey != null && !idempotencyKey.isBlank()) {
                idempotencyService.releaseKey(idempotencyKey, claimToken);
            }
            throw e;
        }
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
            if (entity.getStatus() == TransactionStatus.APPROVED || entity.getStatus() == TransactionStatus.BLOCKED) {
                log.info("Transaction {} already finalized with status {}, ignoring duplicate scored event",
                        transactionId, entity.getStatus());
                return;
            }
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
