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
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

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
        if (idempotencyKey != null && !idempotencyKey.isBlank()) {
            TransactionResponse cached = idempotencyService.getCachedResponse(idempotencyKey);
            if (cached != null) {
                return cached;
            }
        }

        TransactionEntity entity = new TransactionEntity();
        entity.setTransactionId(UUID.randomUUID());
        entity.setSenderUpi(request.getSenderUpi().trim());
        entity.setReceiverUpi(request.getReceiverUpi().trim());
        entity.setAmount(request.getAmount());
        entity.setCity(request.getCity().trim());
        entity.setDeviceId(request.getDeviceId().trim());
        entity.setStatus(TransactionStatus.PENDING);
        entity.setRiskScore(0);
        entity.setFlagReason(null);
        entity.setCreatedAt(Instant.now());

        TransactionEntity saved = transactionRepository.save(entity);
        log.info("Saved transaction {} with status PENDING", saved.getTransactionId());

        Map<String, Object> payload = new HashMap<>();
        payload.put("transactionId", saved.getTransactionId().toString());
        payload.put("senderUpi", saved.getSenderUpi());
        payload.put("receiverUpi", saved.getReceiverUpi());
        payload.put("amount", saved.getAmount().doubleValue());
        payload.put("city", saved.getCity());
        payload.put("deviceId", saved.getDeviceId());
        payload.put("createdAt", saved.getCreatedAt().toString());

        kafkaProducerService.publishRawTransaction(payload);

        TransactionResponse response = TransactionResponse.fromEntity(saved);

        if (idempotencyKey != null && !idempotencyKey.isBlank()) {
            idempotencyService.cacheResponse(idempotencyKey, response);
        }

        return response;
    }

    @Transactional(readOnly = true)
    public List<TransactionResponse> getRecentTransactions(int limit, String statusFilter) {
        PageRequest pageRequest = PageRequest.of(0, Math.min(limit, 100));
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
