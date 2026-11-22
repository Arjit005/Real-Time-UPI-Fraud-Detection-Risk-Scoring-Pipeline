package com.upi.fraud.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.upi.fraud.dto.ScoredTransactionEvent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Service;

@Service
public class KafkaConsumerService {

    private static final Logger log = LoggerFactory.getLogger(KafkaConsumerService.class);

    private final TransactionService transactionService;
    private final ObjectMapper objectMapper;

    public KafkaConsumerService(TransactionService transactionService, ObjectMapper objectMapper) {
        this.transactionService = transactionService;
        this.objectMapper = objectMapper;
    }

    @KafkaListener(topics = "${app.kafka.topics.scored-transactions:upi.transactions.scored}",
                   groupId = "${spring.kafka.consumer.group-id:upi-transaction-group}")
    public void consumeScoredTransaction(String message) {
        try {
            ScoredTransactionEvent event = objectMapper.readValue(message, ScoredTransactionEvent.class);
            if (event.getTransactionId() == null || event.getStatus() == null || event.getRiskScore() == null) {
                log.warn("Scored event rejected due to missing required fields: transactionId={}, status={}, riskScore={}",
                        event.getTransactionId(), event.getStatus(), event.getRiskScore());
                throw new IllegalArgumentException("Scored event missing required fields (transactionId, status, riskScore)");
            }

            log.info("Processing scored event for transactionId={}: status={}, riskScore={}",
                    event.getTransactionId(), event.getStatus(), event.getRiskScore());

            transactionService.updateScoredTransaction(
                    event.getTransactionId(),
                    event.getStatus(),
                    event.getRiskScore(),
                    event.getFlagReason()
            );
        } catch (Exception e) {
            log.error("Failed to process scored transaction: {}", e.getMessage());
            throw new RuntimeException("Error processing scored transaction: " + e.getMessage(), e);
        }
    }
}
